from datetime import datetime

from .engine import Inversor, Mercado, MotorRoboAdvisor, Perfil, Regimen, hechos_de
from .matrices import version_activa
from .portfolio import cartera_de
from .instrument_rules import POLICY_VERSION
from .validation import validar_entrada


def evaluar(datos, mercado):
    """Devuelve la recomendación, la auditoría y los errores de validación."""
    resultado, auditoria, errores, _ = evaluar_con_traza(datos, mercado)
    return resultado, auditoria, errores


def evaluar_con_traza(datos, mercado):
    """Igual que evaluar() y además la traza completa de reglas disparadas (con nivel)."""
    version_matriz, matriz = version_activa()
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
            "version_matriz": version_matriz,
            "version_politica_instrumentos": POLICY_VERSION,
            "revision_experta": "pendiente",
        }
        return resultado, [], errores, []

    motor = MotorRoboAdvisor(matriz)
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
    traza = list(motor.traza_reglas)

    if not perfiles or not regimenes:
        resultado = {
            "estado": "DERIVADO_ASESOR_MANUAL",
            "errores": [{
                "codigo": "ERR_INFERENCIA_INCOMPLETA",
                "mensaje": "El motor no produjo todos los hechos necesarios.",
            }],
            "version_matriz": version_matriz,
            "version_politica_instrumentos": POLICY_VERSION,
            "revision_experta": "pendiente",
        }
        return resultado, auditoria, errores, traza

    perfil, regimen = perfiles[0], regimenes[0]
    try:
        cartera = cartera_de(motor)
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
            "version_matriz": version_matriz,
            "version_politica_instrumentos": POLICY_VERSION,
            "revision_experta": "pendiente",
        }
    except ValueError as exc:
        resultado = {
            "estado": "DERIVADO_ASESOR_MANUAL",
            "errores": [{"codigo": "ERR_ASIGNACION_INVIABLE", "mensaje": str(exc)}],
            "version_matriz": version_matriz,
            "version_politica_instrumentos": POLICY_VERSION,
            "revision_experta": "pendiente",
        }
    return resultado, auditoria, errores, traza
