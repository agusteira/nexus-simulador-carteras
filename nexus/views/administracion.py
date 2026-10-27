"""RF-08: administración y versionado de las matrices de decisión."""

import json
import os

import streamlit as st

from ..matrices import (
    CATEGORIAS,
    PERFILES,
    REGIMENES_AJUSTABLES,
    guardar_version,
    listar_versiones,
    restaurar_version,
    validar_matriz,
    version_activa,
)
from ..state import set_step
from ..ui.common import escenario_fmt, fecha_fmt, perfil_fmt


def _clave_admin():
    clave = os.environ.get("NEXUS_ADMIN_CLAVE")
    if clave:
        return clave
    try:
        return st.secrets.get("NEXUS_ADMIN_CLAVE")
    except Exception:  # sin secrets.toml
        return None


def _acceso_permitido():
    clave = _clave_admin()
    if not clave:
        st.caption(
            "Modo demo: no hay clave de administrador configurada "
            "(variable de entorno o secreto `NEXUS_ADMIN_CLAVE`)."
        )
        return True
    if st.session_state.get("admin_autenticado"):
        return True
    ingresada = st.text_input("Clave de administrador", type="password", key="admin_clave")
    if st.button("Ingresar", key="admin_ingresar"):
        if ingresada == clave:
            st.session_state.admin_autenticado = True
            st.rerun()
        st.error("Clave incorrecta.")
    return False


def _formulario(version, matriz):
    k = f"adm_v{version}"  # claves por versión: al guardar, el formulario se recarga
    nueva = json.loads(json.dumps(matriz))
    with st.form(f"{k}_form"):
        st.markdown("## Umbrales de perfil (tolerancia a pérdidas, %)")
        izq, der = st.columns(2)
        nueva["umbrales_perfil"]["conservador_tolerancia_max"] = izq.number_input(
            "Máximo para CONSERVADOR", 0, 100,
            matriz["umbrales_perfil"]["conservador_tolerancia_max"], key=f"{k}_umb_c",
        )
        nueva["umbrales_perfil"]["moderado_tolerancia_max"] = der.number_input(
            "Máximo para MODERADO (por encima: AGRESIVO)", 0, 100,
            matriz["umbrales_perfil"]["moderado_tolerancia_max"], key=f"{k}_umb_m",
        )

        st.markdown("## Carteras base por perfil (%)")
        st.caption("Cada perfil debe sumar 100%.")
        for columna, perfil in zip(st.columns(len(PERFILES)), PERFILES):
            with columna:
                st.markdown(f"**{perfil_fmt(perfil)}**")
                for categoria in CATEGORIAS:
                    nueva["carteras_base"][perfil][categoria] = st.number_input(
                        categoria, 0, 100, matriz["carteras_base"][perfil][categoria],
                        key=f"{k}_base_{perfil}_{categoria}",
                    )
                st.caption(f"Suma actual guardada: {sum(matriz['carteras_base'][perfil].values())}%")

        st.markdown("## Topes por clase de activo (%)")
        st.caption("Si una clase supera su tope, el excedente pasa a liquidez inmediata.")
        no_liquidas = [c for c in CATEGORIAS if c != "Liquidez inmediata"]
        for columna, perfil in zip(st.columns(len(PERFILES)), PERFILES):
            with columna:
                st.markdown(f"**{perfil_fmt(perfil)}**")
                topes = nueva["topes_clase"].setdefault(perfil, {})
                for categoria in no_liquidas:
                    topes[categoria] = st.number_input(
                        f"Tope {categoria}", 0, 100,
                        matriz.get("topes_clase", {}).get(perfil, {}).get(categoria, 100),
                        key=f"{k}_tope_{perfil}_{categoria}",
                    )

        st.markdown("## Reglas de ajuste por escenario")
        for regimen in REGIMENES_AJUSTABLES:
            ajuste = matriz["ajustes_regimen"][regimen]
            st.markdown(f"**{escenario_fmt(regimen)}** (`{regimen}`)")
            c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
            nueva["ajustes_regimen"][regimen] = {
                "activo": c1.checkbox("Activa", ajuste.get("activo", True), key=f"{k}_aj_{regimen}_act"),
                "desde": c2.selectbox("Mover desde", CATEGORIAS, CATEGORIAS.index(ajuste["desde"]), key=f"{k}_aj_{regimen}_desde"),
                "hacia": c3.selectbox("Hacia", CATEGORIAS, CATEGORIAS.index(ajuste["hacia"]), key=f"{k}_aj_{regimen}_hacia"),
                "puntos": c4.number_input("Puntos máx.", 0, 100, ajuste["puntos"], key=f"{k}_aj_{regimen}_pts"),
            }

        st.markdown("## Prioridad entre escenarios")
        st.caption("Si se activan varias señales, gana la de mayor prioridad.")
        prioridad = []
        for posicion, (columna, actual) in enumerate(zip(st.columns(3), matriz["prioridad_regimen"]), start=1):
            prioridad.append(columna.selectbox(
                f"Prioridad {posicion}", REGIMENES_AJUSTABLES,
                REGIMENES_AJUSTABLES.index(actual), format_func=escenario_fmt,
                key=f"{k}_prio_{posicion}",
            ))
        nueva["prioridad_regimen"] = prioridad

        st.markdown("## Registro del cambio")
        autor = st.text_input("Responsable del cambio", key=f"{k}_autor")
        nota = st.text_input("Motivo o nota de la versión", key=f"{k}_nota")
        enviado = st.form_submit_button("Guardar como nueva versión", type="primary")

    if enviado:
        errores = validar_matriz(nueva)
        if not autor.strip():
            errores.append("Indicá quién realiza el cambio.")
        if nueva == matriz:
            errores.append("No hay cambios respecto de la versión activa.")
        if errores:
            for error in errores:
                st.error(error)
        else:
            numero = guardar_version(nueva, autor, nota)
            st.session_state.admin_mensaje = f"Se guardó y activó la versión {numero}."
            st.rerun()


