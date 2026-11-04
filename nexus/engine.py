"""Motor experto de NEXUS (Experta, encadenamiento hacia adelante).

Cada nivel consume hechos derivados por el anterior, junto con entradas y parámetros
cuando la regla los requiere; los nuevos hechos habilitan el encadenamiento hacia adelante.
  N1: clasifica idoneidad, señales de mercado, horizonte, objetivo y tolerancia nula.
  N2: elige el régimen dominante, obtiene la cartera base y detecta inconsistencias.
  N3: ajusta tácticamente la cartera base según el régimen y la matriz vigente.
  N4: limita la exposición por clase de activo según el perfil.
  N5: aplica el tope de renta variable correspondiente al horizonte.
  N6: aplica el tope de renta variable correspondiente al objetivo.
  N7: procura alcanzar la liquidez inmediata mínima solicitada.
  N8: valida la distribución final o declara un fallo de asignación.
  N9: traduce clases a familias de instrumentos y declara la conclusión final.
"""
from experta import DefFacts, Fact, KnowledgeEngine, MATCH, NOT, P, Rule, TEST

from .instrument_rules import load_policy
from .matrices import version_activa


# ---------------------------------------------------------------- hechos
class Inversor(Fact):
    """Entrada: tolerancia, horizonte, objetivo, liquidez (todas opcionales)."""


class Mercado(Fact):
    """Entrada: inflacion_alta, presion_cambiaria, volatilidad_alta (bool)."""


class Parametros(Fact):
    """Entrada (DefFacts): umbrales y políticas vigentes (RF-08)."""


class Perfil(Fact):
    """N1: nombre in {CONSERVADOR, MODERADO, AGRESIVO}."""


class SenalMercado(Fact):
    """N1: nombre (régimen o ESTABLE) y rango (posición en prioridad_regimen; 99 = ESTABLE)."""


class HorizonteClase(Fact):
    """N1: tramo in {CORTO, MEDIANO, LARGO, NO_INFORMADO}; meses (int o None)."""


class ObjetivoClase(Fact):
    """N1: nombre = objetivo declarado (str o None)."""


class ToleranciaNula(Fact):
    """N1: el inversor declaró 0% de tolerancia a pérdidas."""


class Regimen(Fact):
    """N2: nombre in {VOLATILIDAD_ALTA, INFLACION_ALTA, PRESION_CAMBIARIA, ESTABLE}."""


class Derivacion(Fact):
    """N2: codigo, mensaje, orden (int, para ordenar errores)."""


class Cartera(Fact):
    """N2..N7: etapa y valores = tupla ordenada de (categoria, porcentaje)."""


class CarteraFinal(Fact):
    """N8: valores = tupla ordenada de (categoria, porcentaje) validada."""


class FalloAsignacion(Fact):
    """N8: mensaje (texto del ValueError de construir_cartera)."""


class TipoInstrumento(Fact):
    """N9: categoria, tipo (familia de instrumentos del brief), porcentaje."""


class Conclusion(Fact):
    """N9: estado in {RECOMENDACION_EXITOSA, ASIGNACION_INVIABLE}."""


MOTIVOS_REGIMEN = {
    "VOLATILIDAD_ALTA": ("R_MERCADO_03", "Se prioriza la cautela ante la volatilidad marcada."),
    "INFLACION_ALTA": ("R_MERCADO_01", "Se identificó un escenario marcado por inflación elevada."),
    "PRESION_CAMBIARIA": ("R_MERCADO_02", "Se identificó presión cambiaria elevada."),
    "ESTABLE": ("R_MERCADO_04", "No se marcaron alertas en los indicadores de esta demo."),
}
SEÑAL_REGIMEN = {
    "VOLATILIDAD_ALTA": "volatilidad",
    "INFLACION_ALTA": "inflacion",
    "PRESION_CAMBIARIA": "cambio",
}
TIPOS_INSTRUMENTO = {
    "Renta fija inflación": "Bonos CER / Letras del Tesoro",
    "Renta fija cambiaria": "Obligaciones Negociables Hard Dollar",
    "Renta variable": "CEDEARs / Acciones locales",
    "Liquidez inmediata": "FCI Money Market",
}
PERFILES_ANTES_QUE_REGIMEN = ("CONSERVADOR", "MODERADO")
MSG_VALORES = "La asignación contiene valores inválidos."
MSG_SUMA = "La asignación no totaliza 100%."
MSG_LIQUIDEZ = "No se puede satisfacer el mínimo de liquidez con las reglas actuales."
MSG_TOL_CRECIMIENTO = "Tolerancia nula a pérdidas y objetivo de crecimiento requieren revisión manual."
MSG_HORIZONTE_CRECIMIENTO = ("Un horizonte menor a 6 meses no es compatible con un objetivo de "
                             "crecimiento; la consulta requiere revisión manual.")


