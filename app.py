from pathlib import Path

import streamlit as st

from nexus.state import initialize_session
from nexus.ui.common import (
    render_footer,
    render_header,
    render_sidebar,
    render_step_indicator,
)
from nexus.views import (
    administracion,
    auditoria,
    historial,
    mercado,
    perfil_inversor,
    resultado,
    revision,
    resumen,
)


st.set_page_config(
    page_title="NEXUS | Simulador de carteras",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)

css_path = Path(__file__).parent / "nexus" / "ui" / "styles.css"
st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

initialize_session()
pagina = render_sidebar()
render_header()
render_step_indicator(pagina)

vistas = {
    "inicio": resumen.render,
    "perfil": perfil_inversor.render,
    "escenario": mercado.render,
    "revision": revision.render,
    "resultado": resultado.render,
    "auditoria": auditoria.render,
    "historial": historial.render,
    "administracion": administracion.render,
}
vistas[pagina]()
render_footer()
