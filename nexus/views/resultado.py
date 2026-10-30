import json
from html import escape

import streamlit as st

from ..state import is_result_stale, set_step
from ..ui.instrument_examples import render as render_instrument_examples
from ..ui.common import (
    fecha_fmt,
    moneda_fmt,
    objetivo_fmt,
    perfil_fmt,
    escenario_snapshot_fmt,
)


def _snapshot():
    return st.session_state.get("snapshot_ejecucion") or {}


def _render_actions():
    st.markdown("## ¿Qué querés hacer ahora?")
    left, right = st.columns(2)
    with left:
        st.button(
            "Editar perfil",
            key="resultado_editar_perfil",
            on_click=set_step,
            args=("perfil",),
            width="stretch",
        )
        st.button(
            "Ver auditoría",
            key="resultado_ver_auditoria",
            on_click=set_step,
            args=("auditoria",),
            width="stretch",
        )
    with right:
        st.button(
            "Simular otro escenario",
            key="resultado_editar_escenario",
            on_click=set_step,
            args=("escenario",),
            width="stretch",
            type="primary",
        )
        st.button(
            "Volver a revisar datos",
            key="resultado_volver_revision",
            on_click=set_step,
            args=("revision",),
            width="stretch",
        )


def _render_snapshot_summary(resultado, snapshot):
    perfil = snapshot.get("perfil") or {}
    escenario = snapshot.get("escenario") or {}

    inferred = resultado.get("perfil_riesgo")
    profile_label = perfil_fmt(inferred) if inferred else "Perfil no inferido"
    scenario_label = escenario_snapshot_fmt(escenario, resultado.get("regimen_mercado")) if perfil else "Datos originales no disponibles"
    capital = resultado.get("capital", perfil.get("capital"))
    currency = resultado.get("moneda", perfil.get("moneda", "ARS"))
    fields = [
        ("Capital simulado", moneda_fmt(capital, currency)),
        ("Perfil", profile_label),
        ("Escenario", scenario_label),
        ("Fecha de ejecución", fecha_fmt(resultado.get("fecha_ejecucion"))),
    ]
    cells = "".join(f'<div class="result-summary-cell"><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>' for label, value in fields)
    st.markdown(f'<dl class="result-summary" aria-label="Resumen de esta evaluación">{cells}</dl>', unsafe_allow_html=True)

    with st.expander("Ver respuestas originales de esta ejecución"):
        if perfil:
            st.write(f"**Objetivo:** {objetivo_fmt(perfil.get('objetivo'))}")
            st.write(f"**Horizonte:** {perfil.get('horizonte', 'No disponible')} meses")
            st.write(f"**Tolerancia hipotética:** {perfil.get('tolerancia', 'No disponible')}%")
            st.write(f"**Liquidez mínima simulada:** {perfil.get('liquidez', 'No disponible')}%")
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
            st.caption("Escenario manual simulado; no describe datos actuales del mercado.")
        else:
            st.info("Los datos originales de esta sesión no están disponibles.")


def _render_success(resultado):
    st.success("La simulación generó una distribución ilustrativa.")
    cartera = resultado.get("cartera_porcentual", {})
    moneda = resultado.get("moneda", "ARS")
    montos = resultado.get("montos_estimados", {})
    st.markdown("## Distribución del monto simulado")
    with st.container(key="allocation-table"):
        rows = "".join(
            "<tr>"
            f"<th scope='row'>{escape(categoria)}</th>"
            f"<td>{porcentaje}%</td>"
            f"<td>{moneda_fmt(montos.get(categoria, resultado.get('capital', 0) * porcentaje / 100), moneda)}</td>"
            "</tr>"
            for categoria, porcentaje in cartera.items()
        )
        st.markdown(
            "<table class='allocation-table'>"
            "<caption>Porcentajes y montos estimados por categoría</caption>"
            "<thead><tr><th scope='col'>Categoría</th>"
            "<th scope='col' aria-label='Asignación porcentual'>%</th>"
            "<th scope='col'>Monto</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>",
            unsafe_allow_html=True,
        )
    palette = ["#a78bfa", "#56c8d8", "#6ee7b7", "#e9bd7b", "#8ba6ef", "#e8a3c9"]
    bars = "".join(
        f'<div class="allocation-bar"><div class="bar-label"><span>{escape(category)}</span><b>{percent}%</b></div><div class="bar-track"><div style="width:{percent}%;background:{palette[i % len(palette)]}"></div></div></div>'
        for i, (category, percent) in enumerate(cartera.items()) if percent > 0
    )
    st.markdown(f'<div class="allocation-chart" role="img" aria-label="Distribución ilustrativa; porcentajes detallados en la tabla anterior">{bars}</div>', unsafe_allow_html=True)
    st.caption(resultado.get("advertencia", "Distribución ilustrativa."))


