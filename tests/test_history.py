"""RF-09: persistencia y consulta del historial de evaluaciones."""

from datetime import date, timedelta
import os
import tempfile
import unittest
from unittest.mock import patch

from nexus import history
from nexus.service import evaluar


DATOS = {"usuario_id": "Ana", "capital": 100000.0, "moneda": "ARS", "horizonte": 24,
         "objetivo": "Crecimiento", "tolerancia": 30, "liquidez": 20}
MERCADO = {"inflacion_alta": True, "presion_cambiaria": False,
           "volatilidad_alta": False, "mercado_actualizado": True}


class HistoryTest(unittest.TestCase):
    def setUp(self):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        entorno = patch.dict(os.environ, {"NEXUS_DATA_DIR": directorio.name})
        entorno.start()
        self.addCleanup(entorno.stop)

    def guardar(self, datos=DATOS, mercado=MERCADO):
        resultado, auditoria, errores = evaluar(datos, mercado)
        return history.guardar_evaluacion(datos, mercado, resultado, auditoria, errores), resultado, auditoria

    def test_full_record_round_trip(self):
        identificador, resultado, auditoria = self.guardar()
        registro = history.obtener_evaluacion(identificador)
        self.assertEqual(registro["usuario_id"], "Ana")
        self.assertEqual(registro["entrada"], DATOS)
        self.assertEqual(registro["mercado"], MERCADO)
        self.assertEqual(registro["resultado"], resultado)
        self.assertEqual(registro["auditoria"], auditoria)
        self.assertTrue(registro["auditoria"])
        self.assertEqual(registro["version_matriz"], 1)
        self.assertEqual(registro["perfil_riesgo"], "AGRESIVO")
        self.assertEqual(registro["regimen_mercado"], "INFLACION_ALTA")
        self.assertIsNone(history.obtener_evaluacion(9999))

    def test_filters_by_user_and_date_range(self):
        self.guardar()
        self.guardar({**DATOS, "usuario_id": "beto", "tolerancia": 0})
        self.guardar({**DATOS, "usuario_id": ""})
        self.guardar(mercado={**MERCADO, "mercado_actualizado": False})  # derivación: también se registra
        self.assertEqual(history.listar_usuarios(), ["Ana", "anonimo", "beto"])
        filas = history.consultar_historial("ana")  # sin distinguir mayúsculas
        self.assertEqual(len(filas), 2)
        self.assertGreater(filas[0]["id"], filas[1]["id"])  # más recientes primero
        self.assertEqual({f["estado"] for f in filas},
                         {"RECOMENDACION_EXITOSA", history.obtener_evaluacion(filas[0]["id"])["estado"]})
        self.assertEqual(len(history.consultar_historial()), 4)
        hoy = date.today()
        self.assertEqual(len(history.consultar_historial(None, hoy, hoy)), 4)
        self.assertEqual(history.consultar_historial(None, hoy + timedelta(days=1)), [])
        self.assertEqual(history.consultar_historial(None, None, hoy - timedelta(days=1)), [])


if __name__ == "__main__":
    unittest.main()
