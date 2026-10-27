from .matrices import version_activa


def construir_cartera(perfil, regimen, liquidez_minima, matriz=None):
    """Arma la cartera con la matriz indicada o, si no se pasa, la versión activa (RF-08)."""
    if matriz is None:
        _, matriz = version_activa()
    cartera = dict(matriz["carteras_base"][perfil])

    ajuste = matriz["ajustes_regimen"].get(regimen)
    if ajuste and ajuste.get("activo", True):
        mover = min(ajuste["puntos"], cartera[ajuste["desde"]])
        cartera[ajuste["desde"]] -= mover
        cartera[ajuste["hacia"]] += mover

    # Topes por clase de activo: el excedente pasa a liquidez inmediata.
    for categoria, tope in matriz.get("topes_clase", {}).get(perfil, {}).items():
        excedente = max(0, cartera[categoria] - tope)
        cartera[categoria] -= excedente
        cartera["Liquidez inmediata"] += excedente

    faltante = max(0, liquidez_minima - cartera["Liquidez inmediata"])
    for categoria in matriz["orden_retiro_liquidez"]:
        retiro = min(cartera[categoria], faltante)
        cartera[categoria] -= retiro
        cartera["Liquidez inmediata"] += retiro
        faltante -= retiro
        if faltante == 0:
            break

    if any(not isinstance(valor, int) or valor < 0 for valor in cartera.values()):
        raise ValueError("La asignación contiene valores inválidos.")
    if sum(cartera.values()) != 100:
        raise ValueError("La asignación no totaliza 100%.")
    if cartera["Liquidez inmediata"] < liquidez_minima:
        raise ValueError(
            "No se puede satisfacer el mínimo de liquidez con las reglas actuales."
        )
    return cartera