def _render_interpretation(resultado):
    reglas = resultado.get("auditoria", [])
    st.markdown("## Cómo se interpretaron tus respuestas")
    if reglas:
        for regla in reglas[:2]:
            st.markdown(f"- {regla['motivo']}")
    else:
        st.info("Esta evaluación no incluye una traza de auditoría disponible.")
    with st.expander("Detalle técnico de reglas y JSON"):
        if reglas:
            st.dataframe(reglas, width="stretch", hide_index=True)
        st.caption(
            "La traza es parcial: registra clasificación de perfil y escenario, "
            "pero no detalla cada ajuste porcentual de la cartera."
        )
        st.json(resultado)


def _render_manual_result(resultado):
    st.error("No pudimos generar una distribución con estas respuestas.")
    st.write(
        "El prototipo no pudo producir una asignación para esta combinación. "
        "Podés revisar los datos o conservarlos y consultar el detalle técnico."
    )
    for error in resultado.get("errores", []):
        st.write(f"**Detalle:** {error.get('mensaje', 'La evaluación requiere revisión.')}")
    st.caption("Esta demo no envía consultas a un asesor.")

    codes = {error.get("codigo") for error in resultado.get("errores", [])}
    if "ERR_DATOS_MERCADO_NO_DISPONIBLES" in codes:
        st.button(
            "Revisar el escenario simulado",
            key="manual_editar_escenario",
            on_click=set_step,
            args=("escenario",),
        )
    elif codes.intersection({"ERR_CAPITAL_INVALIDO", "ERR_HORIZONTE_INVALIDO", "ERR_TOLERANCIA_INVALIDA", "ERR_LIQUIDEZ_INVALIDA", "ERR_INCONSISTENCIA_PERFIL_HORIZONTE"}):
        st.button(
            "Revisar el perfil",
            key="manual_editar_perfil",
            on_click=set_step,
            args=("perfil",),
        )
    elif codes.intersection({"ERR_INFERENCIA_INCOMPLETA", "ERR_ASIGNACION_INVIABLE"}):
        st.button(
            "Revisar las respuestas",
            key="manual_revisar_respuestas",
            on_click=set_step,
            args=("revision",),
        )

    with st.expander("Detalle técnico"):
        st.dataframe(resultado.get("errores", []), width="stretch", hide_index=True)


def render():
    st.markdown('<div class="eyebrow">RESULTADO</div>', unsafe_allow_html=True)
    st.title("Resultado de la simulación")
    resultado = st.session_state.get("resultado_robo")
    if not resultado:
        st.info("Todavía no hay una evaluación. Revisá los datos para ejecutar el motor.")
        perfil = st.session_state.get("datos_inversor")
        mercado = st.session_state.get("datos_mercado")
        if not perfil:
            st.button("Completar perfil", on_click=set_step, args=("perfil",), type="primary")
        elif not mercado:
            st.button("Completar escenario", on_click=set_step, args=("escenario",), type="primary")
        else:
            st.button("Revisar respuestas", on_click=set_step, args=("revision",), type="primary")
        return

    stale = is_result_stale()
    if stale:
        st.warning(
            "Esta evaluación está desactualizada porque hay datos guardados o "
            "borradores diferentes. Lo que sigue y el archivo descargable "
            "corresponden a la evaluación anterior."
        )
        st.button(
            "Volver al perfil para guardar cambios",
            key="resultado_guardar_perfil",
            on_click=set_step,
            args=("perfil",),
        )
        st.button(
            "Volver al escenario para guardar cambios",
            key="resultado_guardar_escenario",
            on_click=set_step,
            args=("escenario",),
        )
        st.markdown("## Evaluación anterior")

    if resultado.get("estado") == "RECOMENDACION_EXITOSA":
        distribution_tab, examples_tab, interpretation_tab = st.tabs(
            [
                "Resultado de la simulación",
                "Del porcentaje a ejemplos reales",
                "Cómo se interpretaron tus respuestas",
            ],
            key="resultado_secciones",
            default="Resultado de la simulación",
        )
        with distribution_tab:
            _render_snapshot_summary(resultado, _snapshot())
            _render_success(resultado)
        with examples_tab:
            render_instrument_examples(resultado, _snapshot())
        with interpretation_tab:
            _render_interpretation(resultado)
    else:
        _render_snapshot_summary(resultado, _snapshot())
        _render_manual_result(resultado)

    st.download_button(
        "Descargar JSON de la evaluación anterior" if stale else "Descargar JSON de esta evaluación",
        data=json.dumps(resultado, ensure_ascii=False, indent=2),
        file_name="resultado_nexus.json",
        mime="application/json",
        width="stretch",
        help=(
            "Descarga los datos exactos de esta evaluación guardada."
            if not stale
            else "Descarga la evaluación anterior, no los borradores actuales."
        ),
    )
    if resultado.get("estado") != "RECOMENDACION_EXITOSA":
        with st.expander("Ver respuesta JSON completa"):
            st.json(resultado)
    _render_actions()
