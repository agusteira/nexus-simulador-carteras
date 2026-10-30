from .matrices import version_activa
from .instrument_rules import load_policy


def construir_cartera(perfil, regimen, liquidez_minima, matriz=None, *, horizonte=None, objetivo=None, auditoria=None):
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

    # Educational suitability caps: preserve matrix v1 and move only capped
    # equity allocation to immediate liquidity.
    policy = load_policy()
    limites = []
    if horizonte is not None:
        caps = policy["equity_caps"]["horizon_months"]
        if horizonte < 12: limites.append((caps["under_12"], "horizonte menor a 12 meses"))
        elif horizonte < 36: limites.append((caps["12_to_35"], "horizonte entre 12 y 35 meses"))
    objective_caps = policy["equity_caps"]["objectives"]
    if objetivo in objective_caps and objective_caps[objetivo] is not None:
        limites.append((objective_caps[objetivo], "objetivo de preservación" if objetivo == "Preservacion" else f"objetivo {objetivo}"))
    for tope, motivo in limites:
        antes = cartera.get("Renta variable", 0)
        excedente = max(0, antes - tope)
        if excedente:
            cartera["Renta variable"] -= excedente
            cartera["Liquidez inmediata"] += excedente
            if auditoria is not None:
                auditoria.append({"regla": "R_ASIGNACION_HORIZONTE" if "horizonte" in motivo else "R_ASIGNACION_OBJETIVO",
                                 "mensaje": f"Tope educativo de renta variable aplicado por {motivo}: {antes}% a {cartera['Renta variable']}%.",
                                 "antes": antes, "despues": cartera["Renta variable"], "motivo": motivo})

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
