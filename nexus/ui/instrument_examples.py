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
    st.markdown("## Instrumentos para entender tu cartera")
    st.write("Investigamos referencias educativas para explicar cada categoría. No ejecutamos operaciones ni calculamos cantidades para invertir.")

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
        st.info("Esta consulta guardada usa un formato anterior. No contiene fichas investigadas; actualizala para ver las referencias educativas.")
        _render_legacy_source_diagnostics(saved)
        return

    if not any("educational_selection" in item for item in research.get("categories", [])):
        st.info("Esta investigación guardada es anterior al formato de fichas educativas. Actualizala para consultar referencias explicadas por categoría.")
        _render_sources_and_limits(saved, research)
        return

    portfolio = result.get("cartera_porcentual") or {}
    research_by_category = {item.get("category"): item for item in research.get("categories", [])}
    legacy_by_category = {item.get("categoria"): item for item in saved.get("categorias", [])}
    for category, weight in portfolio.items():
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        category_research = research_by_category.get(category, {})
        selection = category_research.get("educational_selection") or {}
        cards = (selection.get("cards") or [])[:2]
        count_label = "referencia investigada" if len(cards) == 1 else "referencias investigadas"
        label = (f"{category} · {weight:g}% · {len(cards)} {count_label}"
                 if cards else f"{category} · {weight:g}% · Sin una referencia verificada")
        with st.expander(label, expanded=False):
            saved_category = legacy_by_category.get(category, {})
            amount = saved_category.get("monto_asignado")
            if amount is None:
                capital = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0))
                amount = capital * weight / 100
            currency = result.get("moneda", (snapshot.get("perfil") or {}).get("moneda", "ARS"))
            if amount is not None:
                st.caption(f"Monto simulado para esta categoría: {moneda_fmt(amount, currency)} {currency}.")

            if cards:
                selected_ids = {item.get("canonical_id") for item in category_research.get("selected", [])}
                selected_cards = [card for card in cards if card.get("canonical_id") in selected_ids]
                if selected_cards:
                    st.info("Esta referencia coincide con las reglas educativas de la categoría. La operativa real y la idoneidad requieren revisión externa.")
                else:
                    st.info("Estas referencias ayudan a entender la categoría; no son selecciones operativas para tu cartera.")
                original_id = category_research.get("original_id")
                different = next((card for card in cards if original_id and card.get("canonical_id") != original_id), None)
                if different:
                    original = next((item.get("record", {}) for item in category_research.get("evaluated", [])
                                     if item.get("canonical_id") == original_id), {})
                    if original.get("name"):
                        with st.expander("Cómo se eligieron estas referencias", expanded=False):
                            st.text(f"La referencia inicial era {original['name']}; se muestra {different.get('name') or different.get('canonical_id')} como explicación educativa, no como reemplazo de la asignación.")
                for index, card in enumerate(cards):
                    _render_card(card, currency, research, category, index)
            else:
                _render_no_reference(selection)

    _render_bitcoin_library(research)
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


def _render_card(card, currency, research, category, index):
    with st.container(border=True):
        name = card.get("name") or card.get("canonical_id") or "Instrumento sin nombre"
        st.markdown(f"<h3>{escape(_display_name(card))}</h3>", unsafe_allow_html=True)
        st.text(f"{_type_label(card.get('instrument_type'))} · {card.get('market') or 'mercado no confirmado'}")
        description = card.get("educational_description") or _what_is(card)
        st.text(description)

        currency_status = _currency_status(card.get("currency_status"), card)
        operational_status = _operational_status(card.get("operational_status"))
        st.text(f"Moneda: {currency_status} · Operativa: {operational_status}")

        missing = card.get("missing_fields") or []
        if missing or card.get("reason"):
            with st.expander("Qué se verificó y qué falta antes de operar", expanded=False):
                if card.get("reason"):
                    st.text(card["reason"])
                if missing:
                    st.text("Por confirmar: " + ", ".join(_field_label(field) for field in missing) + ".")
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


def _render_no_reference(selection):
    excluded = selection.get("excluded") or []
    familiar = next((item for item in excluded if item.get("familiar") is True), None)
    if familiar:
        name = familiar.get("name") or familiar.get("canonical_id")
        reason = _join_reasons(familiar.get("reasons") or selection.get("reasons") or [])
        st.text(f"Investigamos {name}, pero no podemos presentarlo como referencia verificada para esta categoría. {reason}")
    elif selection.get("reasons"):
        st.text(_join_reasons(selection["reasons"]))
    else:
        st.info("No encontramos una referencia educativa verificada para esta categoría.")
    if selection.get("excluded") and not familiar:
        with st.expander("Por qué no se muestra una referencia"):
            st.write(_join_reasons(selection.get("reasons") or []))


def _render_bitcoin_library(research):
    crypto = [item for item in research.get("educational_universe", [])
              if item.get("instrument_type") in ("CRYPTO", "CRYPTO_FUND")]
    if not crypto:
        return
    with st.expander("Conocer Bitcoin y sus vehículos (sin asignación)", expanded=False):
        st.caption("Bitcoin y un fondo cotizado con exposición a Bitcoin son vehículos distintos. Esta sección no modifica la cartera simulada.")
        for item in crypto:
            st.text(item.get("name") or item.get("canonical_id"))
            st.text(item.get("educational_description") or item.get("description") or _what_is(item))
            st.caption("Identidad/negociación disponible: " + _availability_label(item.get("availability")) + ".")
            for evidence in item.get("evidence", [])[:1]:
                url = _https_url(evidence.get("url"))
                if url:
                    st.link_button("Consultar fuente sobre Bitcoin", url)


def _render_sources_and_limits(saved, research):
    with st.expander("Fuentes, actualización y detalle de la investigación", expanded=False):
        st.caption(f"Consulta: {fecha_fmt(saved.get('consultado_en'))} · versión de política {research.get('policy_version')} · universo {research.get('universe_version')}.")
        for error in saved.get("errores_fuente", []) + research.get("search", {}).get("errors", []):
            st.text(str(error))
        for source in saved.get("fuentes", []):
            url = _https_url(source.get("url"))
            st.text(str(source.get("fuente") or "Fuente pública"))
            if url:
                st.link_button("Ver publicación del catálogo", url)
        seen = set()
        for category in research.get("categories", []):
            selection = category.get("educational_selection") or {}
            for card in selection.get("cards", []):
                for evidence in card.get("evidence", []):
                    url = _https_url(evidence.get("url"))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    st.text(str(evidence.get("source") or card.get("name") or "Referencia del instrumento"))
                    st.link_button("Ver referencia del instrumento", url)
                    st.caption(f"Observada: {fecha_fmt(evidence.get('observed_at')) if evidence.get('observed_at') else 'fecha no informada'} · contenido {evidence.get('data_date') or 'sin fecha'}")
        st.json(research)


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


def _currency_status(value, card):
    if value == "match":
        return "coincide con la simulación"
    if value == "not_applicable":
        return "no corresponde a esta comprobación"
    if value in (None, "", "unknown", "unverified"):
        return f"sin confirmar ({card.get('quotation_currency') or 'cotización no informada'} / {card.get('subscription_currency') or 'suscripción no informada'})"
    return str(value)


def _operational_status(value):
    if value in (None, "", "unknown", "unverified"):
        return "pendiente de confirmar"
    return str(value)


def _availability_label(value):
    return {"identity_confirmed": "identidad observada en la fuente", "source_unavailable": "fuente no disponible",
            "reference_unsupported": "sin fuente para esta referencia",
            "curated_reference_not_checked": "referencia no consultada"}.get(value, "requiere confirmación")


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
