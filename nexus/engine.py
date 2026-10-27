from experta import DefFacts, Fact, KnowledgeEngine, MATCH, Rule, TEST

from .matrices import version_activa


class Inversor(Fact):
    pass


class Mercado(Fact):
    pass


class Perfil(Fact):
    pass


class Regimen(Fact):
    pass


class Parametros(Fact):
    """Umbrales de la matriz de decisión vigente (RF-08)."""


MOTIVOS_REGIMEN = {
    "VOLATILIDAD_ALTA": ("R_MERCADO_03", "Se prioriza la cautela ante la volatilidad marcada."),
    "INFLACION_ALTA": ("R_MERCADO_01", "Se identificó un escenario marcado por inflación elevada."),
    "PRESION_CAMBIARIA": ("R_MERCADO_02", "Se identificó presión cambiaria elevada."),
}
SEÑAL_REGIMEN = {
    "VOLATILIDAD_ALTA": "volatilidad",
    "INFLACION_ALTA": "inflacion",
    "PRESION_CAMBIARIA": "cambio",
}


class MotorRoboAdvisor(KnowledgeEngine):
    def __init__(self, matriz=None):
        super().__init__()
        if matriz is None:
            _, matriz = version_activa()
        self.matriz = matriz
        self.auditoria = []

    @DefFacts()
    def parametros_vigentes(self):
        umbrales = self.matriz["umbrales_perfil"]
        yield Parametros(
            conservador_max=umbrales["conservador_tolerancia_max"],
            moderado_max=umbrales["moderado_tolerancia_max"],
        )

    @Rule(
        Inversor(tolerancia=MATCH.tolerancia),
        Parametros(conservador_max=MATCH.cmax),
        TEST(lambda tolerancia, cmax: tolerancia <= cmax),
        salience=10,
    )
    def perfil_conservador(self, cmax):
        self.declare(Perfil(nombre="CONSERVADOR"))
        self.auditoria.append({
            "regla": "R_PERFIL_01",
            "resultado": "CONSERVADOR",
            "motivo": "La tolerancia declarada a pérdidas es nula." if cmax == 0
            else f"La tolerancia declarada a pérdidas es igual o inferior al {cmax}%.",
        })

    @Rule(
        Inversor(tolerancia=MATCH.tolerancia),
        Parametros(conservador_max=MATCH.cmax, moderado_max=MATCH.mmax),
        TEST(lambda tolerancia, cmax, mmax: cmax < tolerancia <= mmax),
        salience=5,
    )
    def perfil_moderado(self, cmax, mmax):
        self.declare(Perfil(nombre="MODERADO"))
        self.auditoria.append({
            "regla": "R_PERFIL_02",
            "resultado": "MODERADO",
            "motivo": f"La pérdida temporal tolerada se encuentra entre {cmax + 1}% y {mmax}%.",
        })

    @Rule(
        Inversor(tolerancia=MATCH.tolerancia),
        Parametros(moderado_max=MATCH.mmax),
        TEST(lambda tolerancia, mmax: tolerancia > mmax),
    )
    def perfil_agresivo(self, mmax):
        self.declare(Perfil(nombre="AGRESIVO"))
        self.auditoria.append({
            "regla": "R_PERFIL_03",
            "resultado": "AGRESIVO",
            "motivo": f"La tolerancia declarada a pérdidas es superior al {mmax}%.",
        })

    @Rule(Mercado(
        inflacion_alta=MATCH.inflacion,
        presion_cambiaria=MATCH.cambio,
        volatilidad_alta=MATCH.volatilidad,
    ))
    def evaluar_regimen(self, inflacion, cambio, volatilidad):
        señales = {"inflacion": inflacion, "cambio": cambio, "volatilidad": volatilidad}
        # El orden de prioridad entre regímenes es configurable (RF-08).
        nombre = next(
            (r for r in self.matriz["prioridad_regimen"] if señales[SEÑAL_REGIMEN[r]]),
            "ESTABLE",
        )
        codigo, motivo = MOTIVOS_REGIMEN.get(
            nombre, ("R_MERCADO_04", "No se marcaron alertas en los indicadores de esta demo.")
        )
        self.declare(Regimen(nombre=nombre))
        self.auditoria.append({
            "regla": codigo,
            "resultado": nombre,
            "motivo": motivo,
        })
