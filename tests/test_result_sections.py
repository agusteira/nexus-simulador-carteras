"""Product checks for the three native result sections and research cards."""
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def _research_snapshot(result, snapshot, **kwargs):
    categories = []
    legacy_categories = []
    for name, weight in result.get("cartera_porcentual", {}).items():
        if weight <= 0:
            continue
        cards = []
        if name == "Renta variable":
            cards = [{
                "canonical_id": "CEDEAR:XYZ:BYMA", "name": "Empresa XYZ de prueba", "instrument_type": "CEDEAR",
                "ticker": "XYZ", "market": "BYMA", "category": name, "exposure": "equity",
                "quotation_currency": "ARS", "subscription_currency": "unknown",
                "description": "Registro sintético para probar el render de una selección.",
                "missing_fields": [], "knowledge_version": 1,
                "evidence": [{"source": "Fixture sintético", "url": "https://example.test/xyz",
                              "kind": "observed", "observed_at": datetime.now(timezone.utc).isoformat(),
                              "data_date": "2026-10-29", "version": "fixture-1",
                              "fields": {"name": "Empresa XYZ de prueba", "category": name,
                                         "exposure": "equity", "instrument_type": "CEDEAR", "ticker": "XYZ",
                                         "market": "BYMA", "quotation_currency": "ARS"}}],
            }]
        selected = []
        evaluated = []
        comparison = {"reason": "No hay datos suficientes para seleccionar."}
        category_decision = "INFORMACION_INSUFICIENTE"
        if cards:
            selected = [cards[0]]
            evaluated = [{"canonical_id": cards[0]["canonical_id"], "record": cards[0], "eligible": True,
                          "decision": "CONSERVAR_CANDIDATO", "selection_scope": "instrument_recommendation",
                          "reasons": ["Cotización en pesos confirmada por el fixture."], "selection_explanation": ["Cotización en pesos confirmada por el fixture."],
                          "missing_fields": [], "execution_checks": {"status": "PENDIENTE_INTERMEDIARIO",
                              "missing_fields": ["subscription_currency", "broker_fee"],
                              "reasons": ["Confirmar moneda de suscripción y comisión con el intermediario."]},
                          "ranking_factors": {"riesgo": 1, "costos": 2}}]
            category_decision = "CONSERVAR_CANDIDATO"
            comparison = {"original": evaluated[0], "alternative": evaluated[0], "reason": "Se conserva el candidato elegible."}
        categories.append({
            "category": name, "decision": category_decision,
            "selected": selected, "evaluated": evaluated, "comparison": comparison,
            "educational_selection": {"status": "REFERENCIA_EDUCATIVA" if cards else "SIN_REFERENCIA_VERIFICADA",
                                      "cards": [{"canonical_id": "ETF:SPY:NYSE_ARCA", "name": "SPY educativo"}],
                                      "excluded": [], "rule_ids": [], "reasons": []},
        })
        # Old schema stays in the JSON for compatibility, but never becomes a UI card.
        legacy_categories.append({"categoria": name, "peso": weight, "monto_asignado": result.get("capital", 0) * weight / 100,
                                  "ejemplos": [{"nombre": "Fondo alfabético legacy"}],
                                  "alternativas": [{"nombre": "Alternativa legacy"}], "diagnostico": {"registros_revisados": 1}})
    crypto_universe = [
        {"canonical_id": "CRYPTO:BTC", "name": "Bitcoin", "instrument_type": "CRYPTO",
         "educational_description": "Activo digital Bitcoin."},
        {"canonical_id": "CRYPTO_FUND:IBIT", "name": "iShares Bitcoin Trust", "instrument_type": "CRYPTO_FUND",
         "educational_description": "Fondo con exposición a Bitcoin."},
    ]
    research = {"schema_version": 4, "scope": "ARGENTINA_SIN_BROKER", "execution_id": "test-run", "policy_version": "test-policy", "universe_version": "test-universe",
                "source_coverage": [{"source": "Catálogo FCI", "url": "https://example.test/fci",
                                     "published_at": "2026-10-29", "candidate_count": 0, "classes": ["FCI"]}],
                "categories": categories, "educational_universe": crypto_universe,
                "search": {"queries": 1, "limits": {"max_queries": 4}, "elapsed_seconds": 0.1, "errors": []}}
    return {"ejecucion_id": "test-run", "consultado_en": datetime.now(timezone.utc).isoformat(),
            "moneda": result.get("moneda", "ARS"), "ventana_datos_dias": 7,
            "categorias": legacy_categories, "fuentes": [], "errores_fuente": [],
            "investigacion": research, "criterio_orden": "fixture", "advertencia": "fixture"}


class ResultSectionsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_dir = directory.name
        env = patch.dict(os.environ, {"NEXUS_DATA_DIR": self.data_dir})
        env.start()
        self.addCleanup(env.stop)
        public_source = patch("nexus.instruments.ArgentinaDatosClient.fund_catalog", return_value={
            "fondos": [], "fuente": "Fixture", "url": "https://example.test/fci", "consultado_en": "2026-10-29T12:00:00+00:00"})
        public_source.start()
        self.addCleanup(public_source.stop)
        ref = patch("nexus.instrument_research.ReferenceProvider.research", side_effect=lambda record, **kwargs: record)
        ref.start()
        self.addCleanup(ref.stop)
        self.query = patch("nexus.ui.instrument_examples.query_examples", side_effect=_research_snapshot)
        self.query_mock = self.query.start()
        self.addCleanup(self.query.stop)
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self._fill_and_evaluate()

    def _fill_and_evaluate(self):
        self.app.button(key="nav_perfil").click().run()
        states = self.app._tree.get_widget_states()
        widget = states.widgets.add()
        widget.id = self.app.get("bidi_component")[0].proto.id
        import json
        widget.json_value = json.dumps({"value": "250000,00"})
        self.app._run(states)
        self.app.select_slider(key="perfil_tolerancia").set_value(30).run()
        self.app.selectbox(key="perfil_objetivo").set_value("Crecimiento").run()
        next(button for button in self.app.button if "Guardar perfil y continuar" in button.label).click().run()
        self.app.checkbox(key="escenario_confirmado").check().run()
        next(button for button in self.app.button if "Guardar escenario y revisar" in button.label).click().run()
        execute = next(button for button in self.app.button if "Ejecutar evaluación" in button.label)
        execute.click().run()
        self.assertFalse(self.app.exception, [item.message for item in self.app.exception])

    def test_three_native_tabs_and_research_categories_start_collapsed(self):
        labels = [tab.label for tab in self.app.get("tab")]
        self.assertEqual(labels, ["Resultado de la simulación", "Del porcentaje a ejemplos reales", "Cómo se interpretaron tus respuestas"])
        target = next(item for item in self.app.expander if item.label.startswith("Renta variable ·") and "opción seleccionada" in item.label)
        self.assertFalse(target.proto.expanded)
        self.assertEqual(self.query_mock.call_count, 1)

    def test_researched_card_is_visible_but_legacy_examples_are_not(self):
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.assertTrue(saved["categorias"][0]["ejemplos"] or saved["categorias"][0]["alternativas"])
        text_values = self._visible_text()
        self.assertTrue(any("Instrumentos recomendados para tu simulación" in value for value in text_values))
        self.assertTrue(any("Empresa XYZ de prueba" in value for value in text_values))
        self.assertTrue(any("Moneda en la que se informa el precio o la clase del fondo: coincide con la simulación" in value for value in text_values))
        self.assertTrue(any("Con qué moneda podés ingresar el dinero: confirmalo con tu intermediario." in value for value in text_values))
        self.assertTrue(any("opciones de inversión del mercado argentino" in value for value in text_values))
        self.assertFalse(any("Fondo alfabético legacy" in value or "Alternativa legacy" in value for value in text_values))
        self.assertFalse(any("SPY educativo" in value for value in text_values))
        saved_json = json.dumps(saved, ensure_ascii=False)
        self.assertIn("CRYPTO:BTC", saved_json)
        self.assertIn("CRYPTO_FUND:IBIT", saved_json)
        self.assertFalse(any("Bitcoin" in value or "iShares Bitcoin Trust" in value for value in text_values))

    def _set_research(self, research):
        result = self.app.session_state["resultado_robo"]
        result["ejemplos_instrumentos"]["investigacion"] = research
        self.app.session_state["resultado_robo"] = result
        self.app.run()
        self.assertFalse(self.app.exception, [item.message for item in self.app.exception])

    def _visible_text(self):
        return [item.value for kind in (self.app.text, self.app.markdown, self.app.info, self.app.warning, self.app.caption)
                for item in kind if isinstance(item.value, str)]

    @staticmethod
    def _equity_category(research):
        return next(item for item in research["categories"] if item.get("category") == "Renta variable")

    def test_educational_cards_ignored_and_old_schema_requests_update(self):
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        research = saved["investigacion"]
        category = self._equity_category(research)
        category["selected"] = []
        category["evaluated"] = []
        self._set_research(research)
        self.assertFalse(any("SPY educativo" in value for value in self._visible_text()))
        research["schema_version"] = 3
        self._set_research(research)
        text_values = self._visible_text()
        self.assertTrue(any("versión anterior" in value and "Actualizá" in value for value in text_values))
        self.assertFalse(any("SPY educativo" in value or "Empresa XYZ de prueba" in value for value in text_values))

    def test_unknown_but_eligible_selected_candidate_is_rendered(self):
        research = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]["investigacion"]
        candidate = {"canonical_id": "ETF:XYZ:XNAS", "name": "Fondo XYZ", "instrument_type": "CEDEAR",
                     "market": "XNAS", "educational_description": "Descripción general.", "quotation_currency": "ARS"}
        category = self._equity_category(research)
        category["selected"] = [candidate]
        category["evaluated"] = [{"canonical_id": "ETF:XYZ:XNAS", "record": candidate,
                                                        "eligible": True, "decision": "CONSERVAR_CANDIDATO",
                                                        "selection_scope": "instrument_recommendation", "missing_fields": []}]
        category["decision"] = "CONSERVAR_CANDIDATO"
        self._set_research(research)
        self.assertTrue(any("Fondo XYZ" in value for value in self._visible_text()))

    def test_malformed_selected_candidate_is_not_rendered(self):
        research = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]["investigacion"]
        candidate = {"canonical_id": "ETF:BAD:XNAS", "name": "Candidato inválido", "instrument_type": "CEDEAR"}
        category = self._equity_category(research)
        category["selected"] = [candidate]
        category["evaluated"] = [{"canonical_id": "ETF:BAD:XNAS", "record": candidate,
                                                        "eligible": True, "decision": "SELECCIONADO",
                                                        "selection_scope": "instrument_recommendation", "missing_fields": []}]
        category["decision"] = "CONSERVAR_CANDIDATO"
        self._set_research(research)
        text_values = self._visible_text()
        self.assertFalse(any("Candidato inválido" in value for value in text_values))
        self.assertTrue(any("no pudimos confirmar que haya pasado todos los controles" in value for value in text_values))

    def test_old_v3_scope_requests_update(self):
        research = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]["investigacion"]
        research["schema_version"] = 3
        self._set_research(research)
        self.assertTrue(any("versión anterior" in value and "Actualizá" in value for value in self._visible_text()))

    def test_broker_checks_do_not_block_recommendation_but_required_facts_do(self):
        research = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]["investigacion"]
        self.assertTrue(any("Empresa XYZ de prueba" in value for value in self._visible_text()))
        category = self._equity_category(research)
        candidate = category["selected"][0]
        evaluation = category["evaluated"][0]
        evaluation["missing_fields"] = ["quotation_currency"]
        self._set_research(research)
        self.assertFalse(any("Empresa XYZ de prueba" in item.value for item in self.app.markdown if isinstance(item.value, str)))
        self.assertTrue(any("Sin selección" in item.label for item in self.app.expander))

    def test_tab_navigation_does_not_repeat_research_query(self):
        self.app.button(key="nav_auditoria").click().run()
        self.app.button(key="nav_resultado").click().run()
        self.assertEqual(self.query_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
