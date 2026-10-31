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
    st.write("Son opciones de inversión del mercado argentino que pasaron los controles de esta simulación.")
    st.caption("La app compara tus respuestas con datos publicados. No predice qué empresa ganará más. Un intermediario o broker es la empresa o banco donde invertís; allí debés confirmar disponibilidad, precios y costos.")
    with st.expander("Palabras útiles para entender estas opciones", expanded=False):
        st.write("Una acción es una pequeña participación en una empresa. Su valor puede subir o bajar.")
        st.write("Un fondo común de inversión (FCI) reúne dinero de muchas personas para invertirlo en distintos activos. Al participar, comprás una parte del fondo, llamada cuotaparte.")
        st.write("Rescatar es pedir que te devuelvan el dinero invertido en un fondo. El plazo se cuenta desde el pedido y depende de días hábiles y horarios.")
        st.write("Que un instrumento pase los controles significa que encaja con las reglas de la simulación. Puede perder valor y no garantiza ganancias.")

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
        st.info("Esta consulta se guardó con una versión anterior. Actualizá la investigación para aplicar las reglas actuales; la consulta anterior queda en el historial.")
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
        count_label = "opción seleccionada" if len(selected) == 1 else "opciones seleccionadas"
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
                st.warning("No mostramos esta opción porque no pudimos confirmar que haya pasado todos los controles. Podés actualizar la investigación para volver a comprobarla.")
            if selected:
                for index, candidate in enumerate(selected[:2]):
                    record = candidate.get("record", {})
                    if len(selected) > 1:
                        st.caption("Opción principal" if index == 0 else "Otra opción para el mismo monto; no se agrega dinero a la distribución")
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
        st.caption(_type_label(card.get('instrument_type')))
        st.write(_what_is(card))
        explanation = evaluation.get("selection_explanation") or evaluation.get("reasons") or evaluation.get("reason")
        if explanation:
            with st.expander("Por qué aparece esta opción", expanded=False):
                for reason in explanation if isinstance(explanation, list) else [explanation]:
                    st.write(str(reason))
        description = card.get("educational_description") or card.get("description")
        if description:
            with st.expander("Descripción publicada y nombre en el mercado", expanded=False):
                st.caption("Texto guardado de la ficha consultada. Puede usar términos técnicos o comerciales; los controles de la app se muestran por separado.")
                st.text(description)
                st.caption(f"Mercado informado: {card.get('market') or 'sin dato'}.")

        currency_status = _selected_currency_status(card, currency)
        st.text(f"Moneda en la que se informa el precio o la clase del fondo: {currency_status}.")
        if not card.get("subscription_currency") or card.get("subscription_currency") == "unknown":
            st.caption("Con qué moneda podés ingresar el dinero: confirmalo con tu intermediario.")
        else:
            st.caption(f"Moneda informada para ingresar dinero: {card['subscription_currency']}.")

        missing = evaluation.get("missing_fields", []) or []
        if card.get("minimum") is not None:
            st.text(f"Monto mínimo publicado para empezar: {moneda_fmt(card['minimum'], card.get('quotation_currency') or currency)} {card.get('quotation_currency') or currency}, antes de comisiones.")
        if card.get("reference_offer_price") is not None and card.get("snapshot_observed_at"):
            st.text(f"Precio de venta que mostraba la fuente: {moneda_fmt(card['reference_offer_price'], currency)} {currency}. Es una referencia, no el precio final de una compra.")
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
            st.text(f"Cantidad mínima de unidades informada para una operación: {card['lot_size']}.")
        if card.get("fund_fee_annual_pct") is not None:
            st.text(f"Gastos anuales publicados del fondo: {_number_fmt(card['fund_fee_annual_pct'])}%. No incluyen todos los posibles costos de operar.")
            if card['fund_fee_annual_pct'] == 0:
                st.caption("La fuente informa cero en esos gastos; eso no asegura que invertir sea gratis.")
        if card.get("settlement_days") is not None:
            days = card['settlement_days']
            if card.get('instrument_type') == 'FCI':
                timing = "el mismo día hábil" if days == 0 else f"en {_number_fmt(days)} día{'s' if days != 1 else ''} hábil{'es' if days != 1 else ''}"
                st.text(f"Al pedir retirar el dinero, el fondo informa que lo entrega {timing}. Depende de los horarios y del canal que uses.")
            else:
                st.text(f"Plazo informado para completar la operación y entregar dinero o títulos: {_number_fmt(days)} días hábiles.")
        metric = card.get("market_metric")
        if not isinstance(metric, dict) and card.get("volume") is not None:
            metric = {"name": "Volumen informado", "value": card.get("volume"),
                      "unit": card.get("volume_unit"), "date": card.get("volume_date")}
        if isinstance(metric, dict) and metric.get("value") is not None:
            metric_name = {"patrimonio_clase": "Dinero total administrado en esta clase del fondo", "monto_negociado_observado": "Monto de operaciones que mostraba el portal"}.get(metric.get("metric")) or metric.get("name") or metric.get("label") or "Dato de actividad del mercado"
            metric_unit = metric.get("unit") or metric.get("currency") or ""
            metric_date = metric.get("date") or metric.get("period") or metric.get("observed_at")
            metric_value = moneda_fmt(metric["value"], currency) if isinstance(metric["value"], (int, float)) and not isinstance(metric["value"], bool) else str(metric["value"])
            st.text(f"{metric_name}: {metric_value} {metric_unit}".strip() + (f" · referencia {metric_date}." if metric_date else "."))
            st.caption("Este dato describe el tamaño o la actividad informados; no mide la seguridad de la inversión.")
        derived = card.get("derived_exposure")
        if isinstance(derived, dict):
            exposure_names = {"inflation": "instrumentos con ajuste por inflación", "fx": "instrumentos vinculados al tipo de cambio"}
            st.text("De las inversiones publicadas del fondo pudimos identificar: " + ", ".join(f"{_number_fmt(value)}% en {exposure_names.get(key, key)}" for key, value in derived.items()) + ".")
            if card.get("derived_exposure_date"):
                st.caption(f"Composición publicada al {card['derived_exposure_date']}; las tenencias pueden haber cambiado.")
            if card.get("derived_exposure_reasons"):
                st.caption(_join_reasons(card["derived_exposure_reasons"]))
        holdings = card.get("holdings_details") or []
        if holdings and card.get("holdings_date") and _has_field_evidence(card, "holdings_details"):
            st.text("En qué invierte, según sus principales inversiones publicadas: " + "; ".join(
                f"{item.get('name')}: {_number_fmt(item.get('weight'))}%" for item in holdings[:4] if isinstance(item, dict)))
            if card.get("holdings_date"):
                st.caption(f"Fecha de composición informada: {card['holdings_date']}; las tenencias pueden haber cambiado.")

        execution_checks = evaluation.get("execution_checks") or {}
        with st.expander("Qué confirmar con tu intermediario", expanded=False):
            st.caption("Antes de invertir, preguntá a tu banco o empresa de inversiones si ofrece esta opción, con qué monto y moneda podés entrar, cuánto cobra y cuándo podés retirar el dinero.")
            broker_missing = execution_checks.get("missing_fields") or []
            if broker_missing:
                st.text("Por confirmar: " + ", ".join(_field_label(field) for field in broker_missing) + ".")
            if execution_checks.get("reasons"):
                st.text(_join_reasons(execution_checks["reasons"]))
            if not broker_missing and not execution_checks.get("reasons"):
                st.text("Confirmá disponibilidad, condiciones y costos con tu intermediario.")
        if evaluation.get("reasons"):
            with st.expander("Controles que se aplicaron", expanded=False):
                st.text(_join_reasons(evaluation["reasons"]))
                if missing:
                    st.text("Datos necesarios que faltan: " + ", ".join(_field_label(field) for field in missing) + ".")
        for warning in evaluation.get("selection_warnings") or []:
            st.caption(str(warning))
        if card.get("risks"):
            st.text("Riesgos: " + "; ".join(str(x) for x in card["risks"][:3]))

        primary_evidence = _primary_evidence(card.get("evidence", []))
        if primary_evidence:
            url = _https_url(primary_evidence.get("url"))
            observed = primary_evidence.get("observed_at")
            date_text = primary_evidence.get("data_date") or "fecha de contenido no informada"
            if url:
                st.link_button(f"Fuente: {urlparse(url).netloc}", url, width="stretch")
            st.text(f"Consultado el {fecha_fmt(observed) if observed else 'día no informado'}. Fecha del dato: {date_text}.")

        key = f"referencia_{research.get('execution_id')}_{category}_{card.get('canonical_id')}_{card.get('knowledge_version', 0)}"
        kind = st.selectbox("¿Te ayudó esta explicación?", ["understood", "known", "correction"],
                            key=key + "_kind",
                            format_func=lambda value: {"understood": "Entendí", "known": "Ya lo conocía", "correction": "Señalar un dato"}[value])
        note = st.text_input("Dato para revisar", key=key + "_note") if kind == "correction" else ""
        if st.button("Guardar mi comentario", key=key + "_save"):
            try:
                KnowledgeStore().feedback(card["canonical_id"], kind, note,
                                          execution_id=research.get("execution_id"))
                st.success("Comentario guardado para futuras revisiones. El resultado de esta simulación se conserva.")
            except Exception:
                st.warning("No pudimos guardar tu comentario. Podés intentarlo de nuevo.")


