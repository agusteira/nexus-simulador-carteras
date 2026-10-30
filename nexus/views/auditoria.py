import json

import streamlit as st

from ..state import is_result_stale, set_step
from ..ui.common import (
    escenario_snapshot_fmt,
    fecha_fmt,
    moneda_fmt,
    objetivo_fmt,
    perfil_fmt,
)


def _render_inputs(resultado, snapshot):
    perfil = snapshot.get("perfil") or {}
    escenario = snapshot.get("escenario") or {}
    if not perfil:
        st.info("Los datos de entrada originales no están disponibles en esta sesión.")
        return

    currency = perfil.get("moneda", resultado.get("moneda", "ARS"))
    capital = perfil.get("capital", resultado.get("capital", 0))
    st.write(f"**Capital de entrada:** {moneda_fmt(capital, currency)}")
    st.write(f"**Objetivo:** {objetivo_fmt(perfil.get('objetivo'))}")
    st.write(f"**Horizonte:** {perfil.get('horizonte', 'No disponible')} meses")
    st.write(f"**Tolerancia hipotética:** {perfil.get('tolerancia', 'No disponible')}%")
    st.write(f"**Liquidez mínima simulada:** {perfil.get('liquidez', 'No disponible')}%")
    inferred = resultado.get("perfil_riesgo")
    st.write(f"**Perfil inferido:** {perfil_fmt(inferred) if inferred else 'No inferido'}")
    st.write(
        f"**Escenario:** "
        f"{escenario_snapshot_fmt(escenario, resultado.get('regimen_mercado'))}"
    )
    señales = [
        nombre
        for clave, nombre in (
            ("inflacion_alta", "Inflación elevada"),
            ("presion_cambiaria", "Presión cambiaria elevada"),
            ("volatilidad_alta", "Volatilidad elevada"),
        )
        if escenario.get(clave)
    ]
    st.write("**Señales ingresadas:** " + (", ".join(señales) if señales else "Ninguna"))
    st.caption(
        "El escenario usado por el motor es manual y simulado. "
        + ("La consulta independiente de ejemplos de fondos y su estado quedan registrados en el JSON."
           if resultado.get("ejemplos_instrumentos") else "")
    )
    st.write(f"**Usuario:** {perfil.get('usuario_id') or 'anonimo'}")
    if resultado.get("version_matriz") is not None:
        st.write(f"**Versión de la matriz de decisión:** v{resultado['version_matriz']}")
    st.caption(f"**Fecha de ejecución:** {fecha_fmt(resultado.get('fecha_ejecucion'))}")


def render():
    st.markdown('<div class="eyebrow">AUDITORÍA</div>', unsafe_allow_html=True)
    st.title("Trazabilidad de esta evaluación")
    st.markdown(
        "Acá podés revisar qué perfil y escenario quedaron registrados, junto con "
        "las reglas que se dispararon o los errores de la ejecución."
    )

    resultado = st.session_state.get("resultado_robo")
    if not resultado:
        st.info("Todavía no hay una evaluación para auditar.")
        st.button("Volver al resultado", on_click=set_step, args=("resultado",))
        return

    stale = is_result_stale()
    if stale:
        st.warning(
            "La evaluación auditada está desactualizada. La traza y la descarga "
            "corresponden a la ejecución anterior, no a los datos o borradores actuales."
        )

    st.markdown(f"**Estado registrado:** `{resultado.get('estado', 'SIN_ESTADO')}`")
    _render_inputs(resultado, st.session_state.get("snapshot_ejecucion") or {})

    if resultado.get("auditoria"):
        st.markdown("## Reglas registradas")
        st.dataframe(resultado["auditoria"], width="stretch", hide_index=True)
        st.caption(
            "La traza es parcial: registra la clasificación del perfil y del "
            "escenario; no lista cada ajuste porcentual de la cartera."
        )
    elif resultado.get("errores"):
        st.markdown("## Resultado de la validación")
        st.dataframe(resultado["errores"], width="stretch", hide_index=True)
    else:
        st.info("Esta salida no contiene reglas ni errores registrados.")

    research_snapshot = resultado.get("ejemplos_instrumentos") or {}
    research = research_snapshot.get("investigacion") or {}
    if research:
        st.markdown("## Investigación de instrumentos")
        st.caption(f"Ejecución {research.get('execution_id')} · política {research.get('policy_version')} · universo {research.get('universe_version')} · revisión experta pendiente")
        for category in research.get("categories", []):
            st.write(f"**{category.get('category')} — {category.get('decision')}**")
            st.write(category.get("reasons", []))
            for candidate in category.get("evaluated", []):
                record = candidate.get("record", {})
                st.write({"instrumento": record.get("name") or candidate.get("canonical_id"),
                          "decision": candidate.get("decision"), "rule_ids": candidate.get("rule_ids"),
                          "missing_fields": candidate.get("missing_fields"),
                          "evidence": record.get("evidence", [])})

    with st.expander("Detalle técnico y JSON completo"):
        st.json(resultado)

    st.download_button(
        "Exportar JSON de la ejecución anterior" if stale else "Exportar JSON de esta ejecución",
        data=json.dumps(resultado, ensure_ascii=False, indent=2),
        file_name="auditoria_nexus.json",
        mime="application/json",
    )
    st.button(
        "Volver al resultado",
        key="auditoria_volver_resultado",
        on_click=set_step,
        args=("resultado",),
        type="primary",
    )
