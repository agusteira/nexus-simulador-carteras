"""RF-08: matrices de decisión editables y versionadas, sin redesplegar.

La matriz inicial vive en ``config/matriz_decision.json`` (versión 1). Cada
cambio guardado desde Administración crea una versión nueva en
``data/matrices_versiones.json``; el historial nunca se reescribe y restaurar
una versión anterior también genera una versión nueva que la copia.
"""

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
from threading import Lock


ROOT = Path(__file__).resolve().parents[1]
MATRIZ_INICIAL = ROOT / "config" / "matriz_decision.json"
CATEGORIAS = ("Renta fija inflación", "Renta fija cambiaria", "Renta variable", "Liquidez inmediata")
PERFILES = ("CONSERVADOR", "MODERADO", "AGRESIVO")
REGIMENES_AJUSTABLES = ("VOLATILIDAD_ALTA", "INFLACION_ALTA", "PRESION_CAMBIARIA")
_lock = Lock()


def directorio_datos():
    """Carpeta de datos de ejecución; ``NEXUS_DATA_DIR`` permite aislarla en tests."""
    return Path(os.environ.get("NEXUS_DATA_DIR") or ROOT / "data")


def _archivo_versiones():
    return directorio_datos() / "matrices_versiones.json"


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


def matriz_inicial():
    datos = json.loads(MATRIZ_INICIAL.read_text(encoding="utf-8"))
    datos.pop("descripcion", None)
    return datos


def _es_entero(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_matriz(matriz):
    """Devuelve una lista de mensajes; vacía si la matriz es utilizable."""
    errores = []
    umbrales = matriz.get("umbrales_perfil") or {}
    conservador = umbrales.get("conservador_tolerancia_max")
    moderado = umbrales.get("moderado_tolerancia_max")
    if not (_es_entero(conservador) and _es_entero(moderado) and 0 <= conservador < moderado <= 100):
        errores.append("Umbrales: se requiere 0 ≤ máximo conservador < máximo moderado ≤ 100.")

    bases = matriz.get("carteras_base") or {}
    for perfil in PERFILES:
        base = bases.get(perfil)
        if not isinstance(base, dict) or set(base) != set(CATEGORIAS):
            errores.append(f"Cartera base {perfil}: debe incluir exactamente las 4 categorías.")
            continue
        if any(not _es_entero(v) or v < 0 for v in base.values()):
            errores.append(f"Cartera base {perfil}: los porcentajes deben ser enteros no negativos.")
        elif sum(base.values()) != 100:
            errores.append(f"Cartera base {perfil}: suma {sum(base.values())}%, debe sumar 100%.")

    prioridad = matriz.get("prioridad_regimen") or []
    if sorted(prioridad) != sorted(REGIMENES_AJUSTABLES):
        errores.append("Prioridad de regímenes: debe ordenar cada régimen una sola vez.")

    ajustes = matriz.get("ajustes_regimen") or {}
    for regimen in REGIMENES_AJUSTABLES:
        ajuste = ajustes.get(regimen)
        if not isinstance(ajuste, dict):
            errores.append(f"Ajuste {regimen}: falta la definición.")
            continue
        if ajuste.get("desde") not in CATEGORIAS or ajuste.get("hacia") not in CATEGORIAS:
            errores.append(f"Ajuste {regimen}: categorías de origen o destino inválidas.")
        elif ajuste["desde"] == ajuste["hacia"]:
            errores.append(f"Ajuste {regimen}: origen y destino deben ser distintos.")
        if not _es_entero(ajuste.get("puntos")) or not 0 <= ajuste["puntos"] <= 100:
            errores.append(f"Ajuste {regimen}: los puntos deben ser un entero entre 0 y 100.")

    topes = matriz.get("topes_clase") or {}
    for perfil in PERFILES:
        for categoria, tope in (topes.get(perfil) or {}).items():
            if categoria not in CATEGORIAS or categoria == "Liquidez inmediata":
                errores.append(f"Tope {perfil}: categoría no admitida «{categoria}».")
            elif not _es_entero(tope) or not 0 <= tope <= 100:
                errores.append(f"Tope {perfil} / {categoria}: debe ser un entero entre 0 y 100.")

    orden = matriz.get("orden_retiro_liquidez") or []
    if sorted(orden) != sorted(c for c in CATEGORIAS if c != "Liquidez inmediata"):
        errores.append("Orden de retiro para liquidez: debe incluir cada categoría no líquida una vez.")
    return errores


def _leer_historial():
    archivo = _archivo_versiones()
    if archivo.exists():
        return json.loads(archivo.read_text(encoding="utf-8"))
    return {
        "activa": 1,
        "versiones": [{
            "version": 1,
            "fecha": None,
            "autor": "sistema",
            "nota": "Matriz inicial (config/matriz_decision.json).",
            "origen": None,
            "matriz": matriz_inicial(),
        }],
    }


def _escribir_historial(historial):
    archivo = _archivo_versiones()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    temporal = archivo.with_suffix(".tmp")
    temporal.write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, archivo)  # escritura atómica: nunca queda un JSON a medias


def listar_versiones():
    """Versiones de la más nueva a la más vieja, con la marca de activa."""
    historial = _leer_historial()
    return [
        {**deepcopy(v), "activa": v["version"] == historial["activa"]}
        for v in reversed(historial["versiones"])
    ]


def obtener_version(numero):
    for version in _leer_historial()["versiones"]:
        if version["version"] == numero:
            return deepcopy(version)
    raise KeyError(f"No existe la versión {numero} de la matriz.")


def version_activa():
    """Devuelve ``(numero_version, matriz)`` de la versión vigente."""
    historial = _leer_historial()
    version = next(v for v in historial["versiones"] if v["version"] == historial["activa"])
    return version["version"], deepcopy(version["matriz"])


def guardar_version(matriz, autor, nota="", origen=None):
    """Valida, agrega una versión nueva y la activa. Devuelve su número."""
    errores = validar_matriz(matriz)
    if errores:
        raise ValueError(" ".join(errores))
    if not (autor or "").strip():
        raise ValueError("Indicá quién realiza el cambio.")
    with _lock:
        historial = _leer_historial()
        numero = max(v["version"] for v in historial["versiones"]) + 1
        historial["versiones"].append({
            "version": numero,
            "fecha": _ahora(),
            "autor": autor.strip(),
            "nota": (nota or "").strip(),
            "origen": origen,
            "matriz": deepcopy(matriz),
        })
        historial["activa"] = numero
        _escribir_historial(historial)
    return numero


def restaurar_version(numero, autor, nota=""):
    """Vuelve a una versión anterior creando una nueva copia (historial inmutable)."""
    anterior = obtener_version(numero)
    return guardar_version(
        anterior["matriz"], autor, nota or f"Restauración de la versión {numero}.", origen=numero
    )
