from datetime import datetime

import streamlit as st

from ..state import save_market, set_step


MARKET_FIELDS = {
    "inflacion_alta": ("escenario_inflacion", False),
    "presion_cambiaria": ("escenario_cambio", False),
    "volatilidad_alta": ("escenario_volatilidad", False),
    "mercado_actualizado": ("escenario_confirmado", False),
}


def _sync_draft():
    draft = dict(st.session_state.get("escenario_borrador", {}))
    for field, (key, _) in MARKET_FIELDS.items():
        if key in st.session_state:
            draft[field] = st.session_state[key]
    st.session_state.escenario_borrador = draft
    st.session_state.mercado_intento_guardar = False


def _restore_widgets():
    draft = st.session_state.get("escenario_borrador", {})
    saved = st.session_state.get("datos_mercado", {})
    for field, (key, default) in MARKET_FIELDS.items():
        if key not in st.session_state:
            st.session_state[key] = draft.get(field, saved.get(field, default))


def _discard_market_draft():
    saved = dict(st.session_state.get("datos_mercado") or {})
    st.session_state.escenario_borrador = saved
    st.session_state.mercado_intento_guardar = False
    for field, (key, default) in MARKET_FIELDS.items():
        st.session_state[key] = saved.get(field, default)


def _collect_market():
    return {
        field: st.session_state[key]
        for field, (key, _) in MARKET_FIELDS.items()
    }


def _apply_example(inflacion, cambio, volatilidad):
    for key, value in (("escenario_inflacion", inflacion), ("escenario_cambio", cambio), ("escenario_volatilidad", volatilidad)):
        st.session_state[key] = value
    _sync_draft()


def render():
    _restore_widgets()
    st.markdown('<div class="eyebrow">ESCENARIO</div>', unsafe_allow_html=True)
    st.title("¿Qué contexto querés explorar?")
    st.markdown("No hace falta conocer el mercado. Podés partir de uno de estos ejemplos ficticios y después ajustar las señales.")
    st.caption(
        "Las señales son manuales y simuladas. No verifican ni describen el "
        "mercado actual."
    )

    with st.container(border=True):
        st.markdown("## Elegí un ejemplo para empezar")
        st.caption("Opcional: cada ejemplo cambia las señales de abajo. Ninguno representa el mercado de hoy.")
        examples = st.columns(2)
        for i, (label, values) in enumerate([
            ("Sin alertas", (False, False, False)),
            ("Los precios suben mucho", (True, False, False)),
            ("El dólar está bajo presión", (False, True, False)),
            ("El mercado tiene altibajos", (False, False, True)),
        ]):
            examples[i % 2].button(label, key=f"ejemplo_escenario_{i}", on_click=_apply_example, args=values, width="stretch")
    st.markdown("## Ajustá las señales del ejemplo")
    st.caption("Podés activar más de una. Las reglas priorizan volatilidad, luego inflación y después presión cambiaria.")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.toggle(
            "Inflación elevada",
            key="escenario_inflacion",
            on_change=_sync_draft,
            help="Supone presión inflacionaria para probar cómo responde la regla de asignación.",
        )
        st.caption("Los precios de bienes y servicios suben con fuerza.")
        st.toggle(
            "Presión cambiaria elevada",
            key="escenario_cambio",
            on_change=_sync_draft,
            help="Supone presión sobre el tipo de cambio dentro de esta simulación.",
        )
        st.caption("Hay presión sobre el valor de la moneda frente al dólar.")
    with right, st.container(border=True):
        st.toggle(
            "Volatilidad elevada",
            key="escenario_volatilidad",
            on_change=_sync_draft,
            help="Supone oscilaciones marcadas; la regla prioriza cautela en la asignación ilustrativa.",
        )

        st.caption("Los valores de las inversiones suben y bajan de forma marcada.")

    mercado = _collect_market()
    if any(mercado[key] for key in ("inflacion_alta", "presion_cambiaria", "volatilidad_alta")):
        señales = []
        if mercado["volatilidad_alta"]:
            señales.append("Volatilidad elevada: la simulación prioriza cautela.")
        elif mercado["inflacion_alta"]:
            señales.append("Inflación elevada: la simulación prioriza renta fija asociada a inflación.")
        elif mercado["presion_cambiaria"]:
            señales.append("Presión cambiaria elevada: la simulación prioriza renta fija cambiaria.")
        st.info(" ".join(señales))
    else:
        st.info(
            "Vas a explorar un ejemplo sin alertas activadas. Podés continuar así o elegir otro contexto."
        )

    st.checkbox(
        "Entiendo que este escenario es manual y simulado",
        key="escenario_confirmado",
        on_change=_sync_draft,
    )

    if not mercado["mercado_actualizado"] and st.session_state.mercado_intento_guardar:
        st.error("Marcá la confirmación para guardar y continuar con esta simulación.")

    saved_market = st.session_state.get("datos_mercado")
    if saved_market and mercado != saved_market:
        st.info("Tenés cambios sin guardar. La evaluación anterior sigue usando el escenario guardado.")
        st.button(
            "Descartar cambios del escenario",
            key="escenario_descartar_cambios",
            on_click=_discard_market_draft,
        )
    elif saved_market:
        st.success("Este formulario coincide con el escenario guardado.")
    else:
        st.caption("Borrador sin guardar: el escenario se guardará al continuar.")

    back_col, next_col = st.columns(2)
    with back_col:
        st.button("← Volver al perfil", on_click=set_step, args=("perfil",), width="stretch")
    with next_col:
        if st.button("Guardar escenario y revisar →", type="primary", width="stretch"):
            if not mercado["mercado_actualizado"]:
                st.session_state.mercado_intento_guardar = True
                st.rerun()
            else:
                st.session_state.mercado_intento_guardar = False
                save_market(
                    mercado,
                    {
                        "modo": "simulado_manual",
                        "fuente": "ingreso_manual",
                        "fecha_registro": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                st.session_state.escenario_borrador = dict(mercado)
                set_step("revision")
                st.rerun()