def _number_fmt(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def _render_no_selection(category_research):
    evaluated = category_research.get("evaluated") or []
    eligible_count = sum(item.get("eligible") is True for item in evaluated)
    excluded_count = sum(str(item.get("decision", "")).upper() in {"EXCLUIR", "EXCLUIR_CANDIDATO"} for item in evaluated)
    pending = [item for item in evaluated if item.get("eligible") is not True
               and str(item.get("decision", "")).upper() not in {"EXCLUIR", "EXCLUIR_CANDIDATO"}]
    st.warning("No pudimos elegir una opción para este grupo con los datos disponibles. La distribución de tu dinero sigue siendo la misma.")
    st.caption(f"Opciones revisadas: {len(evaluated)} · pasaron los controles: {eligible_count} · descartadas: {excluded_count} · falta comprobar: {len(pending)}.")
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
        with st.expander("Qué faltó y qué opciones se revisaron", expanded=False):
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
    with st.expander("Cómo se compararon las opciones", expanded=False):
        for label, candidate in (("Primera opción recibida", original), ("Opción seleccionada", alternative)):
            if not candidate:
                continue
            record = candidate.get("record") or {}
            name = record.get("name") or candidate.get("canonical_id") or label
            st.text(f"{label}: {name}. {_decision_label(candidate.get('decision'))}.")
            factors = candidate.get("ranking_factors") or {}
            if factors:
                for key in ("settlement_days", "published_fund_fees", "observed_spread", "verified_diversification", "risk_fit"):
                    if key in factors:
                        value = factors[key]
                        shown = "sin datos comparables" if value is None else ("sí" if value is True else "no" if value is False else _number_fmt(value))
                        st.text(f"{_factor_label(key)}: {shown}.")
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
            "costos": "costos", "familiaridad": "familiaridad",
            "settlement_days": "Días hábiles informados para recibir dinero o títulos",
            "published_fund_fees": "Gastos anuales publicados del fondo (%)",
            "observed_spread": "Diferencia observada entre precios de compra y venta (%)",
            "verified_diversification": "Reparto de inversiones comprobado",
            "risk_fit": "Medida comparable del riesgo total"}.get(value, value.replace("_", " "))


