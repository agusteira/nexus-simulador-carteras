"""Read-only public instruments, captured once for the saved evaluation."""

from html import escape
import math
from copy import deepcopy
from urllib.parse import urlparse

import streamlit as st

from ..instruments import query_examples
from ..history import anexar_revision_investigacion
from ..instrument_knowledge import KnowledgeStore
from ..state import is_result_stale
from .common import fecha_fmt, moneda_fmt


def _render_example(item, currency):
    with st.container(border=True):
        st.markdown(f"<h4>{escape(item['nombre'])}</h4>", unsafe_allow_html=True)
        st.caption(f"FCI · {item['tipo']} · {item['moneda']}")
        minimum = item.get("inversion_minima_informada")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and math.isfinite(minimum):
            st.markdown(f"**Mínimo informado:** {moneda_fmt(minimum, currency)}")
        st.caption(f"Dato: {item['fecha_dato']} · ArgentinaDatos")
        with st.expander("Por qué aparece y qué revisar", expanded=False):
            st.write(item["criterio"])
            st.caption(f"Identificador de fondo/clase: {item['identificador']}")
            if item.get("administradora"):
                st.caption(f"Administradora: {item['administradora']}")
            if item.get("horizonte_informado"):
                st.caption(f"Horizonte declarado por la fuente: {item['horizonte_informado']} · No certifica compatibilidad con tu plazo.")
            st.write(item["riesgos"])
            value = item.get("valor_cuotaparte_reportado")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                st.write(f"Valor de cuotaparte reportado por la fuente: {value}.")
                st.caption("La unidad publicada no está normalizada. No lo usamos como precio unitario para calcular cuántas cuotapartes comprar.")
            url = _https_url(item.get("url_fuente"))
            if url:
                st.link_button("Consultar publicación de la fuente", url, width="stretch")


