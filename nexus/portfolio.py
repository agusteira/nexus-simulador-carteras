def construir_cartera(perfil, regimen, liquidez_minima):
    bases = {
        "CONSERVADOR": {
            "Renta fija inflación": 60,
            "Renta fija cambiaria": 20,
            "Renta variable": 0,
            "Liquidez inmediata": 20,
        },
        "MODERADO": {
            "Renta fija inflación": 40,
            "Renta fija cambiaria": 20,
            "Renta variable": 20,
            "Liquidez inmediata": 20,
        },
        "AGRESIVO": {
            "Renta fija inflación": 20,
            "Renta fija cambiaria": 15,
            "Renta variable": 45,
            "Liquidez inmediata": 20,
        },
    }
    cartera = bases[perfil].copy()

    if regimen == "INFLACION_ALTA":
        mover = min(10, cartera["Liquidez inmediata"])
        cartera["Liquidez inmediata"] -= mover
        cartera["Renta fija inflación"] += mover
    elif regimen == "PRESION_CAMBIARIA":
        mover = min(10, cartera["Liquidez inmediata"])
        cartera["Liquidez inmediata"] -= mover
        cartera["Renta fija cambiaria"] += mover
    elif regimen == "VOLATILIDAD_ALTA":
        mover = cartera["Renta variable"]
        cartera["Renta variable"] = 0
        cartera["Liquidez inmediata"] += mover

    faltante = max(0, liquidez_minima - cartera["Liquidez inmediata"])
    for categoria in ("Renta variable", "Renta fija cambiaria", "Renta fija inflación"):
        retiro = min(cartera[categoria], faltante)
        cartera[categoria] -= retiro
        cartera["Liquidez inmediata"] += retiro
        faltante -= retiro
        if faltante == 0:
            break

    if perfil == "CONSERVADOR":
        cartera["Renta variable"] = 0

    if any(not isinstance(valor, int) or valor < 0 for valor in cartera.values()):
        raise ValueError("La asignación contiene valores inválidos.")
    if sum(cartera.values()) != 100:
        raise ValueError("La asignación no totaliza 100%.")
    if cartera["Liquidez inmediata"] < liquidez_minima:
        raise ValueError(
            "No se puede satisfacer el mínimo de liquidez con las reglas actuales."
        )
    return cartera
