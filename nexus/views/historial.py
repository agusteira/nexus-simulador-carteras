"""RF-09: consulta, auditoría y comparación de recomendaciones previas."""

from datetime import date, timedelta
import json

import streamlit as st

from ..history import consultar_historial, listar_usuarios, obtener_evaluacion
from ..state import set_step
from ..ui.common import (
    escenario_fmt,
    fecha_fmt,
    moneda_fmt,
    objetivo_fmt,
    perfil_fmt,
)


def _etiqueta(fila):
    return (
        f"#{fila['id']} · {fecha_fmt(fila['fecha_ejecucion'])} · {fila['usuario_id']} · "
        f"{perfil_fmt(fila['perfil_riesgo']) if fila['perfil_riesgo'] else fila['estado']}"
    )


def _render_detalle(registro):
    resultado, entrada = registro["resultado"], registro["entrada"]
    st.markdown(f"**Estado:** `{registro['estado']}` · **Usuario:** {registro['usuario_id']}")
    st.write(
        f"**Fecha:** {fecha_fmt(registro['fecha_ejecucion'])} · "
        f"**Versión de la matriz:** v{registro['version_matriz'] or '—'}"
    )
    st.write(
        f"**Capital:** {moneda_fmt(entrada.get('capital'), entrada.get('moneda', 'ARS'))} · "
        f"**Objetivo:** {objetivo_fmt(entrada.get('objetivo'))} · "
        f"**Horizonte:** {entrada.get('horizonte')} meses · "
        f"**Tolerancia:** {entrada.get('tolerancia')}% · **Liquidez:** {entrada.get('liquidez')}%"
    )
    if resultado.get("perfil_riesgo"):
        st.write(
            f"**Perfil:** {perfil_fmt(resultado['perfil_riesgo'])} · "
            f"**Escenario:** {escenario_fmt(resultado.get('regimen_mercado'))}"
        )
    cartera = resultado.get("cartera_porcentual") or {}
    if cartera:
        montos = resultado.get("montos_estimados") or {}
        st.markdown("#### Asignación")
        st.dataframe(
            [
                {"Categoría": c, "%": p, "Monto": moneda_fmt(montos.get(c), resultado.get("moneda", "ARS"))}
                for c, p in cartera.items()
            ],
            width="stretch",
            hide_index=True,
        )
    if registro["auditoria"]:
        st.markdown("#### Traza de ejecución")
        st.dataframe(registro["auditoria"], width="stretch", hide_index=True)
    if resultado.get("errores"):
        st.markdown("#### Errores / derivación")
        st.dataframe(resultado["errores"], width="stretch", hide_index=True)


def _render_comparacion(a, b):
    st.markdown("## Comparación")
    cartera_a = a["resultado"].get("cartera_porcentual") or {}
    cartera_b = b["resultado"].get("cartera_porcentual") or {}
    filas = [
        {
            "Concepto": "Fecha",
            f"#{a['id']}": fecha_fmt(a["fecha_ejecucion"]),
            f"#{b['id']}": fecha_fmt(b["fecha_ejecucion"]),
            "Diferencia": "",
        },
    ]
    for concepto, clave in (("Usuario", "usuario_id"), ("Estado", "estado"),
                            ("Perfil", "perfil_riesgo"), ("Escenario", "regimen_mercado"),
                            ("Versión matriz", "version_matriz")):
        filas.append({
            "Concepto": concepto,
            f"#{a['id']}": str(a[clave] or "—"),
            f"#{b['id']}": str(b[clave] or "—"),
            "Diferencia": "" if a[clave] == b[clave] else "cambia",
        })
    for campo in ("capital", "horizonte", "tolerancia", "liquidez", "objetivo", "moneda"):
        va, vb = a["entrada"].get(campo), b["entrada"].get(campo)
        filas.append({
            "Concepto": f"Entrada · {campo}",
            f"#{a['id']}": str(va),
            f"#{b['id']}": str(vb),
            "Diferencia": "" if va == vb else "cambia",
        })
    for categoria in dict.fromkeys([*cartera_a, *cartera_b]):
        pa, pb = cartera_a.get(categoria, 0), cartera_b.get(categoria, 0)
        filas.append({
            "Concepto": f"{categoria} (%)",
            f"#{a['id']}": str(pa),
            f"#{b['id']}": str(pb),
            "Diferencia": f"{pb - pa:+d} pp" if pa != pb else "",
        })
    st.dataframe(filas, width="stretch", hide_index=True)
    izquierda, derecha = st.columns(2)
    with izquierda, st.container(border=True):
        st.markdown(f"### #{a['id']}")
        _render_detalle(a)
    with derecha, st.container(border=True):
        st.markdown(f"### #{b['id']}")
        _render_detalle(b)