def _decision_label(value):
    return {"CONSERVAR_CANDIDATO": "Pasó los controles",
            "PROPONER_ALTERNATIVA_COMPATIBLE": "Se eligió otra opción que pasó los controles",
            "EXCLUIR": "No cumple una de las reglas",
            "EXCLUIR_CANDIDATO": "Se descartó según las reglas",
            "INFORMACION_INSUFICIENTE": "Faltan datos para decidir",
            "REQUIERE_REVISION": "Hay datos que necesitan revisión",
            "AMPLIAR_BUSQUEDA": "Se necesitan más opciones o datos"}.get(value, "No se informó una decisión")


def _render_sources_and_limits(saved, research):
    with st.expander("Fuentes, actualización y detalle de la investigación", expanded=False):
        st.caption(f"Consultado el {fecha_fmt(saved.get('consultado_en'))}. Las versiones identifican qué reglas y lista de referencia se usaron: {research.get('policy_version')} / {research.get('universe_version')}.")
        for coverage in research.get("source_coverage", []):
            if not isinstance(coverage, dict):
                continue
            source_name = coverage.get("source") or "Fuente consultada"
            st.text(f"En {source_name} se recibieron {coverage.get('candidate_count', 0)} registros de opciones para revisar. "
                    f"Tipos: {', '.join(_type_label(kind) for kind in coverage.get('classes') or []) or 'no informados'}.")
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
        with st.expander("Datos técnicos completos (JSON)", expanded=False):
            st.caption("Este formato guarda todos los datos de la consulta. No necesitás leerlo para usar la app.")
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
    return {"FCI": "Este fondo reúne dinero de muchas personas y lo invierte según sus reglas. Al participar, tenés una parte del fondo. Su valor puede subir o bajar; abajo podés ver las inversiones que publicó.",
            "ETF": "Es un fondo que se compra y vende en bolsa, como una acción. Reúne una canasta de inversiones cuyo valor puede subir o bajar.",
            "CEDEAR": "Es un certificado que se negocia en Argentina y representa un activo del exterior. Tiene su propio precio y unidad; su valor puede subir o bajar.",
            "ADR": "Es un certificado que representa acciones de una empresa en otro mercado. Sus unidades y precio pueden ser distintos de los de la acción original.",
            "LOCAL_SHARE": "Es una pequeña participación en una empresa que se compra y vende en Argentina. Su valor puede subir o bajar.",
            "FOREIGN_SHARE": "Es una pequeña participación en una empresa que se compra y vende en un mercado del exterior. Su valor puede subir o bajar.",
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
    labels = {"quotation_currency": "moneda en la que se informa el precio", "subscription_currency": "moneda aceptada para ingresar dinero",
              "economic_currency": "moneda de las inversiones que hay detrás", "minimum": "monto mínimo para empezar",
              "lot_size": "cantidad mínima de unidades", "unit_price": "precio por unidad", "costs": "costos y comisiones",
              "broker_fee": "comisión del intermediario",
              "settlement_days": "días para recibir el dinero o los títulos", "liquidity": "condiciones para disponer del dinero", "access": "acceso para operar",
              "holdings": "lista de inversiones del fondo", "category_or_exposure": "tipo de inversión y qué activos tiene",
              "availability": "disponibilidad operativa", "access_authorization": "habilitación del acceso",
              "actual_exposure_or_holdings": "composición y exposición actuales",
              "broker": "intermediario", "broker_fees": "comisiones y gastos del intermediario",
              "cash_subscription_route": "cómo y con qué moneda ingresar dinero", "account_authorization": "habilitación de la cuenta",
              "final_execution_price": "precio final de la orden", "order_quantity": "cantidad operable",
              "broker_settlement_confirmation": "plazos y horarios de acreditación",
              "broker_subscription_currency": "moneda aceptada para ingresar dinero", "broker_redemption_channel": "cómo y a qué hora pedir retirar el dinero",
              "fund_open": "si el fondo está abierto", "subscription_open": "si permite nuevos ingresos de dinero",
              "redemption_open": "si permite pedir retiros", "qualified_only": "si está reservado a inversores con requisitos especiales",
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
