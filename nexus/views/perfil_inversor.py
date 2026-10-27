import streamlit as st

from ..state import save_profile, set_step
from ..ui.common import moneda_fmt, objetivo_fmt
from ..ui.money_input import money_input


PROFILE_FIELDS = {
    "usuario_id": ("perfil_usuario", ""),
    "capital": ("perfil_capital", None),
    "moneda": ("perfil_moneda", "ARS"),
    "horizonte": ("perfil_horizonte", 24),
    "objetivo": ("perfil_objetivo", "Preservacion"),
    "tolerancia": ("perfil_tolerancia", 10),
    "liquidez": ("perfil_liquidez", 20),
}


def _sync_draft():
    draft = dict(st.session_state.get("perfil_borrador", {}))
    for field, (key, _) in PROFILE_FIELDS.items():
        if key in st.session_state:
            draft[field] = st.session_state[key]
    st.session_state.perfil_borrador = draft
    st.session_state.errores_perfil = {}


def _restore_widgets():
    draft = st.session_state.get("perfil_borrador", {})
    saved = st.session_state.get("datos_inversor", {})
    for field, (key, default) in PROFILE_FIELDS.items():
        if key not in st.session_state:
            st.session_state[key] = draft.get(field, saved.get(field, default))


def _discard_profile_draft():
    saved = dict(st.session_state.get("datos_inversor") or {})
    st.session_state.perfil_borrador = saved
    st.session_state.errores_perfil = {}
    for field, (key, default) in PROFILE_FIELDS.items():
        st.session_state[key] = saved.get(field, default)


def _collect_profile():
    return {
        field: st.session_state[key]
        for field, (key, _) in PROFILE_FIELDS.items()
    }


def _validate_profile(data):
    errors = {}
    if data["capital"] is None or data["capital"] <= 0:
        errors["capital"] = "Ingresá un capital mayor que cero."
    if data["horizonte"] is None or data["horizonte"] <= 0:
        errors["horizonte"] = "Ingresá un horizonte mayor que cero meses."
    if not 0 <= data["tolerancia"] <= 100:
        errors["tolerancia"] = "La tolerancia debe estar entre 0 y 100%."
    if not 0 <= data["liquidez"] <= 100:
        errors["liquidez"] = "La liquidez debe estar entre 0 y 100%."
    return errors


def render():
    _restore_widgets()
    errors = st.session_state.get("errores_perfil", {})

    st.markdown('<div class="eyebrow">TU PERFIL</div>', unsafe_allow_html=True)
    st.title("¿Qué necesitás de tu inversión?")
    st.markdown(
        "Empecemos por lo que importa: cuánto querés simular y qué esperás de ese dinero. "
        "Completamos algunas respuestas de ejemplo; podés cambiarlas."
    )
    if errors:
        st.error("Revisá estos datos antes de continuar.")
        anchors = {
            "capital": "capital-y-horizonte",
            "horizonte": "capital-y-horizonte",
            "tolerancia": "objetivo-y-riesgo",
            "liquidez": "objetivo-y-riesgo",
        }
        for field, message in errors.items():
            st.markdown(f"- [{message}](#{anchors[field]})")

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("## Tu punto de partida")
        st.text_input(
            "Identificador de usuario (opcional)",
            key="perfil_usuario",
            max_chars=64,
            on_change=_sync_draft,
            placeholder="Ej.: DNI, legajo o alias",
            help="Se guarda junto con cada evaluación para consultarla después en el Historial.",
        )
        capital = money_input(
            "¿Con cuánto querés simular?",
            key="perfil_capital",
            on_change=_sync_draft,
        )
        if "capital" in errors:
            st.error(errors["capital"])
        moneda = st.selectbox(
            "Moneda base",
            ["ARS", "USD"],
            format_func=lambda value: "Pesos argentinos (ARS)" if value == "ARS" else "Dólares estadounidenses (USD)",
            key="perfil_moneda",
            on_change=_sync_draft,
        )
        horizonte = st.number_input(
            "¿Por cuántos meses?",
            min_value=0,
            step=1,
            key="perfil_horizonte",
            on_change=_sync_draft,
            help="Período orientativo para el ejercicio, expresado en meses.",
        )
        if "horizonte" in errors:
            st.error(errors["horizonte"])
    with right, st.container(border=True):
        st.markdown("## Lo que necesitás")
        objetivo = st.selectbox(
            "¿Qué querés lograr?",
            ["Preservacion", "Renta periodica", "Crecimiento"],
            format_func=objetivo_fmt,
            key="perfil_objetivo",
            on_change=_sync_draft,
        )
        tolerancia = st.select_slider(
            "¿Qué caída temporal aceptarías?",
            options=[0, 5, 10, 15, 20, 30, 50],
            format_func=lambda value: f"{value}%",
            key="perfil_tolerancia",
            on_change=_sync_draft,
            help="Es una caída hipotética del valor de la cartera; no es una pérdida máxima garantizada.",
        )
        if tolerancia == 0 and objetivo == "Crecimiento":
            st.warning(
                "Esta combinación requiere revisión manual. Podés conservarla y "
                "continuar; el motor informará ese resultado sin cambiar tus datos."
            )
        st.caption("Imaginá que tu inversión baja por un tiempo. Elegí cuánto te sentirías capaz de tolerar; no es un límite de pérdida garantizado.")
        if "tolerancia" in errors:
            st.error(errors["tolerancia"])
        liquidez = st.slider(
            "¿Cuánto necesitás tener disponible?",
            0,
            100,
            format="%d%%",
            key="perfil_liquidez",
            on_change=_sync_draft,
            help="Parte del capital que el ejercicio intentará mantener disponible con rapidez.",
        )
        st.caption("Porción que querés disponible en 24/48 h dentro del ejercicio. El acceso real depende de cada instrumento.")
        if "liquidez" in errors:
            st.error(errors["liquidez"])

    data = _collect_profile()
    if capital is None:
        st.caption("Completá el capital para ver el ejemplo de variación y liquidez en dinero.")
    else:
        st.caption(
            f"Con {moneda_fmt(capital, moneda)} como ejemplo, una tolerancia de "
            f"{tolerancia}% equivale a {moneda_fmt(capital * tolerancia / 100, moneda)} "
            f"de variación temporal; una liquidez de {liquidez}% equivale a "
            f"{moneda_fmt(capital * liquidez / 100, moneda)}. "
            "Son ejemplos, no pronósticos ni garantías."
        )

    saved_profile = st.session_state.get("datos_inversor")
    if saved_profile and data != saved_profile:
        st.info("Tenés cambios sin guardar. La evaluación anterior sigue usando el perfil guardado.")
    elif saved_profile:
        st.success("Este formulario coincide con el perfil guardado.")
    else:
        st.caption("Borrador sin guardar: tu perfil se guardará al continuar.")
    if saved_profile and data != saved_profile:
        st.button(
            "Descartar cambios del perfil",
            key="perfil_descartar_cambios",
            on_click=_discard_profile_draft,
        )

    back_col, next_col = st.columns(2)
    with back_col:
        st.button("← Volver al inicio", on_click=set_step, args=("inicio",), width="stretch")
    with next_col:
        if st.button("Guardar perfil y continuar →", type="primary", width="stretch"):
            errors = _validate_profile(data)
            st.session_state.errores_perfil = errors
            if errors:
                st.rerun()
            else:
                save_profile(data)
                st.session_state.perfil_borrador = dict(data)
                set_step("escenario")
                st.rerun()
