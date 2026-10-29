import streamlit as st

PASOS = ("inicio", "perfil", "escenario", "revision", "resultado")
VISTAS_EXTRA = ("auditoria", "historial", "administracion")


def initialize_session():
    if "resultado_robo" not in st.session_state:
        st.session_state.resultado_robo = None
    if "auditoria_robo" not in st.session_state:
        st.session_state.auditoria_robo = []
    if "errores_robo" not in st.session_state:
        st.session_state.errores_robo = []
    st.session_state.setdefault("paso_actual", "inicio")
    st.session_state.setdefault("perfil_borrador", {})
    st.session_state.setdefault("escenario_borrador", {})
    st.session_state.setdefault("contexto_mercado", None)
    st.session_state.setdefault("snapshot_ejecucion", None)
    st.session_state.setdefault("errores_perfil", {})
    st.session_state.setdefault("mercado_intento_guardar", False)


def set_step(step):
    if step in PASOS or step in VISTAS_EXTRA:
        st.session_state.paso_actual = step


def save_profile(data):
    st.session_state.datos_inversor = dict(data)


def save_market(data, metadata):
    st.session_state.datos_mercado = dict(data)
    st.session_state.contexto_mercado = dict(metadata)


def save_execution(result, audit, errors):
    st.session_state.resultado_robo = result
    st.session_state.auditoria_robo = list(audit)
    st.session_state.errores_robo = list(errors)
    st.session_state.snapshot_ejecucion = {
        "perfil": dict(st.session_state.get("datos_inversor") or {}),
        "escenario": dict(st.session_state.get("datos_mercado") or {}),
    }


def is_result_stale():
    if not st.session_state.get("resultado_robo"):
        return False
    snapshot = st.session_state.get("snapshot_ejecucion")
    if snapshot is None:
        return True
    return snapshot != {
        "perfil": dict(st.session_state.get("datos_inversor") or {}),
        "escenario": dict(st.session_state.get("datos_mercado") or {}),
    } or has_unsaved_changes()


def has_unsaved_changes():
    for draft_key, saved_key in (
        ("perfil_borrador", "datos_inversor"),
        ("escenario_borrador", "datos_mercado"),
    ):
        draft = st.session_state.get(draft_key) or {}
        saved = st.session_state.get(saved_key) or {}
        if draft and draft != saved:
            return True
    return False