def render(result, snapshot):
    st.markdown("## Del porcentaje a ejemplos reales")
    st.markdown("Podés consultar fondos publicados por ArgentinaDatos, sin crear una cuenta. Te mostramos qué información coincide con cada categoría y qué falta verificar.")
    saved = result.get("ejemplos_instrumentos")
    automatic = saved is None and not is_result_stale()
    if automatic:
        with st.spinner("Consultando la publicación pública de fondos…"):
            # The result and its original snapshot are passed together even when
            # newer answers exist. No requests happen on incidental reruns.
            previous = saved
            saved = query_examples(result, snapshot, refresh=bool(saved))
            if previous:
                saved["revisiones_investigacion"] = _prior_snapshots(previous)
                saved["revision"] = previous.get("revision", 1) + 1
            else:
                saved["revision"] = 1
            result["ejemplos_instrumentos"] = saved
            st.session_state.resultado_robo = result
            _append_history(saved)
    label = ("Reintentar consulta de ejemplos" if saved and saved.get("errores_fuente") else "Actualizar ejemplos de esta evaluación") if saved else "Consultar ejemplos de esta evaluación"
    update = st.button(label, key="consultar_ejemplos_instrumentos", width="stretch")
    if update:
        with st.spinner("Consultando la publicación pública de fondos…"):
            previous = saved
            saved = query_examples(result, snapshot, refresh=bool(saved))
            if previous:
                saved["revisiones_investigacion"] = _prior_snapshots(previous)
                saved["revision"] = previous.get("revision", 1) + 1
            else:
                saved["revision"] = 1
            result["ejemplos_instrumentos"] = saved
            st.session_state.resultado_robo = result
            _append_history(saved)
    if saved and saved.get("investigacion"):
        _render_research(saved["investigacion"], known_errors=saved.get("errores_fuente", []))
    if not saved:
        st.caption("La evaluación es anterior a los cambios actuales. Podés consultar ejemplos para sus respuestas originales.")
        return
    st.caption(f"Consulta guardada: {fecha_fmt(saved['consultado_en'])} UTC · Moneda: {saved['moneda']} · Ventana de fecha del dato: {saved['ventana_datos_dias']} días calendario.")
    failed = bool(saved.get("errores_fuente")) and not saved.get("fuentes")
    if failed:
        st.warning("No pudimos cargar el catálogo de fondos. Reintentá la consulta.")
        with st.expander("Detalles del error", expanded=False):
            for error in saved["errores_fuente"]:
                st.write(error)
        return
    if saved.get("errores_fuente"):
        st.warning("La distribución sigue disponible, pero no pudimos verificar ejemplos con la fuente en esta consulta.")
        with st.expander("Qué pasó con la fuente", expanded=False):
            for error in saved["errores_fuente"]:
                st.write(error)
    for category in saved["categorias"]:
        count = len(category["ejemplos"] or category["alternativas"])
        diag = category.get("diagnostico")
        if category["ejemplos"]:
            status = f"{count} ejemplos"
        elif category["alternativas"]:
            status = f"{count} alternativas para investigar"
        elif diag and diag.get("descartados", {}).get("minimo_superior", 0):
            status = "Sin opciones para este monto"
        else:
            status = "Sin fondos compatibles"
        with st.expander(f"{category['categoria']} · {category['peso']}% · {status}", expanded=False):
            assigned = category.get("monto_asignado")
            if assigned is not None:
                st.caption(f"Monto asignado a esta categoría: {moneda_fmt(assigned, saved['moneda'])} {saved['moneda']}.")
            if category["ejemplos"]:
                st.markdown("### Coinciden en categoría y moneda")
                st.caption("Coincidencia de clasificación; la idoneidad completa para tu perfil requiere revisión.")
                columns = st.columns(2)
                for index, item in enumerate(category["ejemplos"]):
                    with columns[index % 2]:
                        _render_example(item, saved["moneda"])
            else:
                if category["alternativas"]:
                    st.markdown(f"### {len(category['alternativas'])} alternativas para investigar")
                    st.caption("No verificamos compatibilidad con esta categoría. No reemplazan automáticamente la asignación.")
                    st.write(category["limitacion"])
                    columns = st.columns(2)
                    for index, item in enumerate(category["alternativas"]):
                        with columns[index % 2]:
                            _render_example(item, saved["moneda"])
                else:
                    if not diag:
                        st.info("Esta consulta guardada no incluye motivos de descarte. Podés actualizarla para verlos.")
                    elif not diag["registros_revisados"]:
                        st.info("La fuente no publicó fondos en esta consulta. Podés actualizarla más tarde.")
                    else:
                        d = diag["descartados"]
                        parts = []
                        if d.get("fecha"):
                            parts.append(f"{d['fecha']} registros con fecha no vigente")
                        if d.get("moneda"):
                            parts.append(f"{d['moneda']} registros con moneda distinta o sin confirmar")
                        if d.get("minimo_invalido"):
                            parts.append(f"{d['minimo_invalido']} registros con mínimo inválido")
                        if d.get("minimo_superior"):
                            parts.append(f"{d['minimo_superior']} registros con mínimo superior al monto de esta categoría")
                        if d.get("metadatos"):
                            parts.append(f"{d['metadatos']} registros con metadatos incompletos")
                        if parts:
                            prefix = "Sin opciones para este monto." if d.get("minimo_superior") else "Sin fondos compatibles."
                            st.info(prefix + " " + "; ".join(parts) + ". Podés actualizar los datos de la fuente. Para cambiar moneda o capital, editá el perfil y ejecutá otra evaluación.")
                        elif d.get("categoria") == diag["registros_revisados"]:
                            st.info("El catálogo no incluye fondos de esta clase. Podés actualizar la consulta más adelante.")
                        else:
                            st.info("Sin fondos compatibles con la categoría y los criterios de la consulta.")
                    st.write(category["limitacion"])
            if category["registros_sin_fecha_vigente"]:
                st.caption("Se excluyeron registros con fecha ausente, inválida, futura o fuera de la ventana de 7 días.")
    with st.expander("Fuente, actualización y criterio de selección", expanded=False):
        st.write(saved["criterio_orden"])
        st.write("Se exige moneda de denominación y de inversión igual a la simulación. Se excluyen mínimos informados superiores al monto asignado a la categoría. La consulta no certifica comisiones, disponibilidad, aptitud ni rescate inmediato.")
        for source in saved["fuentes"]:
            st.caption(f"{source['fuente']} · Publicación: {fecha_fmt(source.get('fecha_publicacion'))} UTC · Obtenida: {fecha_fmt(source['consultado_en'])} UTC · {'Caché de hasta 15 minutos' if source.get('cache') else 'Consulta de red'}")
            url = _https_url(source.get("url"))
            if url:
                st.link_button("Ver datos publicados", url, width="stretch")
        st.write(saved["advertencia"])
        st.caption("Estos ejemplos quedan incluidos en el JSON de esta evaluación. Actualizarlos reemplaza sólo esta consulta guardada, sin volver a ejecutar el motor.")


def _append_history(saved):
    evaluation_id = st.session_state.get("historial_id")
    if evaluation_id:
        try:
            current = {key: value for key, value in saved.items() if key != "revisiones_investigacion"}
            anexar_revision_investigacion(evaluation_id, current)
        except Exception as exc:
            st.warning(f"No se pudo guardar esta revisión en el historial: {exc}")


