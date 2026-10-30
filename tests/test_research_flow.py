import os
import tempfile
import unittest
from unittest.mock import patch

from nexus import history
from nexus.instruments import execution_id


class ResearchHistoryFlowTests(unittest.TestCase):
    def test_research_revisions_append_without_changing_base_evaluation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NEXUS_DATA_DIR": directory}):
            result = {"estado": "OK", "capital": 100}
            evaluation_id = history.guardar_evaluacion({"capital": 100}, {}, result, [], [])
            inputs = {"perfil": {"capital": 100}, "escenario": {}}
            run_id = execution_id(result, inputs)
            first = {"ejecucion_id": run_id, "entradas_evaluacion": inputs,
                     "investigacion": {"execution_id": run_id, "inputs": inputs}, "categorias": []}
            second = {"ejecucion_id": run_id, "entradas_evaluacion": inputs,
                      "investigacion": {"execution_id": run_id, "inputs": inputs}, "categorias": [{"decision": "REQUIERE_REVISION"}]}
            self.assertEqual(history.anexar_revision_investigacion(evaluation_id, first), 1)
            self.assertEqual(history.anexar_revision_investigacion(evaluation_id, first), 1)
            self.assertEqual(history.anexar_revision_investigacion(evaluation_id, second), 2)
            saved = history.obtener_evaluacion(evaluation_id)
        self.assertEqual(saved["resultado"]["estado"], "OK")
        self.assertEqual(saved["resultado"]["ejemplos_instrumentos"], second)
        self.assertEqual([r["revision"] for r in saved["revisiones_investigacion"]], [1, 2])
        self.assertEqual(saved["revisiones_investigacion"][0]["snapshot"], first)
        self.assertEqual(saved["resultado"]["revisiones_investigacion"], [first, second])

    def test_rejects_snapshot_for_different_evaluation_inputs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NEXUS_DATA_DIR": directory}):
            evaluation_id = history.guardar_evaluacion({"perfil": {"capital": 100}}, {}, {"estado": "OK"}, [], [])
            foreign = {"ejecucion_id": "other", "entradas_evaluacion": {"perfil": {"capital": 200}, "escenario": {}},
                       "investigacion": {"execution_id": "other"}}
            with self.assertRaises(ValueError):
                history.anexar_revision_investigacion(evaluation_id, foreign)

    def test_same_inputs_cannot_attach_research_from_another_matrix_result(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NEXUS_DATA_DIR": directory}):
            result = {"estado": "OK", "capital": 100, "version_matriz": 1}
            evaluation_id = history.guardar_evaluacion({"capital": 100}, {}, result, [], [])
            inputs = {"perfil": {"capital": 100}, "escenario": {}}
            foreign_id = execution_id({**result, "version_matriz": 2}, inputs)
            foreign = {"ejecucion_id": foreign_id, "entradas_evaluacion": inputs,
                       "investigacion": {"execution_id": foreign_id, "inputs": inputs}}
            with self.assertRaisesRegex(ValueError, "otro resultado"):
                history.anexar_revision_investigacion(evaluation_id, foreign)


if __name__ == "__main__":
    unittest.main()
