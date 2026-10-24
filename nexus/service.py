from datetime import datetime

from .engine import Inversor, Mercado, MotorRoboAdvisor, Perfil, Regimen
from .portfolio import construir_cartera
from .validation import validar_entrada


def evaluar(datos, mercado):
    """Devuelve la recomendación, la auditoría y los errores de validación."""
    errores = validar_entrada(
        datos["capital"],
        datos["horizonte"],
        datos["objetivo"],
        datos["tolerancia"],
        datos["liquidez"],
        mercado["mercado_actualizado"],
    )
    if errores:
        resultado = {
            "estado": "DERIVADO_ASESOR_MANUAL",
            "errores": [{"codigo": codigo, "mensaje": mensaje} for codigo, mensaje in errores],
            "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        }
        return resultado, [], errores

    motor = MotorRoboAdvisor()
    motor.reset()
    motor.declare(
        Inversor(
            tolerancia=datos["tolerancia"],
            horizonte=datos["horizonte"],
            objetivo=datos["objetivo"],
            liquidez=datos["liquidez"],
        )
    )
    motor.declare(
        Mercado(
            inflacion_alta=mercado["inflacion_alta"],
            presion_cambiaria=mercado["presion_cambiaria"],
            volatilidad_alta=mercado["volatilidad_alta"],
        )
    )
    motor.run()

    hechos = list(motor.facts.values())
    perfiles = [hecho["nombre"] for hecho in hechos if isinstance(hecho, Perfil)]
    regimenes = [hecho["nombre"] for hecho in hechos if isinstance(hecho, Regimen)]
    auditoria = motor.auditoria

    if not perfiles or not regimenes:
        resultado = {
            "estado": "DERIVADO_ASESOR_MANUAL",
            "errores": [{
                "codigo": "ERR_INFERENCIA_INCOMPLETA",
                "mensaje": "El motor no produjo todos los hechos necesarios.",
            }],
        }
        return resultado, auditoria, errores

    perfil, regimen = perfiles[0], regimenes[0]
    try:
        cartera = construir_cartera(perfil, regimen, datos["liquidez"])
        resultado = {
            "estado": "RECOMENDACION_EXITOSA",
            "moneda": datos["moneda"],
            "capital": datos["capital"],
            "perfil_riesgo": perfil,
            "regimen_mercado": regimen,
            "objetivo": datos["objetivo"],
            "horizonte_meses": datos["horizonte"],
            "cartera_porcentual": cartera,
            "montos_estimados": {
                categoria: round(datos["capital"] * porcentaje / 100, 2)
                for categoria, porcentaje in cartera.items()
            },
            "instrumentos": [],
            "auditoria": auditoria,
            "advertencia": "Distribución ilustrativa, no asesoramiento financiero personalizado.",
            "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        }
    except ValueError as exc:
        resultado = {
            "estado": "DERIVADO_ASESOR_MANUAL",
            "errores": [{"codigo": "ERR_ASIGNACION_INVIABLE", "mensaje": str(exc)}],
        }
    return resultado, auditoria, errores
