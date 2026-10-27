"""RF-08: matrices de decisión configurables y versionadas."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from nexus import matrices
from nexus.portfolio import construir_cartera
from nexus.service import evaluar


DATOS = {"capital": 100000.0, "moneda": "ARS", "horizonte": 24,
         "objetivo": "Crecimiento", "tolerancia": 10, "liquidez": 20}
MERCADO = {"inflacion_alta": False, "presion_cambiaria": False,
           "volatilidad_alta": False, "mercado_actualizado": True}


class MatricesTest(unittest.TestCase):
    def setUp(self):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.data_dir = directorio.name
        entorno = patch.dict(os.environ, {"NEXUS_DATA_DIR": self.data_dir})
        entorno.start()
        self.addCleanup(entorno.stop)

    def test_default_is_version_1_and_valid(self):
        numero, matriz = matrices.version_activa()
        self.assertEqual(numero, 1)
        self.assertEqual(matrices.validar_matriz(matriz), [])
        self.assertEqual(len(matrices.listar_versiones()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "matrices_versiones.json")))

    def test_save_list_and_restore_keep_history(self):
        _, matriz = matrices.version_activa()
        matriz["umbrales_perfil"]["moderado_tolerancia_max"] = 15
        self.assertEqual(matrices.guardar_version(matriz, "ana", "sube umbral"), 2)
        self.assertEqual(matrices.version_activa()[0], 2)
        self.assertEqual(matrices.restaurar_version(1, "ana"), 3)
        numero, activa = matrices.version_activa()
        self.assertEqual(numero, 3)
        self.assertEqual(activa, matrices.matriz_inicial())
        versiones = matrices.listar_versiones()
        self.assertEqual([v["version"] for v in versiones], [3, 2, 1])
        self.assertEqual(versiones[0]["origen"], 1)
        self.assertTrue(versiones[0]["activa"])
        self.assertEqual(versiones[1]["autor"], "ana")
        self.assertIsNotNone(versiones[1]["fecha"])
        with open(os.path.join(self.data_dir, "matrices_versiones.json"), encoding="utf-8") as archivo:
            guardado = json.load(archivo)
        self.assertEqual(guardado["activa"], 3)

    def test_invalid_matrix_and_missing_author_are_rejected(self):
        _, matriz = matrices.version_activa()
        matriz["carteras_base"]["MODERADO"]["Renta variable"] = 30  # suma 110
        self.assertTrue(matrices.validar_matriz(matriz))
        with self.assertRaises(ValueError):
            matrices.guardar_version(matriz, "ana")
        with self.assertRaises(ValueError):
            matrices.guardar_version(matrices.matriz_inicial(), "  ")
        _, invertida = matrices.version_activa()
        invertida["umbrales_perfil"]["conservador_tolerancia_max"] = 20  # mayor que moderado
        self.assertTrue(matrices.validar_matriz(invertida))
        self.assertEqual(matrices.version_activa()[0], 1)
        with self.assertRaises(KeyError):
            matrices.obtener_version(99)

    def test_result_records_version_and_edited_threshold_changes_profile(self):
        resultado, _, _ = evaluar(DATOS, MERCADO)
        self.assertEqual((resultado["version_matriz"], resultado["perfil_riesgo"]), (1, "MODERADO"))
        _, matriz = matrices.version_activa()
        matriz["umbrales_perfil"]["moderado_tolerancia_max"] = 5
        matrices.guardar_version(matriz, "ana")
        resultado, auditoria, _ = evaluar(DATOS, MERCADO)
        self.assertEqual((resultado["version_matriz"], resultado["perfil_riesgo"]), (2, "AGRESIVO"))
        self.assertIn("superior al 5%", " ".join(a["motivo"] for a in auditoria))

    def test_class_cap_moves_excess_to_liquidity(self):
        matriz = matrices.matriz_inicial()
        matriz["topes_clase"]["AGRESIVO"]["Renta variable"] = 30
        cartera = construir_cartera("AGRESIVO", "ESTABLE", 20, matriz)
        self.assertEqual(cartera["Renta variable"], 30)
        self.assertEqual(cartera["Liquidez inmediata"], 35)
        self.assertEqual(sum(cartera.values()), 100)

    def test_disabled_adjustment_and_priority_are_configurable(self):
        mercado = {**MERCADO, "inflacion_alta": True, "presion_cambiaria": True}
        resultado, _, _ = evaluar(DATOS, mercado)
        self.assertEqual(resultado["regimen_mercado"], "INFLACION_ALTA")
        _, matriz = matrices.version_activa()
        matriz["prioridad_regimen"] = ["PRESION_CAMBIARIA", "INFLACION_ALTA", "VOLATILIDAD_ALTA"]
        matriz["ajustes_regimen"]["PRESION_CAMBIARIA"]["activo"] = False
        matrices.guardar_version(matriz, "ana")
        resultado, _, _ = evaluar(DATOS, mercado)
        self.assertEqual(resultado["regimen_mercado"], "PRESION_CAMBIARIA")
        self.assertEqual(resultado["cartera_porcentual"], matriz["carteras_base"]["MODERADO"])


if __name__ == "__main__":
    unittest.main()
