"""RF-09: historial persistente de recomendaciones por usuario y fecha (SQLite)."""

from contextlib import closing
from datetime import datetime
import json
import sqlite3
import uuid

from .matrices import directorio_datos


USUARIO_ANONIMO = "anonimo"
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS evaluaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ejecucion_id TEXT NOT NULL UNIQUE,
    usuario_id TEXT NOT NULL COLLATE NOCASE,
    fecha_ejecucion TEXT NOT NULL,
    estado TEXT NOT NULL,
    perfil_riesgo TEXT,
    regimen_mercado TEXT,
    version_matriz INTEGER,
    entrada_json TEXT NOT NULL,
    mercado_json TEXT NOT NULL,
    resultado_json TEXT NOT NULL,
    auditoria_json TEXT NOT NULL,
    errores_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluaciones_usuario_fecha
    ON evaluaciones (usuario_id, fecha_ejecucion);
"""


def _conectar():
    ruta = directorio_datos() / "historial.db"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(_ESQUEMA)
    return conexion


def normalizar_usuario(usuario_id):
    return (usuario_id or "").strip() or USUARIO_ANONIMO


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, default=str)


def guardar_evaluacion(datos, mercado, resultado, auditoria, errores):
    """Persiste una ejecución completa y devuelve su id en el historial."""
    fecha = resultado.get("fecha_ejecucion") or datetime.now().isoformat(timespec="seconds")
    with closing(_conectar()) as conexion, conexion:
        cursor = conexion.execute(
            """INSERT INTO evaluaciones (
                ejecucion_id, usuario_id, fecha_ejecucion, estado, perfil_riesgo,
                regimen_mercado, version_matriz, entrada_json, mercado_json,
                resultado_json, auditoria_json, errores_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                normalizar_usuario(datos.get("usuario_id")),
                fecha,
                resultado.get("estado", "SIN_ESTADO"),
                resultado.get("perfil_riesgo"),
                resultado.get("regimen_mercado"),
                resultado.get("version_matriz"),
                _json(datos),
                _json(mercado),
                _json(resultado),
                _json(list(auditoria)),
                _json(list(errores)),
            ),
        )
        return cursor.lastrowid


def consultar_historial(usuario_id=None, desde=None, hasta=None, limite=200):
    """Resumen de ejecuciones, de la más reciente a la más antigua.

    ``desde`` y ``hasta`` son fechas (``date``) inclusivas.
    """
    condiciones, parametros = [], []
    if (usuario_id or "").strip():
        condiciones.append("usuario_id = ?")
        parametros.append(usuario_id.strip())
    if desde:
        condiciones.append("substr(fecha_ejecucion, 1, 10) >= ?")
        parametros.append(desde.isoformat())
    if hasta:
        condiciones.append("substr(fecha_ejecucion, 1, 10) <= ?")
        parametros.append(hasta.isoformat())
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    with closing(_conectar()) as conexion:
        filas = conexion.execute(
            f"""SELECT id, usuario_id, fecha_ejecucion, estado, perfil_riesgo,
                       regimen_mercado, version_matriz
                FROM evaluaciones {where}
                ORDER BY fecha_ejecucion DESC, id DESC LIMIT ?""",
            (*parametros, limite),
        ).fetchall()
    return [dict(fila) for fila in filas]


def obtener_evaluacion(evaluacion_id):
    """Recupera íntegra una ejecución: entradas, asignación, traza y errores."""
    with closing(_conectar()) as conexion:
        fila = conexion.execute(
            "SELECT * FROM evaluaciones WHERE id = ?", (evaluacion_id,)
        ).fetchone()
    if fila is None:
        return None
    registro = {clave: fila[clave] for clave in fila.keys() if not clave.endswith("_json")}
    for clave in ("entrada", "mercado", "resultado", "auditoria", "errores"):
        registro[clave] = json.loads(fila[f"{clave}_json"])
    return registro


def listar_usuarios():
    with closing(_conectar()) as conexion:
        filas = conexion.execute(
            "SELECT DISTINCT usuario_id FROM evaluaciones ORDER BY usuario_id"
        ).fetchall()
    return [fila[0] for fila in filas]