def _es_entero(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _a_dict(valores):
    return {categoria: porcentaje for categoria, porcentaje in valores}


def _a_tupla(cartera):
    return tuple((categoria, porcentaje) for categoria, porcentaje in cartera.items())


class MotorRoboAdvisor(KnowledgeEngine):
    def __init__(self, matriz=None, politica=None):
        super().__init__()
        if matriz is None:
            _, matriz = version_activa()
        self.matriz = matriz
        self.politica = politica if politica is not None else load_policy()
        self.traza_reglas = []
        self._entrada_perfil = None
        self._entrada_regimen = None
        self._entradas_asignacion = []

    # ----------------------------------------------------- traza
    @property
    def auditoria(self):
        """Traza con el mismo contenido y orden que expone service.evaluar."""
        base = []
        if self._entrada_perfil and self._entrada_regimen:
            if self._entrada_perfil["resultado"] in PERFILES_ANTES_QUE_REGIMEN:
                base = [self._entrada_perfil, self._entrada_regimen]
            else:
                base = [self._entrada_regimen, self._entrada_perfil]
        else:
            base = [e for e in (self._entrada_perfil, self._entrada_regimen) if e]
        return base + list(self._entradas_asignacion)

    def _registrar(self, regla, codigo, nivel, conclusion):
        self.traza_reglas.append({
            "orden": len(self.traza_reglas) + 1,
            "regla": regla,
            "codigo": codigo,
            "nivel": nivel,
            "conclusion": conclusion,
        })

    def _siguiente(self, etapa, cartera, regla, codigo, nivel):
        self.declare(Cartera(etapa=etapa, valores=_a_tupla(cartera)))
        self._registrar(regla, codigo, nivel, f"Cartera {etapa}: {cartera}")

    @DefFacts()
    def parametros_vigentes(self):
        umbrales = self.matriz["umbrales_perfil"]
        caps = self.politica["equity_caps"]
        yield Parametros(
            conservador_max=umbrales["conservador_tolerancia_max"],
            moderado_max=umbrales["moderado_tolerancia_max"],
            prioridad=tuple(self.matriz["prioridad_regimen"]),
            ajustes_activos=tuple(
                r for r, a in self.matriz["ajustes_regimen"].items() if a.get("activo", True)
            ),
            tope_rv_horizonte_corto=caps["horizon_months"]["under_12"],
            tope_rv_horizonte_mediano=caps["horizon_months"]["12_to_35"],
            objetivos_con_tope=tuple(
                o for o, t in caps["objectives"].items() if t is not None
            ),
        )

    # ================================================= NIVEL 1
    # Clasifica la idoneidad por tolerancia a pérdidas y reconoce señales declaradas.
    # Parte de Inversor, Mercado y Parametros; deriva horizonte, objetivo y tolerancia nula.
    @Rule(Inversor(tolerancia=MATCH.tolerancia), Parametros(conservador_max=MATCH.cmax),
          TEST(lambda tolerancia, cmax: tolerancia <= cmax), salience=10)
    def perfil_conservador(self, cmax):
        """Clasifica la idoneidad del inversor hasta el umbral conservador configurado.
        RF-03 y RF-08: ajustar el riesgo al perfil con umbrales vigentes.
        Consume Inversor + Parametros; declara Perfil (N1).
        """
        self.declare(Perfil(nombre="CONSERVADOR"))
        self._entrada_perfil = {
            "regla": "R_PERFIL_01", "resultado": "CONSERVADOR",
            "motivo": "La tolerancia declarada a pérdidas es nula." if cmax == 0
            else f"La tolerancia declarada a pérdidas es igual o inferior al {cmax}%.",
        }
        self._registrar("perfil_conservador", "R_PERFIL_01", 1, "Perfil CONSERVADOR")

    @Rule(Inversor(tolerancia=MATCH.tolerancia),
          Parametros(conservador_max=MATCH.cmax, moderado_max=MATCH.mmax),
          TEST(lambda tolerancia, cmax, mmax: cmax < tolerancia <= mmax), salience=10)
    def perfil_moderado(self, cmax, mmax):
        """Clasifica la idoneidad del inversor entre los umbrales conservador y moderado configurado.
        RF-03 y RF-08: ajustar el riesgo al perfil con umbrales vigentes.
        Consume Inversor + Parametros; declara Perfil (N1).
        """
        self.declare(Perfil(nombre="MODERADO"))
        self._entrada_perfil = {
            "regla": "R_PERFIL_02", "resultado": "MODERADO",
            "motivo": f"La pérdida temporal tolerada se encuentra entre {cmax + 1}% y {mmax}%.",
        }
        self._registrar("perfil_moderado", "R_PERFIL_02", 1, "Perfil MODERADO")

    @Rule(Inversor(tolerancia=MATCH.tolerancia), Parametros(moderado_max=MATCH.mmax),
          TEST(lambda tolerancia, mmax: tolerancia > mmax), salience=10)
    def perfil_agresivo(self, mmax):
        """Clasifica la idoneidad del inversor por encima del umbral moderado configurado.
        RF-03 y RF-08: ajustar el riesgo al perfil con umbrales vigentes.
        Consume Inversor + Parametros; declara Perfil (N1).
        """
        self.declare(Perfil(nombre="AGRESIVO"))
        self._entrada_perfil = {
            "regla": "R_PERFIL_03", "resultado": "AGRESIVO",
            "motivo": f"La tolerancia declarada a pérdidas es superior al {mmax}%.",
        }
        self._registrar("perfil_agresivo", "R_PERFIL_03", 1, "Perfil AGRESIVO")

    def _senal(self, regimen, prioridad, regla, codigo):
        rango = list(prioridad).index(regimen)
        self.declare(SenalMercado(nombre=regimen, rango=rango))
        self._registrar(regla, codigo, 1, f"Señal {regimen} (prioridad {rango + 1})")

    @Rule(Mercado(volatilidad_alta=True), Parametros(prioridad=MATCH.prioridad), salience=9)
    def senal_volatilidad(self, prioridad):
        """Reconoce la señal de volatilidad elevada declarada por el usuario.
        RF-02 y RF-04: incorporar el escenario a la asignación táctica.
        Consume Mercado + Parametros; declara SenalMercado (N1).
        """
        self._senal("VOLATILIDAD_ALTA", prioridad, "senal_volatilidad", "R_SENAL_VOLATILIDAD")

    @Rule(Mercado(inflacion_alta=True), Parametros(prioridad=MATCH.prioridad), salience=9)
    def senal_inflacion(self, prioridad):
        """Reconoce la señal de inflación elevada declarada por el usuario.
        RF-02 y RF-04: incorporar el escenario a la asignación táctica.
        Consume Mercado + Parametros; declara SenalMercado (N1).
        """
        self._senal("INFLACION_ALTA", prioridad, "senal_inflacion", "R_SENAL_INFLACION")

    @Rule(Mercado(presion_cambiaria=True), Parametros(prioridad=MATCH.prioridad), salience=9)
    def senal_presion_cambiaria(self, prioridad):
        """Reconoce la señal de presión cambiaria declarada por el usuario.
        RF-02 y RF-04: incorporar el escenario a la asignación táctica.
        Consume Mercado + Parametros; declara SenalMercado (N1).
        """
        self._senal("PRESION_CAMBIARIA", prioridad, "senal_presion_cambiaria", "R_SENAL_CAMBIARIA")

    @Rule(Mercado(volatilidad_alta=False, inflacion_alta=False, presion_cambiaria=False), salience=9)
    def sin_senales(self):
        """Reconoce un escenario sin alertas declaradas de mercado.
        RF-02 y RF-04: considerar el escenario estable en la asignación.
        Consume Mercado; declara SenalMercado ESTABLE (N1).
        """
        self.declare(SenalMercado(nombre="ESTABLE", rango=99))
        self._registrar("sin_senales", "R_SENAL_NINGUNA", 1, "Sin alertas de mercado")

    @Rule(Inversor(horizonte=MATCH.horizonte & P(lambda h: _es_entero(h) and h < 12)), salience=9)
    def horizonte_corto(self, horizonte):
        """Clasifica el horizonte menor a 12 meses según los tramos del código.
        RF-01 y RF-03: usar el plazo para evaluar la idoneidad.
        Consume Inversor; declara HorizonteClase (N1).
        """
        self._horizonte(horizonte, "CORTO", "horizonte_corto", "R_HORIZONTE_CORTO")

    @Rule(Inversor(horizonte=MATCH.horizonte & P(lambda h: _es_entero(h) and 12 <= h < 36)), salience=9)
    def horizonte_mediano(self, horizonte):
        """Clasifica el horizonte entre 12 y 35 meses según los tramos del código.
        RF-01 y RF-03: usar el plazo para evaluar la idoneidad.
        Consume Inversor; declara HorizonteClase (N1).
        """
        self._horizonte(horizonte, "MEDIANO", "horizonte_mediano", "R_HORIZONTE_MEDIANO")

    @Rule(Inversor(horizonte=MATCH.horizonte & P(lambda h: _es_entero(h) and h >= 36)), salience=9)
    def horizonte_largo(self, horizonte):
        """Clasifica el horizonte de al menos 36 meses según los tramos del código.
        RF-01 y RF-03: usar el plazo para evaluar la idoneidad.
        Consume Inversor; declara HorizonteClase (N1).
        """
        self._horizonte(horizonte, "LARGO", "horizonte_largo", "R_HORIZONTE_LARGO")

    @Rule(Inversor(horizonte=MATCH.horizonte & P(lambda h: not _es_entero(h))), salience=9)
    def horizonte_no_informado(self, horizonte):
        """Clasifica el horizonte sin plazo entero informado según los tramos del código.
        RF-01 y RF-03: usar el plazo para evaluar la idoneidad.
        Consume Inversor; declara HorizonteClase (N1).
        """
        self._horizonte(horizonte, "NO_INFORMADO", "horizonte_no_informado", "R_HORIZONTE_NO_INFORMADO")

    def _horizonte(self, meses, tramo, regla, codigo):
        self.declare(HorizonteClase(tramo=tramo, meses=meses if _es_entero(meses) else None))
        self._registrar(regla, codigo, 1, f"Horizonte {tramo}")

    @Rule(Inversor(objetivo=MATCH.objetivo), salience=9)
    def clasificar_objetivo(self, objetivo):
        """Identifica el propósito financiero declarado para el capital.
        RF-01 y RF-03: incorporar el objetivo a los límites de idoneidad.
        Consume Inversor; declara ObjetivoClase (N1).
        """
        self.declare(ObjetivoClase(nombre=objetivo))
        self._registrar("clasificar_objetivo", "R_OBJETIVO", 1, f"Objetivo {objetivo}")

    @Rule(Inversor(tolerancia=P(lambda t: t == 0)), salience=9)
    def tolerancia_nula(self):
        """Identifica la aversión total a pérdidas del inversor.
        RF-03 y RF-07: proteger la idoneidad y detectar contradicciones.
        Consume Inversor; declara ToleranciaNula (N1).
        """
        self.declare(ToleranciaNula())
        self._registrar("tolerancia_nula", "R_TOLERANCIA_NULA", 1, "Tolerancia nula")

    # ================================================= NIVEL 2
    # Usa los hechos N1 para elegir el régimen según la prioridad y obtener la base del perfil.
    # Detecta tolerancia 0 + Crecimiento y horizonte < 6 meses + Crecimiento (RF-07).
    def _regimen(self, nombre, regla):
        codigo, motivo = MOTIVOS_REGIMEN[nombre]
        self.declare(Regimen(nombre=nombre))
        self._entrada_regimen = {"regla": codigo, "resultado": nombre, "motivo": motivo}
        self._registrar(regla, codigo, 2, f"Régimen {nombre}")

    @Rule(SenalMercado(rango=0, nombre=MATCH.nombre), salience=8)
    def regimen_prioridad_1(self, nombre):
        """Elige como régimen dominante la primera señal de la prioridad configurada.
        RF-04 y RF-08: resolver señales concurrentes con la prioridad vigente.
        Consume SenalMercado (N1); declara Regimen (N2).
        """
        self._regimen(nombre, "regimen_prioridad_1")

    @Rule(SenalMercado(rango=1, nombre=MATCH.nombre), NOT(SenalMercado(rango=0)), salience=8)
    def regimen_prioridad_2(self, nombre):
        """Elige como régimen dominante la segunda señal si falta la primera.
        RF-04 y RF-08: resolver señales concurrentes con la prioridad vigente.
        Consume SenalMercado (N1); declara Regimen (N2).
        """
        self._regimen(nombre, "regimen_prioridad_2")

    @Rule(SenalMercado(rango=2, nombre=MATCH.nombre), NOT(SenalMercado(rango=0)),
          NOT(SenalMercado(rango=1)), salience=8)
    def regimen_prioridad_3(self, nombre):
        """Elige como régimen dominante la tercera señal si faltan las dos anteriores.
        RF-04 y RF-08: resolver señales concurrentes con la prioridad vigente.
        Consume SenalMercado (N1); declara Regimen (N2).
        """
        self._regimen(nombre, "regimen_prioridad_3")

    @Rule(SenalMercado(nombre="ESTABLE"), salience=8)
    def regimen_estable(self):
        """Adopta el régimen estable cuando no hay alertas de mercado.
        RF-04: combinar el perfil con el escenario para ponderar la cartera.
        Consume SenalMercado ESTABLE (N1); declara Regimen (N2).
        """
        self._regimen("ESTABLE", "regimen_estable")

    @Rule(Perfil(nombre=MATCH.perfil), salience=8)
    def cartera_base(self, perfil):
        """Asigna la distribución estratégica inicial del perfil según la matriz vigente.
        RF-04 y RF-08: obtener ponderaciones desde la matriz administrable.
        Consume Perfil (N1); declara Cartera BASE (N2).
        """
        self._siguiente("BASE", dict(self.matriz["carteras_base"][perfil]),
                        "cartera_base", "R_CARTERA_BASE", 2)

    @Rule(ToleranciaNula(), ObjetivoClase(nombre="Crecimiento"), salience=8)
    def derivar_tolerancia_nula_crecimiento(self):
        """Deriva a revisión la contradicción entre tolerancia nula y crecimiento.
        RF-07: resolver inconsistencias mediante revisión personalizada.
        Consume ToleranciaNula + ObjetivoClase (N1); declara Derivacion (N2).
        """
        self.declare(Derivacion(codigo="ERR_INCONSISTENCIA_PERFIL_HORIZONTE",
                                mensaje=MSG_TOL_CRECIMIENTO, orden=10))
        self._registrar("derivar_tolerancia_nula_crecimiento", "ERR_INCONSISTENCIA_PERFIL_HORIZONTE", 2,
                        "Derivación: tolerancia nula + crecimiento")

    @Rule(HorizonteClase(meses=P(lambda m: _es_entero(m) and 0 < m < 6)),
          ObjetivoClase(nombre="Crecimiento"), salience=8)
    def derivar_horizonte_corto_crecimiento(self):
        """Deriva a revisión crecimiento con horizonte positivo menor a 6 meses.
        RF-07: tratar las discrepancias de horizonte sin emitir una cartera arbitraria.
        Consume HorizonteClase + ObjetivoClase (N1); declara Derivacion (N2).
        """
        self.declare(Derivacion(codigo="ERR_HORIZONTE_CORTO_CRECIMIENTO",
                                mensaje=MSG_HORIZONTE_CRECIMIENTO, orden=20))
        self._registrar("derivar_horizonte_corto_crecimiento", "ERR_HORIZONTE_CORTO_CRECIMIENTO", 2,
                        "Derivación: horizonte < 6 meses + crecimiento")

    # ================================================= NIVEL 3
    # Combina la cartera base y el régimen N2 con los ajustes habilitados (RF-04, RF-08).
    # Inflación favorece CER; presión cambiaria, dólares; volatilidad reduce renta variable.
    def _ajustar(self, valores, regimen, regla, codigo):
        cartera = _a_dict(valores)
        ajuste = self.matriz["ajustes_regimen"][regimen]
        mover = min(ajuste["puntos"], cartera[ajuste["desde"]])
        cartera[ajuste["desde"]] -= mover
        cartera[ajuste["hacia"]] += mover
        self._siguiente("AJUSTADA_REGIMEN", cartera, regla, codigo, 3)

    @Rule(Cartera(etapa="BASE", valores=MATCH.valores), Regimen(nombre="INFLACION_ALTA"),
          Parametros(ajustes_activos=MATCH.activos),
          TEST(lambda activos: "INFLACION_ALTA" in activos), salience=7)
    def ajustar_por_inflacion(self, valores):
        """Favorece la cobertura CER frente a inflación según el ajuste vigente.
        RF-04 y RF-08: adaptar tácticamente la cartera al régimen dominante.
        Consume Cartera BASE + Regimen (N2) + Parametros; declara Cartera AJUSTADA_REGIMEN (N3).
        """
        self._ajustar(valores, "INFLACION_ALTA", "ajustar_por_inflacion", "R_AJUSTE_INFLACION")

    @Rule(Cartera(etapa="BASE", valores=MATCH.valores), Regimen(nombre="PRESION_CAMBIARIA"),
          Parametros(ajustes_activos=MATCH.activos),
          TEST(lambda activos: "PRESION_CAMBIARIA" in activos), salience=7)
    def ajustar_por_presion_cambiaria(self, valores):
        """Favorece la cobertura en dólares ante presión cambiaria según el ajuste vigente.
        RF-04 y RF-08: adaptar tácticamente la cartera al régimen dominante.
        Consume Cartera BASE + Regimen (N2) + Parametros; declara Cartera AJUSTADA_REGIMEN (N3).
        """
        self._ajustar(valores, "PRESION_CAMBIARIA", "ajustar_por_presion_cambiaria", "R_AJUSTE_CAMBIARIA")

    @Rule(Cartera(etapa="BASE", valores=MATCH.valores), Regimen(nombre="VOLATILIDAD_ALTA"),
          Parametros(ajustes_activos=MATCH.activos),
          TEST(lambda activos: "VOLATILIDAD_ALTA" in activos), salience=7)
    def ajustar_por_volatilidad(self, valores):
        """Reduce renta variable en favor de liquidez ante volatilidad según el ajuste vigente.
        RF-04 y RF-08: adaptar tácticamente la cartera al régimen dominante.
        Consume Cartera BASE + Regimen (N2) + Parametros; declara Cartera AJUSTADA_REGIMEN (N3).
        """
        self._ajustar(valores, "VOLATILIDAD_ALTA", "ajustar_por_volatilidad", "R_AJUSTE_VOLATILIDAD")

    @Rule(Cartera(etapa="BASE", valores=MATCH.valores), Regimen(nombre=MATCH.regimen),
          Parametros(ajustes_activos=MATCH.activos),
          TEST(lambda regimen, activos: regimen not in activos), salience=7)
    def sin_ajuste_regimen(self, valores):
        """Conserva la distribución base cuando el régimen no tiene ajuste activo.
        RF-04 y RF-08: respetar los ajustes habilitados en la matriz.
        Consume Cartera BASE + Regimen (N2) + Parametros; declara Cartera AJUSTADA_REGIMEN (N3).
        """
        self._siguiente("AJUSTADA_REGIMEN", _a_dict(valores), "sin_ajuste_regimen", "R_AJUSTE_NINGUNO", 3)

    # ================================================= NIVEL 4
    # Limita la cartera ajustada N3 según los topes por clase del perfil (RF-03).
    # Traslada los excedentes a liquidez y declara la cartera con topes aplicados.
    @Rule(Cartera(etapa="AJUSTADA_REGIMEN", valores=MATCH.valores), Perfil(nombre=MATCH.perfil), salience=6)
    def aplicar_topes_clase(self, valores, perfil):
        """Limita cada clase por perfil y destina el excedente a liquidez inmediata.
        RF-03: el perfil conservador no admite renta variable; RF-08: topes configurables.
        Consume Cartera AJUSTADA_REGIMEN (N3) + Perfil; declara Cartera TOPES_CLASE (N4).
        """
        cartera = _a_dict(valores)
        for categoria, tope in self.matriz.get("topes_clase", {}).get(perfil, {}).items():
            excedente = max(0, cartera[categoria] - tope)
            cartera[categoria] -= excedente
            cartera["Liquidez inmediata"] += excedente
        self._siguiente("TOPES_CLASE", cartera, "aplicar_topes_clase", "R_TOPES_CLASE", 4)

    # ================================================= NIVEL 5
    # Toma la cartera N4 y el tramo de horizonte N1 para limitar renta variable (RF-03).
    # El excedente pasa a liquidez; horizontes largos o no informados no agregan tope.
    def _tope_rv(self, valores, tope, motivo, codigo_auditoria):
        cartera = _a_dict(valores)
        if tope is None:
            return cartera
        antes = cartera.get("Renta variable", 0)
        excedente = max(0, antes - tope)
        if excedente:
            cartera["Renta variable"] -= excedente
            cartera["Liquidez inmediata"] += excedente
            self._entradas_asignacion.append({
                "regla": codigo_auditoria,
                "mensaje": f"Tope educativo de renta variable aplicado por {motivo}: {antes}% a {cartera['Renta variable']}%.",
                "antes": antes, "despues": cartera["Renta variable"], "motivo": motivo,
            })
        return cartera

    @Rule(Cartera(etapa="TOPES_CLASE", valores=MATCH.valores), HorizonteClase(tramo="CORTO"),
          Parametros(tope_rv_horizonte_corto=MATCH.tope), salience=5)
    def tope_horizonte_corto(self, valores, tope):
        """Aplica el tope configurado de renta variable para el horizonte corto.
        RF-03 y sección 2: limitar la exposición según el plazo de inversión.
        Consume Cartera TOPES_CLASE (N4) + HorizonteClase + Parametros; declara Cartera TOPE_HORIZONTE (N5).
        """
        cartera = self._tope_rv(valores, tope, "horizonte menor a 12 meses", "R_ASIGNACION_HORIZONTE")
        self._siguiente("TOPE_HORIZONTE", cartera, "tope_horizonte_corto", "R_ASIGNACION_HORIZONTE", 5)

    @Rule(Cartera(etapa="TOPES_CLASE", valores=MATCH.valores), HorizonteClase(tramo="MEDIANO"),
          Parametros(tope_rv_horizonte_mediano=MATCH.tope), salience=5)
    def tope_horizonte_mediano(self, valores, tope):
        """Aplica el tope configurado de renta variable para el horizonte mediano.
        RF-03 y sección 2: limitar la exposición según el plazo de inversión.
        Consume Cartera TOPES_CLASE (N4) + HorizonteClase + Parametros; declara Cartera TOPE_HORIZONTE (N5).
        """
        cartera = self._tope_rv(valores, tope, "horizonte entre 12 y 35 meses", "R_ASIGNACION_HORIZONTE")
        self._siguiente("TOPE_HORIZONTE", cartera, "tope_horizonte_mediano", "R_ASIGNACION_HORIZONTE", 5)

    @Rule(Cartera(etapa="TOPES_CLASE", valores=MATCH.valores),
          HorizonteClase(tramo=P(lambda t: t in ("LARGO", "NO_INFORMADO"))), salience=5)
    def sin_tope_horizonte(self, valores):
        """Conserva la cartera sin tope adicional por horizonte largo o no informado.
        RF-03 y sección 2: aplicar los límites temporales previstos por la política del código.
        Consume Cartera TOPES_CLASE (N4) + HorizonteClase; declara Cartera TOPE_HORIZONTE (N5).
        """
        self._siguiente("TOPE_HORIZONTE", _a_dict(valores), "sin_tope_horizonte", "R_HORIZONTE_SIN_TOPE", 5)

    # ================================================= NIVEL 6
    # Toma la cartera N5 y el objetivo N1 para aplicar el tope configurado (RF-03).
    # Conserva la distribución si no hay tope; destina los excedentes a liquidez.
    @Rule(Cartera(etapa="TOPE_HORIZONTE", valores=MATCH.valores), ObjetivoClase(nombre=MATCH.objetivo),
          Parametros(objetivos_con_tope=MATCH.con_tope),
          TEST(lambda objetivo, con_tope: objetivo in con_tope), salience=4)
    def tope_objetivo(self, valores, objetivo):
        """Limita renta variable al tope configurado para el objetivo financiero.
        RF-01 y RF-03: adecuar la exposición al propósito del inversor.
        Consume Cartera TOPE_HORIZONTE (N5) + ObjetivoClase + Parametros; declara Cartera TOPE_OBJETIVO (N6).
        """
        tope = self.politica["equity_caps"]["objectives"][objetivo]
        motivo = "objetivo de preservación" if objetivo == "Preservacion" else f"objetivo {objetivo}"
        cartera = self._tope_rv(valores, tope, motivo, "R_ASIGNACION_OBJETIVO")
        self._siguiente("TOPE_OBJETIVO", cartera, "tope_objetivo", "R_ASIGNACION_OBJETIVO", 6)

    @Rule(Cartera(etapa="TOPE_HORIZONTE", valores=MATCH.valores), ObjetivoClase(nombre=MATCH.objetivo),
          Parametros(objetivos_con_tope=MATCH.con_tope),
          TEST(lambda objetivo, con_tope: objetivo not in con_tope), salience=4)
    def sin_tope_objetivo(self, valores):
        """Conserva la distribución si el objetivo no tiene un tope configurado.
        RF-01 y RF-03: adecuar la exposición al propósito del inversor.
        Consume Cartera TOPE_HORIZONTE (N5) + ObjetivoClase + Parametros; declara Cartera TOPE_OBJETIVO (N6).
        """
        self._siguiente("TOPE_OBJETIVO", _a_dict(valores), "sin_tope_objetivo", "R_OBJETIVO_SIN_TOPE", 6)

    # ================================================= NIVEL 7
    # Toma la cartera N6 y la liquidez pedida por el inversor (sección 6 del brief).
    # Retira de otras clases en el orden vigente para alcanzar ese mínimo.
    @Rule(Cartera(etapa="TOPE_OBJETIVO", valores=MATCH.valores), Inversor(liquidez=MATCH.liquidez), salience=3)
    def asegurar_liquidez_minima(self, valores, liquidez):
        """Eleva la liquidez al mínimo solicitado retirando de otras clases en el orden vigente.
        RF-01 y sección 6: respetar la necesidad de disponibilidad inmediata del capital.
        Consume Cartera TOPE_OBJETIVO (N6) + Inversor; declara Cartera LIQUIDEZ_MINIMA (N7).
        """
        cartera = _a_dict(valores)
        faltante = max(0, liquidez - cartera["Liquidez inmediata"])
        for categoria in self.matriz["orden_retiro_liquidez"]:
            retiro = min(cartera[categoria], faltante)
            cartera[categoria] -= retiro
            cartera["Liquidez inmediata"] += retiro
            faltante -= retiro
            if faltante == 0:
                break
        self._siguiente("LIQUIDEZ_MINIMA", cartera, "asegurar_liquidez_minima", "R_LIQUIDEZ_MINIMA", 7)

    # ================================================= NIVEL 8
    # Revisa la cartera N7: porcentajes enteros no negativos, suma 100 y liquidez alcanzada.
    # Declara CarteraFinal o FalloAsignacion con un mensaje de rechazo (RF-04).
    @Rule(Cartera(etapa="LIQUIDEZ_MINIMA", valores=MATCH.valores),
          TEST(lambda valores: any(not _es_entero(v) or v < 0 for _, v in valores)), salience=2)
    def rechazar_valores_invalidos(self):
        """Rechaza ponderaciones negativas o no enteras.
        RF-04 y sección 7: emitir sólo asignaciones consistentes con las restricciones.
        Consume Cartera LIQUIDEZ_MINIMA (N7); declara FalloAsignacion (N8).
        """
        self._fallo(MSG_VALORES, "rechazar_valores_invalidos", "R_VALIDACION_VALORES")

    @Rule(Cartera(etapa="LIQUIDEZ_MINIMA", valores=MATCH.valores),
          TEST(lambda valores: all(_es_entero(v) and v >= 0 for _, v in valores)),
          TEST(lambda valores: sum(v for _, v in valores) != 100), salience=2)
    def rechazar_suma_distinta_de_100(self):
        """Rechaza una distribución que no totaliza el 100% del capital.
        RF-04 y sección 7: emitir sólo asignaciones consistentes con las restricciones.
        Consume Cartera LIQUIDEZ_MINIMA (N7); declara FalloAsignacion (N8).
        """
        self._fallo(MSG_SUMA, "rechazar_suma_distinta_de_100", "R_VALIDACION_SUMA")

    @Rule(Cartera(etapa="LIQUIDEZ_MINIMA", valores=MATCH.valores), Inversor(liquidez=MATCH.liquidez),
          TEST(lambda valores: all(_es_entero(v) and v >= 0 for _, v in valores)),
          TEST(lambda valores: sum(v for _, v in valores) == 100),
          TEST(lambda valores, liquidez: dict(valores)["Liquidez inmediata"] < liquidez), salience=2)
    def rechazar_liquidez_insuficiente(self):
        """Rechaza una distribución que no alcanza la liquidez mínima pedida.
        RF-04 y sección 7: emitir sólo asignaciones consistentes con las restricciones.
        Consume Cartera LIQUIDEZ_MINIMA (N7) + Inversor; declara FalloAsignacion (N8).
        """
        self._fallo(MSG_LIQUIDEZ, "rechazar_liquidez_insuficiente", "R_VALIDACION_LIQUIDEZ")

    @Rule(Cartera(etapa="LIQUIDEZ_MINIMA", valores=MATCH.valores), Inversor(liquidez=MATCH.liquidez),
          TEST(lambda valores: all(_es_entero(v) and v >= 0 for _, v in valores)),
          TEST(lambda valores: sum(v for _, v in valores) == 100),
          TEST(lambda valores, liquidez: dict(valores)["Liquidez inmediata"] >= liquidez), salience=2)
    def aprobar_cartera(self, valores):
        """Valida porcentajes enteros no negativos, suma 100 y liquidez suficiente.
        RF-04 y sección 7: asegurar la consistencia de la distribución recomendada.
        Consume Cartera LIQUIDEZ_MINIMA (N7) + Inversor; declara CarteraFinal (N8).
        """
        self.declare(CarteraFinal(valores=valores))
        self._registrar("aprobar_cartera", "R_VALIDACION_OK", 8, f"Cartera final: {_a_dict(valores)}")

    def _fallo(self, mensaje, regla, codigo):
        self.declare(FalloAsignacion(mensaje=mensaje))
        self._registrar(regla, codigo, 8, mensaje)

    # ================================================= NIVEL 9
    # Traduce la cartera validada N8 a CER/Letras, ON Hard Dollar, CEDEAR/Merval y FCI Money Market.
    # Declara RECOMENDACION_EXITOSA o ASIGNACION_INVIABLE a partir del resultado N8.
    def _tipo(self, valores, categoria, regla, codigo):
        porcentaje = _a_dict(valores)[categoria]
        self.declare(TipoInstrumento(categoria=categoria, tipo=TIPOS_INSTRUMENTO[categoria], porcentaje=porcentaje))
        self._registrar(regla, codigo, 9, f"{categoria} {porcentaje}% -> {TIPOS_INSTRUMENTO[categoria]}")

    @Rule(CarteraFinal(valores=MATCH.valores),
          TEST(lambda valores: dict(valores).get("Renta fija inflación", 0) > 0), salience=1)
    def tipo_renta_fija_inflacion(self, valores):
        """Traduce la cobertura de inflación a Bonos CER / Letras del Tesoro si su ponderación es positiva.
        RF-05 y sección 6: identificar la familia de instrumentos de cada clase.
        Consume CarteraFinal (N8); declara TipoInstrumento (N9).
        """
        self._tipo(valores, "Renta fija inflación", "tipo_renta_fija_inflacion", "R_TIPO_RF_INFLACION")

    @Rule(CarteraFinal(valores=MATCH.valores),
          TEST(lambda valores: dict(valores).get("Renta fija cambiaria", 0) > 0), salience=1)
    def tipo_renta_fija_cambiaria(self, valores):
        """Traduce la cobertura cambiaria a Obligaciones Negociables Hard Dollar si su ponderación es positiva.
        RF-05 y sección 6: identificar la familia de instrumentos de cada clase.
        Consume CarteraFinal (N8); declara TipoInstrumento (N9).
        """
        self._tipo(valores, "Renta fija cambiaria", "tipo_renta_fija_cambiaria", "R_TIPO_RF_CAMBIARIA")

    @Rule(CarteraFinal(valores=MATCH.valores),
          TEST(lambda valores: dict(valores).get("Renta variable", 0) > 0), salience=1)
    def tipo_renta_variable(self, valores):
        """Traduce la renta variable a CEDEARs / acciones locales (Merval en el brief) si su ponderación es positiva.
        RF-05 y sección 6: identificar la familia de instrumentos de cada clase.
        Consume CarteraFinal (N8); declara TipoInstrumento (N9).
        """
        self._tipo(valores, "Renta variable", "tipo_renta_variable", "R_TIPO_RENTA_VARIABLE")

    @Rule(CarteraFinal(valores=MATCH.valores),
          TEST(lambda valores: dict(valores).get("Liquidez inmediata", 0) > 0), salience=1)
    def tipo_liquidez(self, valores):
        """Traduce la liquidez inmediata a FCI Money Market si su ponderación es positiva.
        RF-05 y sección 6: identificar la familia de instrumentos de cada clase.
        Consume CarteraFinal (N8); declara TipoInstrumento (N9).
        """
        self._tipo(valores, "Liquidez inmediata", "tipo_liquidez", "R_TIPO_LIQUIDEZ")

    @Rule(CarteraFinal(), salience=0)
    def concluir_recomendacion(self):
        """Concluye una recomendación exitosa cuando existe una cartera validada.
        RF-04 y sección 6: comunicar el estado final de la asignación porcentual.
        Consume CarteraFinal (N8); declara Conclusion RECOMENDACION_EXITOSA (N9).
        """
        self.declare(Conclusion(estado="RECOMENDACION_EXITOSA"))
        self._registrar("concluir_recomendacion", "R_CONCLUSION_EXITOSA", 9, "RECOMENDACION_EXITOSA")

    @Rule(FalloAsignacion(mensaje=MATCH.mensaje), salience=0)
    def concluir_asignacion_inviable(self, mensaje):
        """Concluye que la asignación es inviable ante un fallo de validación.
        Sección 6: informar de forma controlada la imposibilidad de recomendar.
        Consume FalloAsignacion (N8); declara Conclusion ASIGNACION_INVIABLE (N9).
        """
        self.declare(Conclusion(estado="ASIGNACION_INVIABLE"))
        self._registrar("concluir_asignacion_inviable", "R_CONCLUSION_INVIABLE", 9, mensaje)


def hechos_de(motor, clase):
    return [h for h in motor.facts.values() if isinstance(h, clase)]


def derivaciones_de_coherencia(tolerancia, horizonte, objetivo, matriz=None):
    """Ejecuta sólo los datos del inversor y devuelve [(codigo, mensaje)] ordenados."""
    motor = MotorRoboAdvisor(matriz)
    motor.reset()
    motor.declare(Inversor(tolerancia=tolerancia, horizonte=horizonte, objetivo=objetivo))
    motor.run()
    return [(d["codigo"], d["mensaje"]) for d in sorted(hechos_de(motor, Derivacion), key=lambda d: d["orden"])]