def _historial(activa):
    st.markdown("## Historial de versiones")
    versiones = listar_versiones()
    st.dataframe(
        [
            {
                "Versión": v["version"],
                "Activa": "✓" if v["activa"] else "",
                "Fecha": fecha_fmt(v["fecha"]) if v["fecha"] else "Inicial",
                "Responsable": v["autor"],
                "Nota": v["nota"],
                "Restaurada de": v.get("origen") or "",
            }
            for v in versiones
        ],
        width="stretch",
        hide_index=True,
    )
    numeros = [v["version"] for v in versiones]
    elegida = st.selectbox("Ver detalle de la versión", numeros, key="admin_version_detalle")
    detalle = next(v for v in versiones if v["version"] == elegida)
    with st.expander(f"Matriz de la versión {elegida} (JSON)"):
        st.json(detalle["matriz"])
    if elegida != activa:
        autor = st.text_input("Responsable de la restauración", key="admin_restaurar_autor")
        if st.button(f"Restaurar la versión {elegida}", key="admin_restaurar"):
            if not autor.strip():
                st.error("Indicá quién realiza la restauración.")
            else:
                numero = restaurar_version(elegida, autor)
                st.session_state.admin_mensaje = (
                    f"Se restauró la versión {elegida} como nueva versión {numero}."
                )
                st.rerun()


def render():
    st.markdown('<div class="eyebrow">ADMINISTRACIÓN</div>', unsafe_allow_html=True)
    st.title("Matrices de decisión")
    st.markdown(
        "Ajustá umbrales, carteras base, topes por clase de activo y reglas de ajuste "
        "sin redesplegar. Cada cambio crea una versión nueva; las evaluaciones "
        "registran qué versión usaron."
    )
    if not _acceso_permitido():
        return
    mensaje = st.session_state.pop("admin_mensaje", None)
    if mensaje:
        st.success(mensaje)

    version, matriz = version_activa()
    st.info(f"Versión activa: **v{version}**. Las próximas evaluaciones la van a usar.")
    _formulario(version, matriz)
    _historial(version)
    st.button("Volver al inicio", key="admin_volver", on_click=set_step, args=("inicio",))
