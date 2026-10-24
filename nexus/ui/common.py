from datetime import datetime

import streamlit as st

from ..state import PASOS, set_step, is_result_stale


LABELS_PASO = {
    "inicio": "Inicio",
    "perfil": "Tu perfil",
    "escenario": "Escenario",
    "revision": "Revisar datos",
    "resultado": "Resultado",
}
PERFIL_LABELS = {
    "CONSERVADOR": "Conservador",
    "MODERADO": "Moderado",
    "AGRESIVO": "Agresivo",
}
OBJETIVO_LABELS = {
    "Preservacion": "Preservación",
    "Renta periodica": "Renta periódica",
    "Crecimiento": "Crecimiento",
}
ESCENARIO_LABELS = {
    "ESTABLE": "Sin alertas en esta simulación",
    "INFLACION_ALTA": "Inflación elevada",
    "PRESION_CAMBIARIA": "Presión cambiaria elevada",
    "VOLATILIDAD_ALTA": "Volatilidad elevada",
}


def moneda_fmt(valor, moneda):
    if valor is None:
        return "No disponible"
    amount = f"{valor:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")
    symbol = "$" if moneda == "ARS" else "US$"
    return f"{symbol} {amount}"


def fecha_fmt(value):
    if not value:
        return "No disponible"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def perfil_fmt(value):
    return PERFIL_LABELS.get(value, value or "No disponible")


def objetivo_fmt(value):
    return OBJETIVO_LABELS.get(value, value or "No disponible")


def escenario_fmt(value):
    return ESCENARIO_LABELS.get(value, value or "No disponible")


def escenario_snapshot_fmt(escenario, regimen=None):
    if regimen:
        return escenario_fmt(regimen)
    if escenario.get("volatilidad_alta"):
        return escenario_fmt("VOLATILIDAD_ALTA")
    if escenario.get("inflacion_alta"):
        return escenario_fmt("INFLACION_ALTA")
    if escenario.get("presion_cambiaria"):
        return escenario_fmt("PRESION_CAMBIARIA")
    return escenario_fmt("ESTABLE")


def render_sidebar():
    with st.sidebar:
        st.markdown(
            """
            <div class="brand-lockup">
              <div class="brand-mark" aria-hidden="true">◈</div>
              <div>
                <div class="brand-title">NEXUS</div>
                <div class="brand-subtitle">SIMULADOR DE CARTERAS</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="nav-heading">TU RECORRIDO</div>', unsafe_allow_html=True)
        paso_actual = st.session_state.paso_actual
        for paso in PASOS:
            label = LABELS_PASO[paso]
            completed = ((paso == "perfil" and st.session_state.get("datos_inversor")) or (paso == "escenario" and st.session_state.get("datos_mercado")) or (paso == "revision" and st.session_state.get("resultado_robo") and not is_result_stale()))
            prefix = "✓" if completed else (str(PASOS.index(paso)) if paso != "inicio" else "◈")
            label = f"{prefix}   {label}"
            if paso == paso_actual:
                label += " · actual"
            st.button(
                label,
                key=f"nav_{paso}",
                type="primary" if paso == paso_actual else "secondary",
                width="stretch",
                on_click=set_step,
                args=(paso,),
            )
        st.markdown("---")
        st.markdown('<div class="sidebar-note"><span class="status-dot"></span> Simulación educativa<br><small>Tu avance se conserva en esta sesión.</small></div>', unsafe_allow_html=True)
        with st.expander("Más opciones"):
            st.button(
                "Auditoría de la ejecución",
                key="nav_auditoria",
                width="stretch",
                on_click=set_step,
                args=("auditoria",),
            )
    return paso_actual


def render_step_indicator(paso):
    flow_steps = PASOS[1:]
    if paso == "inicio":
        return
    if paso not in flow_steps:
        return
    index = flow_steps.index(paso)
    completed = {
        "perfil": bool(st.session_state.get("datos_inversor")),
        "escenario": bool(st.session_state.get("datos_mercado")),
        "revision": bool(st.session_state.get("resultado_robo")) and not is_result_stale(),
        "resultado": bool(st.session_state.get("resultado_robo")) and not is_result_stale(),
    }
    items = "".join(f'<span class="flow-step {"active" if i == index else "done" if completed[name] else ""}"><b>{"✓" if completed[name] and i != index else i + 1}</b> {LABELS_PASO[name]}</span>' for i, name in enumerate(flow_steps))
    st.markdown(f'<div class="flow-track" aria-label="Paso {index + 1} de 4">{items}</div>', unsafe_allow_html=True)


def render_header():
    st.markdown(
        '<div class="app-topline"><span>NEXUS <span class="topline-separator">/</span> Tu próxima decisión, más clara</span><span class="demo-badge"><i></i> DEMO EDUCATIVA</span></div>',
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown('<div class="app-footer"><b>NEXUS</b><span>Prototipo académico · Escenario simulado · Datos públicos de fondos.</span></div>', unsafe_allow_html=True)
