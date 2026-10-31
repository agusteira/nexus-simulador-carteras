import streamlit as st

from ..history import guardar_evaluacion, normalizar_usuario
from ..service import evaluar
from ..state import has_unsaved_changes, is_result_stale, save_execution, set_step
from ..ui.common import moneda_fmt, objetivo_fmt


def render():
    st.markdown('<div class="eyebrow">REVISIÓN</div>', unsafe_allow_html=True)
    st.title("Revisá los datos de esta simulación")
    st.markdown(
        "Este es el resumen de tus respuestas guardadas. Si algo no te representa, "
        "podés editarlo antes de generar la distribución."
    )

    perfil = st.session_state.get("datos_inversor")
    mercado = st.session_state.get("datos_mercado")
    if not perfil:
        st.warning("Todavía no guardaste un perfil.")
        st.button("Completar perfil", on_click=set_step, args=("perfil",), type="primary")
        return
    if not mercado:
        st.warning("Todavía no guardaste un escenario simulado.")
        st.button("Completar escenario", on_click=set_step, args=("escenario",), type="primary")
        return

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("## Tu perfil")
        st.write(f"**Usuario:** {normalizar_usuario(perfil.get('usuario_id'))}")
        st.write(f"**Capital:** {moneda_fmt(perfil['capital'], perfil['moneda'])}")
        st.write(f"**Objetivo:** {objetivo_fmt(perfil['objetivo'])} · **Horizonte:** {perfil['horizonte']} meses")
        st.write(f"**Baja temporal que querés explorar:** {perfil['tolerancia']}% · No es un límite garantizado de pérdida.")
        st.write(f"**Porción que querés disponible:** {perfil['liquidez']}% · Es una meta simulada, no una promesa de acceso inmediato.")
        st.button("Editar perfil", on_click=set_step, args=("perfil",))

    with right, st.container(border=True):
        st.markdown("## Escenario manual")
        st.write("**Tipo:** Simulado · Ingreso manual")
        alertas = [
            nombre
            for key, nombre in (
                ("inflacion_alta", "Inflación elevada"),
                ("presion_cambiaria", "Presión cambiaria elevada"),
                ("volatilidad_alta", "Volatilidad elevada"),
            )
            if mercado.get(key)
        ]
        st.write(
            "**Alertas seleccionadas:** "
            + (", ".join(alertas) if alertas else "Ninguna; sin alertas en esta simulación")
        )
        st.button("Editar escenario", on_click=set_step, args=("escenario",))
        st.caption(
            "La casilla solo registra que aceptaste que estas señales son supuestos manuales; "
            "no verifica las condiciones actuales del mercado."
        )

    perfil_borrador = st.session_state.get("perfil_borrador") or {}
    escenario_borrador = st.session_state.get("escenario_borrador") or {}
    perfil_sin_guardar = bool(perfil_borrador) and perfil_borrador != perfil
    escenario_sin_guardar = bool(escenario_borrador) and escenario_borrador != mercado
    if has_unsaved_changes():
        st.warning(
            "Hay cambios en borrador que todavía no se guardaron. Volvé al paso "
            "correspondiente y guardalos antes de ejecutar, así la evaluación usa "
            "exactamente los datos que acabás de revisar."
        )
        if perfil_sin_guardar:
            st.button("Volver a guardar el perfil", on_click=set_step, args=("perfil",))
        if escenario_sin_guardar:
            st.button("Volver a guardar el escenario", on_click=set_step, args=("escenario",))
        return

    if is_result_stale():
        st.warning("La última evaluación corresponde a otros datos y está desactualizada.")

    st.divider()
    st.markdown(
        "Todo listo. Vamos a transformar estas respuestas en una distribución "
        "ilustrativa y consultar opciones de inversión publicadas. Los porcentajes describen una simulación, "
        "no equivalen a órdenes ni cambian las señales que ingresaste."
    )
    if st.button("Ejecutar evaluación →", type="primary", width="stretch"):
        resultado, auditoria, errores = evaluar(perfil, mercado)
        save_execution(resultado, auditoria, errores)
        try:
            st.session_state.historial_id = guardar_evaluacion(perfil, mercado, resultado, auditoria, errores)
        except Exception:  # el historial no debe impedir mostrar el resultado
            st.session_state.historial_id = None
        set_step("resultado")
        st.rerun()
