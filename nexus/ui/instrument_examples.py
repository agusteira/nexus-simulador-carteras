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
    st.markdown("## Selección de instrumentos")
    st.write("Comparamos candidatos con las reglas de esta simulación. Cada selección conserva sus fuentes y los motivos de la decisión.")

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

    if research.get("schema_version") != 3:
        st.info("Esta consulta anterior mostraba referencias informativas. Actualizá la investigación para obtener la decisión del motor.")
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
                comparison = category_research.get("comparison") or {}
                if comparison.get("reason"):
                    st.info(str(comparison["reason"]))
                for index, candidate in enumerate(selected[:2]):
                    record = candidate.get("record", {})
                    if candidate.get("reason"):
                        st.text(str(candidate["reason"]))
                    elif candidate.get("reasons"):
                        st.text(_join_reasons(candidate["reasons"]))
                    _render_card(record, currency, research, category, index, candidate)
                _render_comparison(category_research)
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
                or decision.get("missing_fields") or not isinstance(decision.get("record"), dict)):
            malformed = True
            continue
        valid.append(decision)
    return valid, malformed


def _render_card(card, currency, research, category, index, evaluation):
    with st.container(border=True):
        name = card.get("name") or card.get("canonical_id") or "Instrumento sin nombre"
        st.markdown(f"<h3>{escape(_display_name(card))}</h3>", unsafe_allow_html=True)
        st.text(f"{_type_label(card.get('instrument_type'))} · {card.get('market') or 'mercado no confirmado'}")
        description = card.get("educational_description") or card.get("description") or _what_is(card)
        st.text(description)

        currency_status = _selected_currency_status(card, currency)
        st.text(f"Moneda: {currency_status} · Operativa: condiciones evaluadas por el motor; disponibilidad por intermediario sin confirmar")

        missing = evaluation.get("missing_fields", []) or []
        if missing or evaluation.get("reason") or evaluation.get("reasons"):
            with st.expander("Qué se verificó y qué falta antes de operar", expanded=False):
                if evaluation.get("reason"):
                    st.text(evaluation["reason"])
                elif evaluation.get("reasons"):
                    st.text(_join_reasons(evaluation["reasons"]))
                if missing:
                    st.text("Por confirmar: " + ", ".join(_field_label(field) for field in missing) + ".")
                if card.get("minimum") is not None:
                    st.text(f"Mínimo publicado: {card['minimum']} {card.get('currency') or currency}.")
                if card.get("settlement_days") is not None:
                    st.text(f"Plazo de liquidación informado: {card['settlement_days']} días.")
                holdings = card.get("holdings_details") or []
                if holdings:
                    st.text("Composición informada (no necesariamente vigente): " + "; ".join(
                        f"{item.get('name')}: {item.get('weight')}%" for item in holdings if isinstance(item, dict)))
                    if card.get("holdings_date"):
                        st.caption(f"Fecha de composición informada: {card['holdings_date']}.")
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


def _render_no_selection(category_research):
    evaluated = category_research.get("evaluated") or []
    eligible_count = sum(item.get("eligible") is True for item in evaluated)
    excluded_count = sum(str(item.get("decision", "")).upper() == "EXCLUIR_CANDIDATO" for item in evaluated)
    pending = [item for item in evaluated if item.get("eligible") is not True
               and str(item.get("decision", "")).upper() != "EXCLUIR_CANDIDATO"]
    st.warning("El motor no seleccionó un instrumento para esta categoría. Esta simulación no emite una recomendación cuando faltan datos o hace falta revisión.")
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
            for candidate in category.get("selected", []):
                evaluated = next((item for item in category.get("evaluated", [])
                                  if item.get("canonical_id") == candidate.get("canonical_id") and item.get("eligible") is True), None)
                if not evaluated:
                    continue
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
    subscription = card.get("subscription_currency")
    if quotation == currency and subscription == currency:
        return "coincide con la simulación"
    if not quotation or not subscription:
        return "sin confirmar (cotización o suscripción no informada)"
    return f"sin confirmar ({quotation} / {subscription})"


def _join_reasons(reasons):
    return " ".join(str(reason) for reason in reasons if reason) or "Faltan datos vigentes o evidencia suficiente."


def _field_label(value):
    labels = {"quotation_currency": "moneda de cotización", "subscription_currency": "moneda de suscripción",
              "economic_currency": "moneda de exposición económica", "minimum": "inversión mínima",
              "lot_size": "lote", "unit_price": "precio unitario", "costs": "costos y comisiones",
              "settlement_days": "plazo de liquidación", "liquidity": "liquidez", "access": "acceso",
              "holdings": "composición de la cartera", "category_or_exposure": "categoría o exposición",
              "availability": "disponibilidad operativa", "access_authorization": "habilitación del acceso",
              "actual_exposure_or_holdings": "composición y exposición actuales"}
    if value.endswith("_evidence"):
        return _field_label(value.removesuffix("_evidence")) + " y su evidencia"
    return labels.get(value, value.replace("_", " "))


def _https_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc and parsed.username is None else None
