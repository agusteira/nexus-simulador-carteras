"""Ensamble de la cartera: delega todo el cálculo en las reglas de MotorRoboAdvisor."""
from .engine import CarteraFinal, FalloAsignacion, Inversor, MotorRoboAdvisor, Perfil, Regimen, hechos_de
from .matrices import version_activa


def ejecutar_asignacion(perfil, regimen, liquidez_minima, matriz, horizonte=None, objetivo=None):
    """Corre sólo la cadena de asignación partiendo de Perfil y Regimen ya conocidos."""
    motor = MotorRoboAdvisor(matriz)
    motor.reset()
    motor.declare(Inversor(horizonte=horizonte, objetivo=objetivo, liquidez=liquidez_minima))
    motor.declare(Perfil(nombre=perfil))
    motor.declare(Regimen(nombre=regimen))
    motor.run()
    return motor


def cartera_de(motor):
    """Devuelve el dict de la CarteraFinal o lanza ValueError con el mensaje legacy."""
    fallos = hechos_de(motor, FalloAsignacion)
    if fallos:
        raise ValueError(fallos[0]["mensaje"])
    finales = hechos_de(motor, CarteraFinal)
    if not finales:
        raise ValueError("La asignación contiene valores inválidos.")
    return {categoria: porcentaje for categoria, porcentaje in finales[0]["valores"]}


def construir_cartera(perfil, regimen, liquidez_minima, matriz=None, *, horizonte=None, objetivo=None, auditoria=None):
    """Arma la cartera con la matriz indicada o, si no se pasa, la versión activa (RF-08)."""
    if matriz is None:
        _, matriz = version_activa()
    motor = ejecutar_asignacion(perfil, regimen, liquidez_minima, matriz, horizonte, objetivo)
    if auditoria is not None:
        auditoria.extend(motor.auditoria)
    return cartera_de(motor)
