"""Recorrido, conservación de respuestas y consistencia de la evaluación."""

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class UserFlowTest(unittest.TestCase):
    def setUp(self):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        self.data_dir = directorio.name
        entorno = patch.dict(os.environ, {"NEXUS_DATA_DIR": self.data_dir})
        entorno.start()
        self.addCleanup(entorno.stop)
        today = datetime.now(timezone.utc).date().isoformat()
        self.public_source = patch("nexus.instruments.ArgentinaDatosClient.fund_catalog", return_value={
            "fondos": [{"nombre": "Fondo offline de prueba", "fondoId": "1", "claseId": "1", "fecha": today,
                        "tipoRenta": "Renta Variable", "moneda": "Peso Argentino", "monedaInversion": "Peso Argentino"}],
            "fuente": "Fixture offline de tests", "url": "https://example.test/funds", "cache": False,
            "consultado_en": today + "T00:00:00+00:00", "fecha_publicacion": today + "T00:00:00+00:00"})
        self.source_mock = self.public_source.start()
        self.addCleanup(self.public_source.stop)
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self.assert_clean()

    def assert_clean(self):
        self.assertFalse(self.app.exception, [e.message for e in self.app.exception])

    def click(self, label):
        matches = [b for b in self.app.button if label in b.label]
        self.assertEqual(len(matches), 1, f"Botón ambiguo o ausente: {label}")
        matches[0].click().run()
        self.assert_clean()

    def navigate(self, step):
        self.app.button(key=f"nav_{step}").click().run()
        self.assert_clean()

    def set_capital(self, value):
        # AppTest has no v2 component driver. Send the same JSON widget state
        # that the browser emits on blur, exercising the actual Python callback.
        states = self.app._tree.get_widget_states()
        widget = states.widgets.add()
        widget.id = self.app.get("bidi_component")[0].proto.id
        text = "" if value is None else f"{value:.2f}".replace(".", ",")
        widget.json_value = json.dumps({"value": text})
        self.app._run(states)
        self.assert_clean()

    def fill_profile(self, capital=250000.0, tolerance=20, objective="Preservacion"):
        self.navigate("perfil")
        self.set_capital(capital)
        self.app.select_slider(key="perfil_tolerancia").set_value(tolerance).run()
        self.app.selectbox(key="perfil_objetivo").set_value(objective).run()
        self.click("Guardar perfil y continuar")

    def evaluate(self):
        self.app.checkbox(key="escenario_confirmado").check().run()
        self.click("Guardar escenario y revisar")
        self.click("Ejecutar evaluación")

    def test_saved_and_unsaved_values_survive_navigation(self):
        self.fill_profile()
        self.navigate("perfil")
        self.assertEqual(self.app.session_state["perfil_capital"], 250000.0)
        self.assertEqual(self.app.select_slider(key="perfil_tolerancia").value, 20)
        self.set_capital(300000.0)
        self.navigate("inicio")
        self.navigate("perfil")
        self.assertEqual(self.app.session_state["perfil_capital"], 300000.0)
        self.assertEqual(self.app.session_state["datos_inversor"]["capital"], 250000.0)

    def test_missing_capital_is_validated_on_submit(self):
        self.navigate("perfil")
        self.assertIsNone(self.app.session_state["perfil_capital"])
        self.assertFalse(self.app.error)
        self.click("Guardar perfil y continuar")
        self.assertEqual(self.app.session_state["paso_actual"], "perfil")
        self.assertIn("capital", self.app.session_state["errores_perfil"])

    def test_money_commit_and_submit_in_same_event_batch(self):
        self.navigate("perfil")
        self.app.selectbox(key="perfil_moneda").set_value("USD").run()
        button = next(b for b in self.app.button if "Guardar perfil y continuar" in b.label)
        button.click()
        self.set_capital(1234567.89)
        self.assertEqual(self.app.session_state["paso_actual"], "escenario")
        self.assertEqual(self.app.session_state["datos_inversor"]["capital"], 1234567.89)
        self.assertEqual(self.app.session_state["datos_inversor"]["moneda"], "USD")
        self.assertEqual(self.app.session_state["perfil_borrador"]["capital"], 1234567.89)

    def test_invalid_money_cannot_reuse_previous_valid_capital(self):
        self.fill_profile()
        self.navigate("perfil")
        states = self.app._tree.get_widget_states()
        widget = states.widgets.add()
        widget.id = self.app.get("bidi_component")[0].proto.id
        widget.json_value = json.dumps({"value": "-100"})
        self.app._run(states)
        self.assertIsNone(self.app.session_state["perfil_capital"])
        self.assertIsNone(self.app.session_state["perfil_borrador"]["capital"])
        self.assertEqual(json.loads(self.app.get("bidi_component")[0].proto.json)["value"], "-100")
        self.click("Guardar perfil y continuar")
        self.assertEqual(self.app.session_state["paso_actual"], "perfil")
        self.assertEqual(self.app.session_state["datos_inversor"]["capital"], 250000.0)
        self.click("Descartar cambios")
        self.assertEqual(self.app.session_state["perfil_capital"], 250000.0)

    def test_scenario_confirmation_is_validated_on_submit(self):
        self.fill_profile()
        self.assertFalse(self.app.error)
        self.click("Guardar escenario y revisar")
        self.assertEqual(self.app.session_state["paso_actual"], "escenario")
        self.assertTrue(self.app.error)
        self.evaluate()
        self.assertEqual(self.app.session_state["resultado_robo"]["estado"], "RECOMENDACION_EXITOSA")
        self.assertTrue(self.app.get("download_button"))

    def test_stale_result_keeps_original_inputs_until_recalculation(self):
        self.fill_profile()
        self.evaluate()
        original = self.app.session_state["snapshot_ejecucion"]["perfil"].copy()
        self.navigate("perfil")
        self.set_capital(500000.0)
        self.navigate("resultado")
        warnings = " ".join(w.value.lower() for w in self.app.warning)
        self.assertIn("desactualiz", warnings)
        self.assertEqual(self.app.session_state["resultado_robo"]["capital"], 250000.0)
        self.assertEqual(self.app.session_state["snapshot_ejecucion"]["perfil"], original)
        self.navigate("revision")
        executable = [b for b in self.app.button if "Ejecutar evaluación" in b.label and not b.disabled]
        self.assertFalse(executable, "No se debe ejecutar ignorando cambios sin guardar")
        self.navigate("perfil")
        self.click("Guardar perfil y continuar")
        self.evaluate()
        self.assertEqual(self.app.session_state["resultado_robo"]["capital"], 500000.0)
        self.assertEqual(self.app.session_state["snapshot_ejecucion"]["perfil"]["capital"], 500000.0)
        self.assertFalse(any("desactualiz" in w.value.lower() for w in self.app.warning))

    def test_conflicting_preferences_reach_controlled_review(self):
        self.fill_profile(100000.0, 0, "Crecimiento")
        self.assertEqual(self.app.session_state["paso_actual"], "escenario")
        self.evaluate()
        result = self.app.session_state["resultado_robo"]
        self.assertEqual(result["estado"], "DERIVADO_ASESOR_MANUAL")
        self.assertEqual(result["errores"][0]["codigo"], "ERR_INCONSISTENCIA_PERFIL_HORIZONTE")
        self.assertEqual(self.app.session_state["datos_inversor"]["tolerancia"], 0)
        self.assertEqual(self.app.session_state["datos_inversor"]["objetivo"], "Crecimiento")

    def test_discarding_drafts_restores_saved_answers_and_current_result(self):
        self.fill_profile()
        self.evaluate()
        self.navigate("perfil")
        self.set_capital(300000.0)
        self.click("Descartar cambios")
        self.assertEqual(self.app.session_state["perfil_capital"], 250000.0)
        self.navigate("escenario")
        self.app.toggle(key="escenario_inflacion").set_value(True).run()
        self.click("Descartar cambios")
        self.assertFalse(self.app.toggle(key="escenario_inflacion").value)
        self.navigate("resultado")
        self.assertFalse(any("desactualiz" in w.value.lower() for w in self.app.warning))

    def test_audit_retains_same_execution(self):
        self.fill_profile()
        self.evaluate()
        result = self.app.session_state["resultado_robo"].copy()
        self.navigate("auditoria")
        self.assertEqual(self.app.session_state["resultado_robo"], result)
        self.assertTrue(self.app.get("download_button"))
        self.assertTrue(self.app.dataframe)

    def test_instrument_query_is_once_per_execution_and_refresh_is_explicit(self):
        self.fill_profile()
        self.evaluate()
        self.assertEqual(self.source_mock.call_count, 1)
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.navigate("auditoria")
        self.navigate("resultado")
        self.assertEqual(self.source_mock.call_count, 1)
        self.assertEqual(self.app.session_state["resultado_robo"]["ejemplos_instrumentos"], saved)
        self.click("Actualizar ejemplos")
        self.assertEqual(self.source_mock.call_count, 2)
        self.assertTrue(self.source_mock.call_args.kwargs["refresh"])
        self.navigate("perfil")
        self.set_capital(300000.0)
        self.navigate("resultado")
        self.assertEqual(self.source_mock.call_count, 2)
        preserved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.assertEqual(preserved["entradas_evaluacion"]["perfil"]["capital"], 250000.0)
        self.assertEqual(preserved["ejecucion_id"], saved["ejecucion_id"])

    def test_instrument_source_failure_does_not_retry_on_navigation(self):
        from nexus.market_data import MarketDataError
        self.source_mock.side_effect = MarketDataError("Fixture offline: sin conexión")
        self.fill_profile()
        self.evaluate()
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.assertTrue(saved["errores_fuente"])
        self.assertEqual(self.app.session_state["resultado_robo"]["estado"], "RECOMENDACION_EXITOSA")
        self.navigate("inicio")
        self.navigate("resultado")
        self.assertEqual(self.source_mock.call_count, 1)
        self.click("Reintentar consulta")
        self.assertEqual(self.source_mock.call_count, 2)

    def test_failed_catalog_shows_one_warning_and_retry_recovers(self):
        from nexus.market_data import MarketDataError
        good = self.source_mock.return_value
        self.source_mock.side_effect = [MarketDataError("Fixture offline: sin conexión"), good]
        self.fill_profile()
        self.evaluate()
        self.assertEqual(len(self.app.warning), 1)
        self.assertEqual(self.app.warning[0].value, "No pudimos cargar el catálogo de fondos. Reintentá la consulta.")
        self.assertFalse(any("Renta variable ·" in item.label or "Renta fija" in item.label for item in self.app.expander))
        self.assertEqual(len([b for b in self.app.button if "Reintentar consulta" in b.label]), 1)
        self.click("Reintentar consulta")
        self.assertEqual(self.source_mock.call_count, 2)
        self.assertFalse(self.app.warning)
        self.assertTrue(self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]["fuentes"])

    def test_alternative_funds_are_visible_without_generic_info(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.source_mock.return_value = {
            "fondos": [{"nombre": "Renta fija alternativa", "fondoId": "2", "claseId": "3", "fecha": today,
                        "tipoRenta": "Renta Fija", "moneda": "Peso Argentino", "monedaInversion": "Peso Argentino",
                        "inversionMinima": None}],
            "fuente": "Fixture offline de tests", "url": "https://example.test/funds", "cache": False,
            "consultado_en": today + "T00:00:00+00:00", "fecha_publicacion": today + "T00:00:00+00:00"}
        self.fill_profile()
        self.evaluate()
        content = " ".join(item.value for item in self.app.markdown if isinstance(item.value, str))
        self.assertIn("alternativas para investigar", content)
        self.assertIn("Renta fija alternativa", content)
        self.assertFalse(any("No pudimos verificar un instrumento que cumpla" in item.value for item in self.app.info))

    def test_zero_results_explain_currency_and_category_budget_together(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.source_mock.return_value = {
            "fondos": [
                {"nombre": "Variable en USD", "fondoId": "10", "claseId": "1", "fecha": today,
                 "tipoRenta": "Renta Variable", "moneda": "USD", "monedaInversion": "USD", "inversionMinima": 1},
                {"nombre": "Mínimo alto", "fondoId": "11", "claseId": "1", "fecha": today,
                 "tipoRenta": "Renta Variable", "moneda": "Peso Argentino", "monedaInversion": "Peso Argentino",
                 "inversionMinima": 999999999},
            ],
            "fuente": "Fixture offline de tests", "url": "https://example.test/funds", "cache": False,
            "consultado_en": today + "T00:00:00+00:00", "fecha_publicacion": today + "T00:00:00+00:00"}
        self.fill_profile()
        self.evaluate()
        labels = [item.label for item in self.app.expander]
        variable_status = next(label for label in labels if label.startswith("Renta variable ·"))
        self.assertIn("Sin opciones para este monto", variable_status)
        infos = " ".join(item.value for item in self.app.info)
        self.assertIn("registros con moneda distinta o sin confirmar", infos)
        self.assertIn("registros con mínimo superior al monto de esta categoría", infos)
        captions = " ".join(item.value for item in self.app.caption)
        self.assertIn("Monto asignado a esta categoría:", captions)
        self.assertIn("ARS", captions)

    def test_legacy_saved_examples_render_fallback_without_requery(self):
        self.fill_profile()
        self.evaluate()
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.assertTrue(any(not category["ejemplos"] and not category["alternativas"] for category in saved["categorias"]))
        for category in saved["categorias"]:
            category.pop("diagnostico", None)
            category.pop("monto_asignado", None)
        self.navigate("auditoria")
        self.navigate("resultado")
        self.assertEqual(self.source_mock.call_count, 1)
        self.assertTrue(any("no incluye motivos de descarte" in item.value for item in self.app.info))
        self.assert_clean()

    def test_example_scenarios_update_draft_and_evaluation(self):
        self.fill_profile()
        flag_keys = ("escenario_inflacion", "escenario_cambio", "escenario_volatilidad")
        examples = ((False, False, False), (True, False, False),
                    (False, True, False), (False, False, True))
        for index, expected in enumerate(examples):
            self.app.button(key=f"ejemplo_escenario_{index}").click().run()
            self.assert_clean()
            self.assertEqual(tuple(self.app.toggle(key=key).value for key in flag_keys), expected)
        self.navigate("perfil")
        self.navigate("escenario")
        self.assertTrue(self.app.toggle(key="escenario_volatilidad").value)
        self.evaluate()
        result = self.app.session_state["resultado_robo"]
        self.assertEqual(result["regimen_mercado"], "VOLATILIDAD_ALTA")
        self.assertEqual(result["cartera_porcentual"]["Renta variable"], 0)


    def test_evaluations_are_persisted_and_listed_in_history(self):
        from nexus import history

        self.navigate("perfil")
        self.app.text_input(key="perfil_usuario").input("ana").run()
        self.fill_profile(tolerance=0)
        self.evaluate()
        self.fill_profile(tolerance=30, objective="Crecimiento")
        self.evaluate()
        filas = history.consultar_historial("ana")
        self.assertEqual(len(filas), 2)
        self.assertEqual({f["perfil_riesgo"] for f in filas}, {"CONSERVADOR", "AGRESIVO"})
        self.assertEqual(self.app.session_state["historial_id"], filas[0]["id"])
        registro = history.obtener_evaluacion(filas[0]["id"])
        self.assertEqual(registro["resultado"]["version_matriz"], 1)
        self.assertTrue(registro["auditoria"])
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "historial.db")))

        self.navigate("historial")
        self.assertEqual(self.app.text_input(key="historial_usuario").value, "ana")
        self.assertTrue(self.app.dataframe)
        self.assertTrue(any("Comparación" in m.value for m in self.app.markdown))
        self.assertTrue(self.app.get("download_button"))
        self.app.text_input(key="historial_usuario").input("nadie").run()
        self.assert_clean()
        self.assertTrue(any("No hay evaluaciones" in i.value for i in self.app.info))

    def test_admin_saves_new_version_used_by_next_evaluation(self):
        self.navigate("administracion")
        self.assertTrue(any("v1" in i.value for i in self.app.info))
        self.app.number_input(key="adm_v1_umb_m").set_value(25)
        self.app.text_input(key="adm_v1_autor").input("docente")
        self.app.text_input(key="adm_v1_nota").input("Umbral moderado más amplio")
        self.click("Guardar como nueva versión")
        self.assertTrue(any("versión 2" in m.value for m in self.app.success))
        self.assertTrue(any("v2" in i.value for i in self.app.info))
        self.fill_profile(tolerance=20, objective="Crecimiento")
        self.evaluate()
        resultado = self.app.session_state["resultado_robo"]
        self.assertEqual(resultado["version_matriz"], 2)
        self.assertEqual(resultado["perfil_riesgo"], "MODERADO")

    def test_admin_rejects_invalid_matrix(self):
        self.navigate("administracion")
        self.app.number_input(key="adm_v1_base_MODERADO_Renta variable").set_value(50)
        self.app.text_input(key="adm_v1_autor").input("docente")
        self.click("Guardar como nueva versión")
        self.assertTrue(any("100" in e.value for e in self.app.error))
        self.assertTrue(any("v1" in i.value for i in self.app.info))


if __name__ == "__main__":
    unittest.main()