def render():
    st.markdown('<div class="eyebrow">HISTORIAL</div>', unsafe_allow_html=True)
    st.title("Recomendaciones previas")
    st.markdown(
        "Consultá las evaluaciones guardadas por identificador de usuario y fecha, "
        "con su asignación y su traza completas, y compará dos de ellas."
    )

    usuarios = listar_usuarios()
    filtro_usuario, filtro_desde, filtro_hasta = st.columns([2, 1, 1])
    usuario = filtro_usuario.text_input(
        "Identificador de usuario",
        value=(st.session_state.get("datos_inversor") or {}).get("usuario_id", ""),
        key="historial_usuario",
        help="Vacío: todos los usuarios. Usuarios con historial: " + (", ".join(usuarios) or "ninguno"),
    )
    hoy = date.today()
    desde = filtro_desde.date_input("Desde", hoy - timedelta(days=30), key="historial_desde", format="DD/MM/YYYY")
    hasta = filtro_hasta.date_input("Hasta", hoy, key="historial_hasta", format="DD/MM/YYYY")

    filas = consultar_historial(usuario, desde, hasta)
    if not filas:
        st.info("No hay evaluaciones guardadas para esos filtros.")
        st.button("Volver al inicio", key="historial_volver", on_click=set_step, args=("inicio",))
        return

    st.dataframe(
        [
            {
                "ID": f["id"],
                "Fecha": fecha_fmt(f["fecha_ejecucion"]),
                "Usuario": f["usuario_id"],
                "Estado": f["estado"],
                "Perfil": perfil_fmt(f["perfil_riesgo"]) if f["perfil_riesgo"] else "—",
                "Escenario": escenario_fmt(f["regimen_mercado"]) if f["regimen_mercado"] else "—",
                "Matriz": f"v{f['version_matriz']}" if f["version_matriz"] else "—",
            }
            for f in filas
        ],
        width="stretch",
        hide_index=True,
    )
    opciones = {f["id"]: _etiqueta(f) for f in filas}

    st.markdown("## Detalle de una evaluación")
    elegido = st.selectbox("Evaluación", list(opciones), format_func=opciones.get, key="historial_detalle")
    registro = obtener_evaluacion(elegido)
    with st.container(border=True):
        _render_detalle(registro)
        with st.expander("JSON completo guardado"):
            st.json(registro)
        st.download_button(
            "Descargar JSON de esta evaluación",
            data=json.dumps(registro, ensure_ascii=False, indent=2),
            file_name=f"historial_nexus_{elegido}.json",
            mime="application/json",
            key="historial_descargar",
        )

    if len(filas) >= 2:
        st.markdown("## Comparar dos evaluaciones")
        ids = list(opciones)
        col_a, col_b = st.columns(2)
        id_a = col_a.selectbox("Evaluación A", ids, index=1, format_func=opciones.get, key="historial_comparar_a")
        id_b = col_b.selectbox("Evaluación B", ids, index=0, format_func=opciones.get, key="historial_comparar_b")
        if id_a == id_b:
            st.caption("Elegí dos evaluaciones distintas para compararlas.")
        else:
            _render_comparacion(obtener_evaluacion(id_a), obtener_evaluacion(id_b))
    st.button("Volver al inicio", key="historial_volver", on_click=set_step, args=("inicio",))
