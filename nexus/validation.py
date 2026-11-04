from .engine import derivaciones_de_coherencia


def validar_entrada(
    capital, horizonte, objetivo, tolerancia, liquidez, mercado_actualizado
):
    errores = []
    if capital <= 0:
        errores.append(("ERR_CAPITAL_INVALIDO", "El capital debe ser mayor que cero."))
    if horizonte <= 0:
        errores.append(("ERR_HORIZONTE_INVALIDO", "El horizonte debe ser mayor que cero."))
    if not 0 <= tolerancia <= 100:
        errores.append(("ERR_TOLERANCIA_INVALIDA", "La tolerancia debe estar entre 0 y 100."))
    if not 0 <= liquidez <= 100:
        errores.append(("ERR_LIQUIDEZ_INVALIDA", "La liquidez debe estar entre 0 y 100."))
    if not mercado_actualizado:
        errores.append((
            "ERR_DATOS_MERCADO_NO_DISPONIBLES",
            "Confirmá que los datos del escenario sean vigentes antes de ejecutar.",
        ))
    # Las incoherencias entre datos se infieren con reglas del motor (nivel 2).
    errores.extend(derivaciones_de_coherencia(tolerancia, horizonte, objetivo))
    return errores
