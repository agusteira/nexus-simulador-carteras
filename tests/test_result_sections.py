"""Product checks for the three native result sections and research cards."""
from datetime import datetime, timezone
import os
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
                "canonical_id": "ADR:YPF:NYSE", "name": "YPF S.A.", "instrument_type": "ADR",
                "ticker": "YPF", "market": "NYSE", "category": name, "exposure": "equity",
                "description": "ADR de YPF en el mercado estadounidense.",
                "educational_description": "Es un certificado que representa acciones de YPF en otro mercado.",
                "reason": "La fuente confirmó identidad y clasificación; no es una selección operativa.",
                "missing_fields": ["costs", "holdings", "access"], "operational_status": "operación pendiente",
                "currency_status": "unknown", "familiar": True, "knowledge_version": 1,
                "evidence": [{"source": "Fixture documentado", "url": "https://example.test/ypf",
                              "kind": "observed", "observed_at": datetime.now(timezone.utc).isoformat(),
                              "data_date": None, "version": "fixture-1", "fields": {"name": "YPF S.A."}}],
            }]
        categories.append({
            "category": name, "decision": "INFORMACION_INSUFICIENTE", "selected": [],
            "educational_selection": {"status": "REFERENCIA_EDUCATIVA" if cards else "SIN_REFERENCIA_VERIFICADA",
                                      "cards": cards, "excluded": [], "rule_ids": [], "reasons": []},
        })
        # Old schema stays in the JSON for compatibility, but never becomes a UI card.
        legacy_categories.append({"categoria": name, "peso": weight, "monto_asignado": result.get("capital", 0) * weight / 100,
                                  "ejemplos": [{"nombre": "Fondo alfabético legacy"}],
                                  "alternativas": [{"nombre": "Alternativa legacy"}], "diagnostico": {"registros_revisados": 1}})
    research = {"execution_id": "test-run", "policy_version": "test-policy", "universe_version": "test-universe",
                "categories": categories, "educational_universe": [],
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
        target = next(item for item in self.app.expander if item.label.startswith("Renta variable ·") and "referencia investigada" in item.label)
        self.assertFalse(target.proto.expanded)
        self.assertEqual(self.query_mock.call_count, 1)

    def test_researched_card_is_visible_but_legacy_examples_are_not(self):
        saved = self.app.session_state["resultado_robo"]["ejemplos_instrumentos"]
        self.assertTrue(saved["categorias"][0]["ejemplos"] or saved["categorias"][0]["alternativas"])
        text_values = [item.value for item in [*self.app.text, *self.app.markdown] if isinstance(item.value, str)]
        self.assertTrue(any("Instrumentos para entender tu cartera" in value for value in text_values))
        self.assertTrue(any("YPF · ADR de YPF" in value for value in text_values))
        self.assertFalse(any("Fondo alfabético legacy" in value or "Alternativa legacy" in value for value in text_values))

    def test_tab_navigation_does_not_repeat_research_query(self):
        self.app.button(key="nav_auditoria").click().run()
        self.app.button(key="nav_resultado").click().run()
        self.assertEqual(self.query_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