def _prior_snapshots(previous):
    old = deepcopy({key: value for key, value in previous.items() if key != "revisiones_investigacion"})
    return deepcopy(list(previous.get("revisiones_investigacion", []))) + [old]


def _render_research(research, known_errors=()):
    st.markdown("## Revisión educativa de instrumentos")
    st.caption(f"Política {research.get('policy_version')} · Universo {research.get('universe_version')} · Revisión experta pendiente")
    search = research.get("search", {})
    st.caption(f"Búsquedas de referencia: {search.get('queries', 0)} de {search.get('limits', {}).get('max_queries', 0)} · {search.get('elapsed_seconds', 0):.1f} s")
    for error in search.get("errors", []):
        if error not in known_errors:
            st.warning(str(error))
    store = None
    for category in research.get("categories", []):
        name = category.get("category") or "Categoría"
        status = category.get("decision", "INFORMACION_INSUFICIENTE")
        status_label = {"CONSERVAR_CANDIDATO": "Se conserva", "PROPONER_ALTERNATIVA_COMPATIBLE": "Alternativa compatible",
                        "AMPLIAR_BUSQUEDA": "Ampliar búsqueda", "REQUIERE_REVISION": "Requiere revisión",
                        "INFORMACION_INSUFICIENTE": "Faltan datos"}.get(status, "En revisión")
        with st.expander(f"Investigación · {name} · {status_label}", expanded=False):
            for reason in category.get("reasons", []):
                st.text(reason)
            comparison = category.get("comparison", {})
            if comparison.get("reason") and comparison["reason"] not in category.get("reasons", []):
                st.text(comparison["reason"])
            for key, label in (("original", "Candidato inicial"), ("alternative", "Alternativa evaluada")):
                compared = comparison.get(key)
                if compared:
                    st.text(f"{label}: {compared.get('name') or compared.get('canonical_id')} · {_decision_label(compared.get('decision'))}")
            evaluated = category.get("evaluated", [])
            selected_ids = {r.get("canonical_id") for r in category.get("selected", [])}
            highlighted = [item for item in evaluated if item.get("canonical_id") in selected_ids
                           or item.get("canonical_id") == category.get("original_id")]
            highlighted += [item for item in evaluated if item not in highlighted]
            if len(evaluated) > 2:
                st.caption(f"Mostramos dos fichas de {len(evaluated)} candidatos evaluados. La auditoría y el JSON incluyen el detalle completo.")
            for item in highlighted[:2]:
                record = item.get("record", {})
                st.text(record.get("name") or record.get("canonical_id") or "Instrumento sin nombre")
                type_label = {"LOCAL_SHARE": "empresa argentina", "FOREIGN_SHARE": "empresa extranjera", "ADR": "certificado ADR", "CEDEAR": "certificado CEDEAR", "ETF": "canasta cotizada", "FCI": "fondo"}.get(record.get("instrument_type"), record.get("instrument_type") or "tipo no verificado")
                st.write(f"{type_label} · {record.get('category') or name} · {_decision_label(item.get('decision'))}")
                if record.get("ticker") or record.get("market"):
                    st.caption(f"Identificación: {record.get('ticker') or 'sin ticker'} · mercado {record.get('market') or 'no confirmado'}")
                st.text(record.get("description") or (record.get("explanation") or {}).get("text") or _what_is(record))
                for reason in item.get("reasons", []):
                    st.write(reason)
                st.write("Riesgos: " + ("; ".join(record.get("risks") or []) or "Puede perder valor. La composición y los riesgos particulares todavía no están verificados."))
                missing = item.get("missing_fields", [])
                st.write("Datos faltantes: " + (", ".join(_field_label(x) for x in missing) if missing else "Ninguno según las reglas educativas"))
                for evidence in record.get("evidence", [])[:2]:
                    url = _https_url(evidence.get("url"))
                    if url:
                        st.link_button(f"Fuente: {urlparse(url).netloc}", url, width="stretch")
                    st.caption(f"Observado: {evidence.get('observed_at') or 'No disponible'} · Dato: {evidence.get('data_date') or 'sin fecha'} · versión {evidence.get('version') or '—'}")
                if record.get("market_metric") is None:
                    st.caption("Métrica de mercado: no medida.")
                key = f"investigacion_{research.get('execution_id')}_{name}_{record.get('canonical_id')}_{record.get('knowledge_version', 0)}"
                kind = st.selectbox("Tu señal", ["understood", "known", "correction"], key=key + "_kind", format_func=lambda x: {"understood": "Entendí", "known": "Ya lo conocía", "correction": "Señalar un dato"}[x])
                note = st.text_input("Nota opcional", key=key + "_note") if kind == "correction" else ""
                if st.button("Guardar señal", key=key + "_save"):
                    try:
                        store = store or KnowledgeStore()
                        store.feedback(record["canonical_id"], kind, note, execution_id=research.get("execution_id"))
                        st.success("Señal guardada para futuras revisiones.")
                    except Exception as exc:
                        st.warning(f"No se pudo guardar la señal: {exc}")
    with st.expander("Universo educativo disponible (no son asignaciones)"):
        st.caption("Estas referencias ayudan a distinguir vehículos. Su disponibilidad para operar, costos y condiciones siguen sin verificar. Bitcoin y sus vehículos no reciben asignación.")
        for record in research.get("educational_universe", []):
            availability = {"identity_confirmed": "identidad observada en la fuente", "source_unavailable": "fuente sin verificar",
                            "reference_unsupported": "sin proveedor habilitado", "curated_reference_not_checked": "referencia aún no consultada"}.get(record.get("availability"), "requiere revisión")
            label = {"LOCAL_SHARE": "acción local", "FOREIGN_SHARE": "acción extranjera", "ADR": "ADR", "CEDEAR": "CEDEAR", "ETF": "ETF", "FCI": "fondo", "CRYPTO": "criptoactivo", "CRYPTO_FUND": "fondo cripto"}.get(record.get("instrument_type"), "instrumento")
            st.text(f"{record.get('name') or record.get('canonical_id')} · {label} · {availability}")
            st.text(record.get("description") or "Descripción no disponible.")
            st.caption(f"Símbolo: {record.get('ticker') or 'no informado'} · Mercado: {record.get('market') or 'no informado'} · Presencia o negociación: no medida.")
            for evidence in record.get("evidence", []):
                url = _https_url(evidence.get("url"))
                if url:
                    st.link_button("Ver referencia de " + str(record.get("name") or record.get("canonical_id")), url)
                if evidence.get("kind") == "observed":
                    st.caption(f"Consultada: {evidence.get('observed_at')} · Fecha del contenido: {evidence.get('data_date') or 'no informada'}")


