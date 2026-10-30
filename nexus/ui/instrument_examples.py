"""One evidence-led explanation of the instruments behind an allocation."""

from copy import deepcopy
from html import escape
from urllib.parse import urlparse

import streamlit as st

from ..history import anexar_revision_investigacion
from ..instrument_knowledge import KnowledgeStore
from ..instruments import query_examples
from ..state import is_result_stale
from .common import fecha_fmt, moneda_fmt


def render(result, snapshot):
    st.markdown("## Instrumentos recomendados para tu simulación")
    st.write("Mercado argentino · selección independiente del broker.")
    st.caption("La selección compara datos públicos. Antes de operar, confirmá las condiciones y costos de tu intermediario.")

    saved = result.get("ejemplos_instrumentos")
    if saved is None and not is_result_stale():
        with st.spinner("Consultando referencias públicas para esta evaluación…"):
            saved = _query_and_freeze(result, snapshot, previous=None)
    label = "Actualizar investigación" if saved else "Consultar investigación"
    if st.button(label, key="consultar_ejemplos_instrumentos", width="stretch"):
        with st.spinner("Actualizando referencias públicas…"):
            saved = _query_and_freeze(result, snapshot, previous=saved)

    if not saved:
        st.info("Esta evaluación no tiene una investigación guardada. Podés consultar referencias para las respuestas originales.")
        return

    research = saved.get("investigacion")
    if not research:
        st.info("Esta consulta anterior no incluye la decisión del motor. Actualizá la investigación para ver la selección de instrumentos.")
        _render_legacy_source_diagnostics(saved)
        return

    if research.get("schema_version") != 4 or research.get("scope") != "ARGENTINA_SIN_BROKER":
        st.info("Esta consulta usa un alcance anterior. Actualizá la investigación para obtener la selección del mercado argentino sin broker.")
        _render_sources_and_limits(saved, research)
        return

    portfolio = result.get("cartera_porcentual") or {}
    research_by_category = {item.get("category"): item for item in research.get("categories", [])}
    legacy_by_category = {item.get("categoria"): item for item in saved.get("categorias", [])}
    for category, weight in portfolio.items():
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        category_research = research_by_category.get(category, {})
        selected, malformed = _validated_selected(category_research)
        count_label = "candidato seleccionado" if len(selected) == 1 else "candidatos seleccionados"
        label = (f"{category} · {weight:g}% · {len(selected)} {count_label}"
                 if selected else f"{category} · {weight:g}% · Sin selección: faltan datos o revisión")
        with st.expander(label, expanded=False):
            saved_category = legacy_by_category.get(category, {})
            amount = saved_category.get("monto_asignado")
            if amount is None:
                capital = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0))
                amount = capital * weight / 100
            currency = result.get("moneda", (snapshot.get("perfil") or {}).get("moneda", "ARS"))
            if amount is not None:
                st.caption(f"Monto simulado para esta categoría: {moneda_fmt(amount, currency)} {currency}.")

            if malformed:
                st.warning("La investigación contiene una selección que no coincide con una evaluación elegible. No se muestra esa ficha.")
            if selected:
                for index, candidate in enumerate(selected[:2]):
                    record = candidate.get("record", {})
                    if len(selected) > 1:
                        st.caption("Opción principal" if index == 0 else "Alternativa evaluada; no se suma como una segunda posición")
                    _render_card(record, currency, research, category, index, candidate)
                _render_comparison(category_research)
                category_explanation = category_research.get("selection_explanation") or []
                if category_explanation:
                    st.text(_join_reasons(category_explanation) if isinstance(category_explanation, list) else str(category_explanation))
            else:
                _render_no_selection(category_research)

    _render_sources_and_limits(saved, research)


def _query_and_freeze(result, snapshot, previous):
    saved = query_examples(result, snapshot, refresh=bool(previous))
    if previous:
        saved["revisiones_investigacion"] = _prior_snapshots(previous)
        saved["revision"] = previous.get("revision", 1) + 1
    else:
        saved["revision"] = 1
    result["ejemplos_instrumentos"] = saved
    st.session_state.resultado_robo = result
    _append_history(saved)
    return saved


