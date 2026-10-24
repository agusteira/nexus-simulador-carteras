from experta import Fact, KnowledgeEngine, MATCH, P, Rule


class Inversor(Fact):
    pass


class Mercado(Fact):
    pass


class Perfil(Fact):
    pass


class Regimen(Fact):
    pass


class MotorRoboAdvisor(KnowledgeEngine):
    def __init__(self):
        super().__init__()
        self.auditoria = []

    @Rule(Inversor(tolerancia=0), salience=10)
    def perfil_conservador(self):
        self.declare(Perfil(nombre="CONSERVADOR"))
        self.auditoria.append({
            "regla": "R_PERFIL_01",
            "resultado": "CONSERVADOR",
            "motivo": "La tolerancia declarada a pérdidas es nula.",
        })

    @Rule(Inversor(tolerancia=P(lambda x: 0 < x <= 10)), salience=5)
    def perfil_moderado(self):
        self.declare(Perfil(nombre="MODERADO"))
        self.auditoria.append({
            "regla": "R_PERFIL_02",
            "resultado": "MODERADO",
            "motivo": "La pérdida temporal tolerada se encuentra entre 1% y 10%.",
        })

    @Rule(Inversor(tolerancia=P(lambda x: x > 10)))
    def perfil_agresivo(self):
        self.declare(Perfil(nombre="AGRESIVO"))
        self.auditoria.append({
            "regla": "R_PERFIL_03",
            "resultado": "AGRESIVO",
            "motivo": "La tolerancia declarada a pérdidas es superior al 10%.",
        })

    @Rule(Mercado(
        inflacion_alta=MATCH.inflacion,
        presion_cambiaria=MATCH.cambio,
        volatilidad_alta=MATCH.volatilidad,
    ))
    def evaluar_regimen(self, inflacion, cambio, volatilidad):
        if volatilidad:
            nombre, codigo = "VOLATILIDAD_ALTA", "R_MERCADO_03"
            motivo = "Se prioriza la cautela ante la volatilidad marcada."
        elif inflacion:
            nombre, codigo = "INFLACION_ALTA", "R_MERCADO_01"
            motivo = "Se identificó un escenario marcado por inflación elevada."
        elif cambio:
            nombre, codigo = "PRESION_CAMBIARIA", "R_MERCADO_02"
            motivo = "Se identificó presión cambiaria elevada."
        else:
            nombre, codigo = "ESTABLE", "R_MERCADO_04"
            motivo = "No se marcaron alertas en los indicadores de esta demo."
        self.declare(Regimen(nombre=nombre))
        self.auditoria.append({
            "regla": codigo,
            "resultado": nombre,
            "motivo": motivo,
        })