def _what_is(record):
    return {
        "FCI": "Un fondo común reúne aportes de distintas personas y los administra en una cartera. La clasificación publicada describe una clase amplia; su composición concreta todavía no está verificada.",
        "ETF": "Es una canasta de activos cuyas participaciones cotizan en bolsa. Sus unidades y precio corresponden a este mercado.",
        "CEDEAR": "Es un certificado argentino que representa un activo del exterior. Tiene unidades y condiciones propias; su precio no se puede intercambiar con el del activo representado.",
        "ADR": "Es un certificado que representa acciones en otro mercado. Hay que verificar su relación con la acción original.",
        "LOCAL_SHARE": "Es una participación en una empresa, negociada en el mercado local.",
        "FOREIGN_SHARE": "Es una participación en una empresa, negociada en un mercado del exterior.",
    }.get(record.get("instrument_type"), "No hay información suficiente para explicar este vehículo.")


def _field_label(value):
    labels = {"quotation_currency": "moneda de cotización", "subscription_currency": "moneda de suscripción",
              "economic_currency": "moneda de exposición económica", "minimum": "inversión mínima",
              "lot_size": "lote", "unit_price": "precio unitario", "costs": "costos",
              "settlement_days": "plazo de liquidación", "liquidity": "liquidez", "access": "acceso",
              "holdings": "composición", "category_or_exposure": "categoría o exposición", "availability": "disponibilidad",
              "access_authorization": "condiciones de acceso del usuario", "canonical_id": "identidad del instrumento",
              "instrument_type": "tipo de instrumento", "market": "mercado", "ticker": "símbolo",
              "validation_status_freshness": "vigencia de la ficha", "unit_price_freshness": "vigencia del precio",
              "context.category": "categoría de la simulación", "context.profile": "perfil original",
              "context.horizon_months": "horizonte original", "context.objective": "objetivo original",
              "context.budget": "presupuesto original", "context.currency": "moneda original",
              "context.tolerance": "tolerancia original", "context.liquidity_required": "liquidez solicitada"}
    if value.endswith("_evidence"):
        return _field_label(value.removesuffix("_evidence")) + " (evidencia)"
    return labels.get(value, value.replace("_", " "))


def _decision_label(value):
    return {"CONSERVAR_CANDIDATO": "Se conserva", "PROPONER_ALTERNATIVA_COMPATIBLE": "Alternativa compatible",
            "EXCLUIR_CANDIDATO": "Se excluye", "REQUIERE_REVISION": "Requiere revisión",
            "INFORMACION_INSUFICIENTE": "Faltan datos"}.get(value, "En revisión")


def _https_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc and parsed.username is None else None