def _validated_selected(category_research):
    evaluated = category_research.get("evaluated") or []
    selected = category_research.get("selected") or []
    valid = []
    malformed = False
    blocked_category_decisions = {"EXCLUIR_CANDIDATO", "REQUIERE_REVISION", "INFORMACION_INSUFICIENTE", "AMPLIAR_BUSQUEDA"}
    if str(category_research.get("decision", "")).upper() in blocked_category_decisions:
        return [], bool(selected)
    for record in selected:
        canonical_id = record.get("canonical_id") if isinstance(record, dict) else None
        decision = next((item for item in evaluated if item.get("canonical_id") == canonical_id), None)
        if (not canonical_id or not decision or decision.get("eligible") is not True
                or decision.get("decision") != "CONSERVAR_CANDIDATO"
                or decision.get("missing_fields") or decision.get("selection_scope") != "instrument_recommendation"
                or not isinstance(decision.get("record"), dict)):
            malformed = True
            continue
        valid.append(decision)
    return valid, malformed


def _render_card(card, currency, research, category, index, evaluation):
    with st.container(border=True):
        name = card.get("name") or card.get("canonical_id") or "Instrumento sin nombre"
        st.markdown(f"<h3>{escape(_display_name(card))}</h3>", unsafe_allow_html=True)
        explanation = evaluation.get("selection_explanation") or evaluation.get("reasons") or evaluation.get("reason")
        if explanation:
            st.write(_join_reasons(explanation) if isinstance(explanation, list) else str(explanation))
        st.text(f"{_type_label(card.get('instrument_type'))} · {card.get('market') or 'mercado no confirmado'}")
        description = card.get("educational_description") or card.get("description") or _what_is(card)
        st.text(description)

        currency_status = _selected_currency_status(card, currency)
        st.text(f"Moneda de cotización: {currency_status}")
        if not card.get("subscription_currency") or card.get("subscription_currency") == "unknown":
            st.caption("Moneda de suscripción: se confirma con el intermediario.")
        else:
            st.caption(f"Moneda de suscripción informada: {card['subscription_currency']}.")

        missing = evaluation.get("missing_fields", []) or []
        if card.get("minimum") is not None:
            st.text(f"Mínimo publicado antes de comisiones: {moneda_fmt(card['minimum'], card.get('quotation_currency') or currency)} {card.get('quotation_currency') or currency}.")
        if card.get("reference_offer_price") is not None and card.get("snapshot_observed_at"):
            st.text(f"Oferta vendedora referencial observada: {moneda_fmt(card['reference_offer_price'], currency)} {currency}.")
            st.caption(f"Consulta al portal: {fecha_fmt(card['snapshot_observed_at'])}. La fuente anuncia datos con {card.get('snapshot_delay_minutes', 20)} minutos de demora y no informa la fecha del último negocio. El precio final se confirma antes de operar.")
        if card.get("unit_price") is not None and (card.get("price_date") or card.get("quote_date")):
            st.text(f"Precio referencial: {card['unit_price']} {card.get('quotation_currency') or currency} · fecha {card.get('price_date') or card.get('quote_date')}.")
            quote_evidence = _field_evidence(card, "unit_price")
            quote_source = card.get("price_source") or card.get("quote_source") or (quote_evidence or {}).get("source")
            quote_url = _https_url(card.get("price_url") or card.get("quote_url") or (quote_evidence or {}).get("url"))
            if quote_url:
                st.link_button(f"Fuente de cotización: {urlparse(quote_url).netloc}", quote_url)
            elif quote_source:
                st.caption(f"Fuente de cotización: {quote_source}.")
            delay = (card.get("price_delay_minutes") or card.get("quote_delay_minutes")
                     or (quote_evidence or {}).get("delay_minutes"))
            if delay is not None:
                st.caption(f"La fuente informa un retraso de {delay} minutos; el precio no es en tiempo real.")
            else:
                st.caption("Precio referencial publicado; puede no reflejar el valor actual.")
        if card.get("lot_size") is not None and _has_field_evidence(card, "lot_size"):
            st.text(f"Lote publicado: {card['lot_size']}.")
        if card.get("fund_fee_annual_pct") is not None:
            st.text(f"Gastos anuales publicados que se pudieron comparar: {_number_fmt(card['fund_fee_annual_pct'])}% anual.")
        if card.get("settlement_days") is not None:
            st.text(f"Plazo de liquidación publicado: {_number_fmt(card['settlement_days'])} días hábiles.")
        metric = card.get("market_metric")
        if not isinstance(metric, dict) and card.get("volume") is not None:
            metric = {"name": "Volumen informado", "value": card.get("volume"),
                      "unit": card.get("volume_unit"), "date": card.get("volume_date")}
        if isinstance(metric, dict) and metric.get("value") is not None:
            metric_name = metric.get("name") or metric.get("label") or {"patrimonio_clase": "Patrimonio reportado de la clase", "monto_negociado_observado": "Monto negociado observado en el portal"}.get(metric.get("metric"), "Métrica de mercado")
            metric_unit = metric.get("unit") or metric.get("currency") or ""
            metric_date = metric.get("date") or metric.get("period") or metric.get("observed_at")
            metric_value = moneda_fmt(metric["value"], currency) if isinstance(metric["value"], (int, float)) and not isinstance(metric["value"], bool) else str(metric["value"])
            st.text(f"{metric_name}: {metric_value} {metric_unit}".strip() + (f" · referencia {metric_date}." if metric_date else "."))
        derived = card.get("derived_exposure")
        if isinstance(derived, dict):
            exposure_names = {"inflation": "instrumentos con ajuste por inflación", "fx": "instrumentos vinculados al tipo de cambio"}
            st.text("Exposición identificada en la composición: " + ", ".join(f"{_number_fmt(value)}% en {exposure_names.get(key, key)}" for key, value in derived.items()) + ".")
            if card.get("derived_exposure_date"):
                st.caption(f"Composición publicada al {card['derived_exposure_date']}; las tenencias pueden haber cambiado.")
            if card.get("derived_exposure_reasons"):
                st.caption(_join_reasons(card["derived_exposure_reasons"]))
        holdings = card.get("holdings_details") or []
        if holdings and card.get("holdings_date") and _has_field_evidence(card, "holdings_details"):
            st.text("Principales posiciones informadas: " + "; ".join(
                f"{item.get('name')}: {_number_fmt(item.get('weight'))}%" for item in holdings[:4] if isinstance(item, dict)))
            if card.get("holdings_date"):
                st.caption(f"Fecha de composición informada: {card['holdings_date']}; las tenencias pueden haber cambiado.")

        execution_checks = evaluation.get("execution_checks") or {}
        with st.expander("Qué confirmar con tu intermediario", expanded=False):
            st.caption("La selección no confirma que tu intermediario ofrezca el instrumento ni que una orden pueda ejecutarse.")
            broker_missing = execution_checks.get("missing_fields") or []
            if broker_missing:
                st.text("Por confirmar: " + ", ".join(_field_label(field) for field in broker_missing) + ".")
            if execution_checks.get("reasons"):
                st.text(_join_reasons(execution_checks["reasons"]))
            if not broker_missing and not execution_checks.get("reasons"):
                st.text("Confirmá disponibilidad, condiciones y costos con tu intermediario.")
        if evaluation.get("reasons"):
            with st.expander("Reglas y motivos de la selección", expanded=False):
                st.text(_join_reasons(evaluation["reasons"]))
                if missing:
                    st.text("Datos bloqueantes de la recomendación: " + ", ".join(_field_label(field) for field in missing) + ".")
        if card.get("risks"):
            st.text("Riesgos: " + "; ".join(str(x) for x in card["risks"][:3]))

        primary_evidence = _primary_evidence(card.get("evidence", []))
        if primary_evidence:
            url = _https_url(primary_evidence.get("url"))
            observed = primary_evidence.get("observed_at")
            date_text = primary_evidence.get("data_date") or "fecha de contenido no informada"
            if url:
                st.link_button(f"Fuente: {urlparse(url).netloc}", url, width="stretch")
            st.text(f"Observación: {fecha_fmt(observed) if observed else 'fecha no informada'} · {date_text}.")

        key = f"referencia_{research.get('execution_id')}_{category}_{card.get('canonical_id')}_{card.get('knowledge_version', 0)}"
        kind = st.selectbox("Tu señal", ["understood", "known", "correction"],
                            key=key + "_kind",
                            format_func=lambda value: {"understood": "Entendí", "known": "Ya lo conocía", "correction": "Señalar un dato"}[value])
        note = st.text_input("Dato para revisar", key=key + "_note") if kind == "correction" else ""
        if st.button("Guardar señal para futuras revisiones", key=key + "_save"):
            try:
                KnowledgeStore().feedback(card["canonical_id"], kind, note,
                                          execution_id=research.get("execution_id"))
                st.success("Señal guardada. Esta ficha de la evaluación no cambia.")
            except Exception:
                st.warning("No se pudo guardar la señal local.")


