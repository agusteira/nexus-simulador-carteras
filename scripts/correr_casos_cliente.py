"""Demuestra y contrasta los casos del Grupo G sin consultar la red."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def diferencias(actual, esperado, ruta=""):
    """Devuelve rutas y valores distintos, incluyendo claves ausentes."""
    if isinstance(actual, dict) and isinstance(esperado, dict):
        detalle = []
        for clave in sorted(actual.keys() | esperado.keys()):
            nombre = f"{ruta}.{clave}" if ruta else clave
            if clave not in actual:
                detalle.append(f"{nombre}: falta; esperado {esperado[clave]!r}")
            elif clave not in esperado:
                detalle.append(f"{nombre}: adicional {actual[clave]!r}")
            else:
                detalle.extend(diferencias(actual[clave], esperado[clave], nombre))
        return detalle
    if actual != esperado:
        return [f"{ruta}: obtenido {actual!r}; esperado {esperado!r}"]
    return []


def mostrar(caso):
    print(f"\n{caso['id']}: {caso['descripcion']}")
    datos = caso["datos"]
    print(f"Entradas: tolerancia {datos['tolerancia']}%; horizonte {datos['horizonte']} meses; "
          f"objetivo {datos['objetivo']}; liquidez {datos['liquidez']}%; "
          f"capital {datos['capital']} {datos['moneda']}")
    senales = [nombre for nombre in ("inflacion_alta", "presion_cambiaria", "volatilidad_alta")
               if caso["mercado"][nombre]]
    print(f"Señales de mercado activas: {', '.join(senales) or 'ninguna'}; "
          f"escenario confirmado: {'sí' if caso['mercado']['mercado_actualizado'] else 'no'}")
    resultado = caso["resultado"]
    print(f"Estado final: {resultado['estado']}")
    print(f"Perfil: {resultado.get('perfil_riesgo', 'no determinado')}; "
          f"régimen: {resultado.get('regimen_mercado', 'no determinado')}")
    for categoria, porcentaje in resultado.get("cartera_porcentual", {}).items():
        print(f"  {categoria}: {porcentaje}%")
    for error in resultado.get("errores", []):
        print(f"  {error['codigo']}: {error['mensaje']}")
    print("Traza de reglas disparadas:")
    for entrada in caso["traza"]:
        print(f"  {entrada['orden']}. N{entrada['nivel']} {entrada['codigo']}: {entrada['conclusion']}")
    if not caso["traza"]:
        print("  Sin reglas disparadas: la validación de entrada derivó la consulta.")
    if caso["coincide"]:
        print("OK (coincide con la conclusión esperada por el cliente)")
    else:
        print("DIFERENCIA")
        for detalle in caso["diferencias"]:
            print(f"  {detalle}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caso", help="Ejecutar sólo el caso indicado, por ejemplo C03")
    parser.add_argument("--json", action="store_true", help="Mostrar resultados crudos en JSON")
    args = parser.parse_args(argv)
    casos = json.loads((ROOT / "docs/casos-brief.json").read_text(encoding="utf-8"))["casos"]
    if args.caso:
        casos = [caso for caso in casos if caso["id"] == args.caso]
        if not casos:
            parser.error(f"Caso desconocido: {args.caso}")
    salidas = []
    previo = os.environ.get("NEXUS_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="nexus-casos-") as directorio:
        os.environ["NEXUS_DATA_DIR"] = directorio
        try:
            from nexus.service import evaluar, evaluar_con_traza

            for caso in casos:
                resultado, auditoria, errores, traza = evaluar_con_traza(caso["datos"], caso["mercado"])
                verificado, audit, errors = evaluar(caso["datos"], caso["mercado"])
                verificado.pop("fecha_ejecucion", None)
                verificado.pop("version_matriz", None)
                actual = json.loads(json.dumps({
                    "resultado": verificado, "auditoria": audit, "errores": errors,
                }))
                detalle = diferencias(actual, caso["expected"])
                salidas.append({
                    "id": caso["id"], "descripcion": caso["descripcion"],
                    "datos": caso["datos"], "mercado": caso["mercado"],
                    "resultado": resultado, "auditoria": auditoria, "errores": errores,
                    "traza": traza, "coincide": not detalle, "diferencias": detalle,
                })
        finally:
            if previo is None:
                os.environ.pop("NEXUS_DATA_DIR", None)
            else:
                os.environ["NEXUS_DATA_DIR"] = previo
    coinciden = sum(caso["coincide"] for caso in salidas)
    if args.json:
        print(json.dumps({"casos": salidas, "coinciden": coinciden, "total": len(salidas)},
                         ensure_ascii=False, indent=2))
    else:
        for caso in salidas:
            mostrar(caso)
        print(f"\n{coinciden}/{len(salidas)} casos coinciden con lo esperado por el cliente")
    return 0 if coinciden == len(salidas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
