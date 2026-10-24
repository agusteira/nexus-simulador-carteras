"""Regresión técnica; la aprobación financiera de los casos sigue pendiente."""

import json
from pathlib import Path
import unittest

from nexus.service import evaluar


ROOT = Path(__file__).resolve().parents[1]


class BriefCasesTest(unittest.TestCase):
    def test_reference_outputs_and_determinism(self):
        cases = json.loads((ROOT / "docs/casos-brief.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases["casos"]), 10)
        for case in cases["casos"]:
            with self.subTest(case=case["id"]):
                for _ in range(2):
                    result, audit, errors = evaluar(case["datos"], case["mercado"])
                    result.pop("fecha_ejecucion", None)
                    actual = json.loads(json.dumps({
                        "resultado": result, "auditoria": audit, "errores": errors,
                    }))
                    self.assertEqual(actual, case["expected"])
                    if result["estado"] == "RECOMENDACION_EXITOSA":
                        self.assertEqual(sum(result["cartera_porcentual"].values()), 100)
                        self.assertGreaterEqual(
                            result["cartera_porcentual"]["Liquidez inmediata"],
                            case["datos"]["liquidez"],
                        )
                        if result["perfil_riesgo"] == "CONSERVADOR":
                            self.assertEqual(result["cartera_porcentual"]["Renta variable"], 0)


if __name__ == "__main__":
    unittest.main()