def _number_fmt(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def _render_no_selection(category_research):
    evaluated = category_research.get("evaluated") or []
    eligible_count = sum(item.get("eligible") is True for item in evaluated)
    excluded_count = sum(str(item.get("decision", "")).upper() == "EXCLUIR_CANDIDATO" for item in evaluated)
    pending = [item for item in evaluated if item.get("eligible") is not True
               and str(item.get("decision", "")).upper() != "EXCLUIR_CANDIDATO"]
    st.warning("No hay un instrumento seleccionado para esta categoría con la evidencia disponible.")
    st.caption(f"Analizados: {len(evaluated)} · elegibles: {eligible_count} · excluidos: {excluded_count} · pendientes de revisión: {len(pending)}.")
    missing = []
    reasons = []
    for item in evaluated:
        missing.extend(item.get("missing_fields") or [])
        reasons.extend(item.get("reasons") or [])
        if item.get("reason"):
            reasons.append(item["reason"])
    if missing:
        st.text("Datos faltantes: " + ", ".join(_field_label(value) for value in dict.fromkeys(missing)) + ".")
    search = category_research.get("search") or {}
    coverage = search.get("coverage") or category_research.get("coverage") or {}
    if coverage:
        source_count = coverage.get("sources") or coverage.get("source_count")
        markets = coverage.get("markets") or coverage.get("market_count")
        details = []
        if source_count is not None:
            details.append(f"fuentes consultadas: {source_count}")
        if markets is not None:
            details.append(f"mercados cubiertos: {markets}")
        if details:
            st.caption("Cobertura: " + " · ".join(map(str, details)) + ".")
    if reasons:
        with st.expander("Motivos y candidatos revisados", expanded=False):
            for item in evaluated:
                record = item.get("record") or {}
                name = record.get("name") or item.get("canonical_id") or "Candidato"
                st.text(f"{name}: {_join_reasons(item.get('reasons') or ([item['reason']] if item.get('reason') else []))}")
                if item.get("missing_fields"):
                    st.caption("Por confirmar: " + ", ".join(_field_label(value) for value in item["missing_fields"]) + ".")


def _render_comparison(category_research):
    comparison = category_research.get("comparison") or {}
    original = comparison.get("original") or {}
    alternative = comparison.get("alternative") or {}
    if not original and not alternative:
        return
    with st.expander("Comparación y factores de decisión", expanded=False):
        for label, candidate in (("Candidato original", original), ("Candidato seleccionado", alternative)):
            if not candidate:
                continue
            record = candidate.get("record") or {}
            name = record.get("name") or candidate.get("canonical_id") or label
            st.text(f"{label}: {name} · {candidate.get('decision') or 'estado no informado'}.")
            factors = candidate.get("ranking_factors") or {}
            if factors:
                st.text("Factores: " + ", ".join(f"{_factor_label(key)} {value}" for key, value in factors.items()) + ".")
            for evidence in record.get("evidence", [])[:2]:
                if not isinstance(evidence, dict):
                    continue
                st.caption(f"Evidencia: {evidence.get('source') or 'fuente informada'} · "
                           f"{evidence.get('data_date') or evidence.get('observed_at') or 'fecha no informada'}.")
                url = _https_url(evidence.get("url"))
                if url:
                    st.link_button("Consultar evidencia de comparación", url)
        if comparison.get("reason"):
            st.caption(str(comparison["reason"]))


def _factor_label(value):
    return {"riesgo": "riesgo", "operacion": "operación", "diversificacion": "diversificación",
            "costos": "costos", "familiaridad": "familiaridad"}.get(value, value.replace("_", " "))


def _render_sources_and_limits(saved, research):
    with st.expander("Fuentes, actualización y detalle de la investigación", expanded=False):
        st.caption(f"Consulta: {fecha_fmt(saved.get('consultado_en'))} · versión de política {research.get('policy_version')} · universo {research.get('universe_version')}.")
        for coverage in research.get("source_coverage", []):
            if not isinstance(coverage, dict):
                continue
            source_name = coverage.get("source") or "Fuente consultada"
            st.text(f"Cobertura de {source_name}: {coverage.get('candidate_count', 0)} candidatos · "
                    f"clases {', '.join(coverage.get('classes') or []) or 'no informadas'}.")
            url = _https_url(coverage.get("url"))
            if url:
                st.link_button("Consultar fuente de cobertura", url)
            if coverage.get("published_at"):
                st.caption(f"Publicación informada: {coverage['published_at']}.")
        for error in saved.get("errores_fuente", []) + research.get("search", {}).get("errors", []):
            st.text(str(error))
        for source in saved.get("fuentes", []):
            url = _https_url(source.get("url"))
            st.text(str(source.get("fuente") or "Fuente pública"))
            if url:
                st.link_button("Ver publicación del catálogo", url)
        seen = set()
        for category in research.get("categories", []):
            selected, _ = _validated_selected(category)
            for evaluated in selected:
                record = evaluated.get("record") or {}
                for evidence in record.get("evidence", []):
                    url = _https_url(evidence.get("url"))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    st.text(str(evidence.get("source") or record.get("name") or "Fuente del candidato seleccionado"))
                    st.link_button("Ver fuente del candidato", url)
                    st.caption(f"Observada: {fecha_fmt(evidence.get('observed_at')) if evidence.get('observed_at') else 'fecha no informada'} · contenido {evidence.get('data_date') or 'sin fecha'}")
        st.json(research, expanded=False)


def _render_legacy_source_diagnostics(saved):
    if saved.get("errores_fuente"):
        with st.expander("Estado de la consulta anterior"):
            for error in saved["errores_fuente"]:
                st.text(str(error))
    with st.expander("Diagnóstico anterior del catálogo"):
        for category in saved.get("categorias", []):
            diag = category.get("diagnostico") or {}
            st.text(f"{category.get('categoria')}: {diag.get('registros_revisados', 0)} registros revisados; no se muestran como fichas de investigación.")


def _append_history(saved):
    evaluation_id = st.session_state.get("historial_id")
    if evaluation_id:
        try:
            current = {key: value for key, value in saved.items() if key != "revisiones_investigacion"}
            anexar_revision_investigacion(evaluation_id, current)
        except Exception:
            st.warning("No se pudo guardar esta revisión en el historial.")


def _prior_snapshots(previous):
    old = deepcopy({key: value for key, value in previous.items() if key != "revisiones_investigacion"})
    return deepcopy(list(previous.get("revisiones_investigacion", []))) + [old]


def _type_label(value):
    return {"LOCAL_SHARE": "Acción local", "FOREIGN_SHARE": "Acción en el exterior", "ADR": "Certificado ADR",
            "CEDEAR": "Certificado CEDEAR", "ETF": "Canasta cotizada", "FCI": "Fondo común de inversión",
            "CRYPTO": "Criptoactivo", "CRYPTO_FUND": "Fondo cotizado cripto"}.get(value, "Tipo de instrumento por confirmar")


def _display_name(card):
    names = {"ETF:SPY:NYSE_ARCA": "SPY · canasta del S&P 500",
             "FOREIGN_SHARE:MELI:NASDAQ": "MELI · Mercado Libre",
             "CEDEAR:MELI:BYMA": "MELI · CEDEAR de Mercado Libre",
             "LOCAL_SHARE:YPFD:BYMA": "YPFD · YPF en Argentina",
             "ADR:YPF:NYSE": "YPF · ADR de YPF"}
    return names.get(card.get("canonical_id"), f"{card.get('ticker')} · {card.get('name')}" if card.get("ticker") and card.get("ticker") not in str(card.get("name") or "") else card.get("name") or card.get("canonical_id") or "Instrumento sin nombre")


def _primary_evidence(evidence):
    observed = [item for item in evidence if isinstance(item, dict) and item.get("kind") == "observed"]
    if not observed:
        return None
    classification = next((item for item in observed if {"category", "exposure"}.issubset(item.get("fields") or {})), None)
    if classification:
        return classification
    issuer = next((item for item in observed if "issuer" in (item.get("fields") or {})), None)
    return issuer or observed[0]


def _what_is(record):
    explanations = {
        "CEDEAR:SPY:BYMA": "SPY es un fondo que sigue al índice S&P 500, una canasta de grandes empresas de Estados Unidos. Esta ficha corresponde al certificado CEDEAR argentino vinculado a ese fondo. Su valor puede subir o bajar.",
        "ETF:SPY:NYSE_ARCA": "SPY es un fondo cotizado que sigue al índice S&P 500, una canasta de grandes empresas de Estados Unidos. Esta ficha corresponde al ETF del mercado estadounidense. Su valor puede subir o bajar.",
        "LOCAL_SHARE:YPFD:BYMA": "YPFD representa una participación en YPF en el mercado argentino. Sirve para entender una inversión en una empresa concreta: su resultado depende de esa empresa y del mercado, y puede perder valor.",
        "ADR:YPF:NYSE": "Este ADR representa acciones de YPF y cotiza en Estados Unidos. Permite explicar la inversión en una empresa concreta a través de otro vehículo; sus unidades y condiciones difieren de la acción local.",
        "CEDEAR:MELI:BYMA": "Este CEDEAR argentino representa acciones de Mercado Libre. Es una inversión vinculada a una empresa concreta, cuyo precio puede subir o bajar.",
        "FOREIGN_SHARE:MELI:NASDAQ": "MELI es la acción de Mercado Libre en Nasdaq. Representa una participación en una empresa concreta, cuyo precio puede subir o bajar.",
    }
    if record.get("canonical_id") in explanations:
        return explanations[record["canonical_id"]]
    return {"FCI": "Un fondo común reúne aportes y los administra en una cartera; la composición concreta de este fondo debe verificarse.",
            "ETF": "Una canasta de activos cuyas participaciones cotizan en un mercado. Sus unidades y precio son propios.",
            "CEDEAR": "Un certificado argentino que representa un activo del exterior. Tiene unidades y condiciones propias.",
            "ADR": "Un certificado que representa acciones en otro mercado; la relación con la acción original debe verificarse.",
            "LOCAL_SHARE": "Una participación en una empresa negociada en el mercado local.",
            "FOREIGN_SHARE": "Una participación en una empresa negociada en un mercado del exterior.",
            "CRYPTO": "Un activo digital nativo de la red Bitcoin.",
            "CRYPTO_FUND": "Un fondo cotizado con exposición a Bitcoin; es distinto de tener el activo digital directamente."}.get(
                record.get("instrument_type"), "No hay información suficiente para explicar este vehículo.")


def _selected_currency_status(card, currency):
    quotation = card.get("quotation_currency")
    if quotation == currency:
        return "coincide con la simulación"
    if not quotation or quotation == "unknown":
        return "sin confirmar (cotización no informada)"
    return f"no coincide con la moneda simulada ({quotation} / {currency})"


def _has_field_evidence(record, field):
    return _field_evidence(record, field) is not None


def _field_evidence(record, field):
    return next((item for item in record.get("evidence", [])
                 if isinstance(item, dict) and field in (item.get("fields") or {})), None)


def _join_reasons(reasons):
    return " ".join(str(reason) for reason in reasons if reason) or "Faltan datos vigentes o evidencia suficiente."


def _field_label(value):
    labels = {"quotation_currency": "moneda de cotización", "subscription_currency": "moneda de suscripción",
              "economic_currency": "moneda de exposición económica", "minimum": "inversión mínima",
              "lot_size": "lote", "unit_price": "precio unitario", "costs": "costos y comisiones",
              "broker_fee": "comisión del intermediario",
              "settlement_days": "plazo de liquidación", "liquidity": "liquidez", "access": "acceso",
              "holdings": "composición de la cartera", "category_or_exposure": "categoría o exposición",
              "availability": "disponibilidad operativa", "access_authorization": "habilitación del acceso",
              "actual_exposure_or_holdings": "composición y exposición actuales",
              "broker": "intermediario", "broker_fees": "comisiones y gastos del intermediario",
              "cash_subscription_route": "canal y moneda de fondeo", "account_authorization": "habilitación de la cuenta",
              "final_execution_price": "precio final de la orden", "order_quantity": "cantidad operable",
              "broker_settlement_confirmation": "plazos y horarios de acreditación",
              "broker_subscription_currency": "moneda aceptada al suscribir", "broker_redemption_channel": "canal y horarios de rescate",
              "fund_open": "fondo abierto", "subscription_open": "suscripción de la clase habilitada",
              "redemption_open": "rescate de la clase habilitado", "qualified_only": "restricción para inversores calificados",
              "horizon": "horizonte publicado", "duration": "duración publicada de los activos",
              "category": "clasificación", "exposure": "exposición", "holdings_date": "fecha de composición",
              "holdings_details": "composición publicada", "documented_market_unit_rule": "unidad mínima de negociación respaldada",
              "ordinary_share_representation": "representación de una acción ordinaria",
              "valid_two_sided_market_snapshot": "ofertas de compra y venta verificables"}
    if value.endswith("_evidence"):
        return _field_label(value.removesuffix("_evidence")) + " y su evidencia"
    return labels.get(value, value.replace("_", " "))


def _https_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc and parsed.username is None else None
