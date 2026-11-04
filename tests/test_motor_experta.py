import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp())

from nexus import matrices  # noqa: E402  (importa primero nexus: aplica el shim de collections)
from experta import Rule  # noqa: E402
from nexus.engine import MotorRoboAdvisor  # noqa: E402
from nexus.portfolio import construir_cartera  # noqa: E402
from nexus.service import evaluar, evaluar_con_traza  # noqa: E402

GOLDEN = Path(__file__).parent / "fixtures" / "golden_baseline.json"
DATOS = {"capital": 100000, "moneda": "ARS", "horizonte": 24, "objetivo": "Crecimiento",
         "tolerancia": 15, "liquidez": 10}
MERCADO = {"mercado_actualizado": True, "inflacion_alta": True, "presion_cambiaria": False,
           "volatilidad_alta": False}


def _norm(valor):
    return json.loads(json.dumps(valor, ensure_ascii=False))


def _salida(datos, mercado):
    resultado, auditoria, errores = evaluar(datos, mercado)
    resultado = dict(resultado)
    resultado.pop("fecha_ejecucion", None)
    return _norm({"resultado": resultado, "auditoria": auditoria, "errores": errores})


class EstructuraMotorTests(unittest.TestCase):
    def test_motor_tiene_al_menos_20_reglas(self):
        reglas = [n for n, v in vars(MotorRoboAdvisor).items() if isinstance(v, Rule)]
        self.assertGreaterEqual(len(reglas), 20, reglas)

    def test_traza_encadena_al_menos_tres_niveles(self):
        _, _, _, traza = evaluar_con_traza(DATOS, MERCADO)
        niveles = {paso["nivel"] for paso in traza}
        self.assertTrue({1, 2, 3}.issubset(niveles), traza)
        self.assertEqual([p["orden"] for p in traza], list(range(1, len(traza) + 1)))
        reglas = [p["regla"] for p in traza]
        self.assertLess(reglas.index("senal_inflacion"), reglas.index("regimen_prioridad_2"))
        self.assertLess(reglas.index("regimen_prioridad_2"), reglas.index("ajustar_por_inflacion"))
        self.assertEqual(reglas[-1], "concluir_recomendacion")


class DerivacionHorizonteCortoTests(unittest.TestCase):
    def test_horizonte_menor_a_6_con_crecimiento_deriva(self):
        for meses in (1, 3, 5):
            resultado, auditoria, errores = evaluar(dict(DATOS, horizonte=meses), MERCADO)
            self.assertEqual(resultado["estado"], "DERIVADO_ASESOR_MANUAL")
            self.assertEqual(resultado["errores"][-1]["codigo"], "ERR_HORIZONTE_CORTO_CRECIMIENTO")
            self.assertEqual(auditoria, [])

    def test_limites_no_derivan(self):
        for datos in (dict(DATOS, horizonte=6), dict(DATOS, horizonte=3, objetivo="Preservacion"),
                      dict(DATOS, horizonte=3, objetivo="Renta periodica")):
            resultado, _, _ = evaluar(datos, MERCADO)
            self.assertEqual(resultado["estado"], "RECOMENDACION_EXITOSA", datos)


class EquivalenciaGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_evaluar_idem_golden(self):
        casos = self.golden["casos_evaluar"]
        for caso in [c for c in casos if c["matriz"] == "v1"]:
            with self.subTest(caso=caso["id"]):
                self.assertEqual(_salida(caso["datos"], caso["mercado"]), caso["esperado"])
        matrices.guardar_version(self.golden["matrices"]["v2"], "golden", "matriz alternativa para golden")
        for caso in [c for c in casos if c["matriz"] == "v2"]:
            with self.subTest(caso=caso["id"]):
                self.assertEqual(_salida(caso["datos"], caso["mercado"]), caso["esperado"])

    def test_construir_cartera_idem_golden(self):
        for indice, caso in enumerate(self.golden["casos_construir_cartera"]):
            matriz = self.golden["matrices"][caso["matriz"]]
            with self.subTest(caso=indice):
                if caso.get("sin_kwargs"):
                    cartera = construir_cartera(caso["perfil"], caso["regimen"], caso["liquidez"], matriz)
                    self.assertEqual(list(cartera.items()), [tuple(x) for x in caso["cartera"].items()])
                    continue
                auditoria = []
                try:
                    cartera = construir_cartera(caso["perfil"], caso["regimen"], caso["liquidez"], matriz,
                                                horizonte=caso["horizonte"], objetivo=caso["objetivo"],
                                                auditoria=auditoria)
                    error = None
                except ValueError as exc:
                    cartera, error = None, str(exc)
                self.assertEqual(error, caso["error"])
                if cartera is not None:
                    self.assertEqual(list(cartera.items()), [tuple(x) for x in caso["cartera"].items()])
                self.assertEqual(_norm(auditoria), caso["auditoria"])


if __name__ == "__main__":
    unittest.main()
