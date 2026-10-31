import streamlit as st

from ..state import has_unsaved_changes, is_result_stale, set_step


def render():
    perfil = st.session_state.get("datos_inversor")
    mercado = st.session_state.get("datos_mercado")
    perfil_dirty = bool(st.session_state.get("perfil_borrador")) and (
        st.session_state.get("perfil_borrador") != (perfil or {})
    )
    escenario_dirty = bool(st.session_state.get("escenario_borrador")) and (
        st.session_state.get("escenario_borrador") != (mercado or {})
    )
    resultado = st.session_state.get("resultado_robo")

    st.markdown("""
    <section class="welcome-hero">
      <div class="eyebrow">INVERTIR EMPIEZA POR ENTENDER</div>
      <h1>Tu dinero. Tus objetivos.<br><span>Un camino más claro.</span></h1>
      <p>Explorá cómo podría distribuirse tu capital según lo que necesitás.
      Te acompañamos en cada paso, sin que tengas que saber de inversiones.</p>
      <div class="hero-bottom"><span>4 pasos simples</span><span>Respuestas explicadas</span><span>A tu ritmo</span></div>
    </section>
    """, unsafe_allow_html=True)

    if resultado:
        if is_result_stale():
            st.warning("Tenés una evaluación anterior que ya no coincide con los datos guardados.")
        else:
            st.success(f"Última evaluación: {resultado.get('estado', 'SIN_ESTADO')}")
    elif has_unsaved_changes():
        st.info("Tenés borradores sin guardar. Volvé al paso que estabas editando para continuar.")

    if has_unsaved_changes():
        if perfil_dirty:
            label = "Continuar borrador del perfil →" if not perfil else "Volver al perfil →"
            next_step = "perfil"
        else:
            label = "Continuar borrador del escenario →" if not mercado else "Volver al escenario →"
            next_step = "escenario"
    elif not perfil:
        label, next_step = "Comenzar simulación →", "perfil"
    elif not mercado:
        label, next_step = "Continuar con el escenario →", "escenario"
    elif not resultado or is_result_stale():
        label, next_step = "Revisar los datos →", "revision"
    else:
        label, next_step = "Consultar resultado →", "resultado"
    st.button(
        label,
        type="primary",
        width="stretch",
        on_click=set_step,
        args=(next_step,),
    )

    st.markdown('<div class="section-intro"><div class="eyebrow">ASÍ FUNCIONA</div><h2>De tus respuestas a una distribución.</h2><p>Vos contás qué necesitás. NEXUS te ayuda a explorar el resultado.</p></div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="journey-grid">
      <article class="journey-card"><span class="card-number">01</span><h3>Contanos sobre vos</h3><p>Cuánto querés simular, por cuánto tiempo y qué tan cómodo te sentís con las variaciones.</p><span class="card-tag">Tu perfil</span></article>
      <article class="journey-card"><span class="card-number">02</span><h3>Probá un contexto</h3><p>Elegí un ejemplo ficticio del mercado. Te explicamos qué significa cada opción.</p><span class="card-tag">Escenario</span></article>
      <article class="journey-card"><span class="card-number">03</span><h3>Revisá con calma</h3><p>Confirmá tus respuestas antes de generar la evaluación. Podés volver y editar.</p><span class="card-tag">Revisar datos</span></article>
      <article class="journey-card"><span class="card-number">04</span><h3>Entendé el resultado</h3><p>Mirá porcentajes, montos y los motivos de una distribución ilustrativa.</p><span class="card-tag">Resultado</span></article>
    </div>
    <div class="learning-note"><b>Un espacio para aprender.</b> Esta demo usa reglas y escenarios manuales. En el resultado podés explorar opciones publicadas de fondos y mercado local, sin ejecutar inversiones. Tu avance se conserva durante la sesión y las evaluaciones se guardan en el historial del servidor.</div>
    """, unsafe_allow_html=True)
    with st.expander("Antes de empezar: dos conceptos útiles"):
        st.markdown("**Tolerancia:** cuánto aceptarías ver bajar temporalmente tu capital en un ejemplo. No es un límite garantizado de pérdida.\n\n**Liquidez:** qué parte del dinero querés poder usar pronto. No garantiza acceso inmediato; los plazos dependen de cada opción. Verás ambos ejemplos en pesos o dólares al completar el capital.")
