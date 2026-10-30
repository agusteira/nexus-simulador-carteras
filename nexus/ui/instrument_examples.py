"""Read-only public instruments, captured once for the saved evaluation."""

from html import escape
import math

import streamlit as st

from ..instruments import query_examples
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
            st.link_button("Consultar publicación de la fuente", item["url_fuente"], width="stretch")


def render(result, snapshot):
    st.markdown("## Del porcentaje a ejemplos reales")
    st.markdown("Podés consultar fondos publicados por ArgentinaDatos, sin crear una cuenta. Te mostramos qué información coincide con cada categoría y qué falta verificar.")
    saved = result.get("ejemplos_instrumentos")
    automatic = saved is None and not is_result_stale()
    if automatic:
        with st.spinner("Consultando la publicación pública de fondos…"):
            # The result and its original snapshot are passed together even when
            # newer answers exist. No requests happen on incidental reruns.
            saved = query_examples(result, snapshot, refresh=bool(saved))
            result["ejemplos_instrumentos"] = saved
            st.session_state.resultado_robo = result
    label = ("Reintentar consulta de ejemplos" if saved and saved.get("errores_fuente") else "Actualizar ejemplos de esta evaluación") if saved else "Consultar ejemplos de esta evaluación"
    update = st.button(label, key="consultar_ejemplos_instrumentos", width="stretch")
    if update:
        with st.spinner("Consultando la publicación pública de fondos…"):
            saved = query_examples(result, snapshot, refresh=bool(saved))
            result["ejemplos_instrumentos"] = saved
            st.session_state.resultado_robo = result
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
            st.link_button("Ver datos publicados", source["url"], width="stretch")
        st.write(saved["advertencia"])
        st.caption("Estos ejemplos quedan incluidos en el JSON de esta evaluación. Actualizarlos reemplaza sólo esta consulta guardada, sin volver a ejecutar el motor.")
