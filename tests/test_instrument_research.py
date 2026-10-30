import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from nexus.instrument_knowledge import KnowledgeStore, load_universe
from nexus.market_data import MarketDataError
from nexus.instrument_research import ResearchLimits, research_instruments


RESULT = {"capital": 100000, "moneda": "ARS", "perfil_riesgo": "MODERADO",
          "cartera_porcentual": {"Renta variable": 20}}
SNAPSHOT = {"perfil": {"capital": 100000, "moneda": "ARS", "usuario_id": "private-user",
                        "horizonte": 60, "objetivo": "Crecimiento"},
            "escenario": {"notas": "private context"}}


class Provider:
    def __init__(self): self.calls = []
    def research(self, record, **kwargs):
        self.calls.append((record.copy(), kwargs))
        return record


class InstrumentResearchTests(unittest.TestCase):
    def test_shared_source_refresh_counts_once_and_does_not_repeat_failure(self):
        seeds = [r for r in load_universe() if r.get("ticker") == "MELI"]
        class SharedProvider:
            def __init__(self, fail=False): self.calls, self.fail = [], fail
            def supports(self, record): return True
            def source_key(self, record): return "https://example.test/shared"
            def research(self, record, **kwargs):
                self.calls.append(kwargs["refresh"])
                if self.fail: raise MarketDataError("source unavailable")
                return {**record, "reference_status": "identity_observed"}
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory, patch("nexus.instrument_research.load_universe", return_value=seeds):
                provider = SharedProvider(fail)
                research = research_instruments(RESULT, SNAPSHOT, [], refresh=True, provider=provider,
                    store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(1, 10, 2))
                self.assertEqual(research["search"]["queries"], 1)
                self.assertEqual(provider.calls, [True] if fail else [True, False])
                if fail:
                    self.assertTrue(all(r["availability"] == "source_unavailable" for r in research["educational_universe"]))

    def test_limits_bound_reference_queries_and_keep_input_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider()
            research = research_instruments(RESULT, SNAPSHOT, [], provider=provider,
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(1, 10, 5),
                today=date(2026, 10, 29))
        self.assertLessEqual(len(provider.calls), 1)
        self.assertEqual(research["search"]["queries"], len(provider.calls))
        self.assertEqual(research["inputs"], SNAPSHOT)
        self.assertEqual(research["expert_review"], "pending")
        self.assertTrue(all("private-user" not in repr(call[0]) for call in provider.calls))

    def test_zero_query_limit_does_not_call_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Provider()
            research = research_instruments(RESULT, SNAPSHOT, [], provider=provider,
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(0, 1, 2),
                today=date(2026, 10, 29))
        self.assertEqual(provider.calls, [])
        self.assertEqual(research["search"]["queries"], 0)
        self.assertEqual(research["categories"][0]["category"], "Renta variable")

    def test_store_constructor_failure_keeps_ephemeral_research_alive(self):
        with patch("nexus.instrument_research.KnowledgeStore", side_effect=OSError("private path")):
            research = research_instruments(RESULT, SNAPSHOT, [], provider=False,
                limits=ResearchLimits(0, 1, 6), today=date(2026, 10, 29))
        self.assertEqual(len(research["categories"]), 1)
        self.assertTrue(any("almacenamiento local" in e for e in research["search"]["errors"]))

    def test_educational_universe_includes_reference_checked_copy(self):
        class FoundProvider(Provider):
            def research(self, record, **kwargs):
                result = record.copy()
                result["reference_status"] = "identity_observed"
                result["evidence"] = [*result.get("evidence", []), {"source": "fixture", "fields": {"ticker": result["ticker"]}, "kind": "observed", "expires_at": "2026-12-01T00:00:00+00:00"}]
                return result
        with tempfile.TemporaryDirectory() as directory:
            research = research_instruments(RESULT, SNAPSHOT, [], provider=FoundProvider(),
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(2, 10, 5),
                today=date(2026, 10, 29))
        spy = next(x for x in research["educational_universe"] if x["canonical_id"] == "ETF:SPY:NYSE_ARCA")
        self.assertEqual(spy["availability"], "identity_confirmed")
        self.assertTrue(any(e.get("source") == "fixture" for e in spy["evidence"]))

    def test_no_expand_event_when_category_has_no_curated_candidates(self):
        result = {**RESULT, "cartera_porcentual": {"Renta fija inflación": 100}}
        with tempfile.TemporaryDirectory() as directory:
            research = research_instruments(result, SNAPSHOT, [], provider=False,
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(0, 10, 8),
                today=date(2026, 10, 29))
        self.assertEqual(research["search"]["events"], [])
        self.assertEqual(research["categories"][0]["decision"], "INFORMACION_INSUFICIENTE")

    def test_fresh_api_field_replaces_same_source_cached_value(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(directory + "/knowledge.db")
            source = {"fuente": "Fixture", "url": "https://example.test/fci", "version": "1", "consultado_en": "2026-10-29T12:00:00+00:00"}
            fund = {"nombre": "Fondo V", "fondoId": "10", "claseId": "2", "fecha": "2026-10-29",
                    "tipoRenta": "Renta Variable", "moneda": "ARS", "monedaInversion": "ARS", "inversionMinima": 100}
            old = research_instruments(RESULT, SNAPSHOT, [{**source, "fondos": [fund]}], provider=False,
                store=store, limits=ResearchLimits(0, 10, 5), today=date(2026, 10, 29))
            fund["inversionMinima"] = 250
            updated = research_instruments(RESULT, SNAPSHOT, [{**source, "fondos": [fund]}], provider=False,
                store=store, limits=ResearchLimits(0, 10, 5), today=date(2026, 10, 29))
        record = next(x["record"] for x in updated["categories"][0]["evaluated"] if x["canonical_id"] == "AR:FCI:10:2")
        self.assertEqual(record["minimum"], 250)
        self.assertGreaterEqual(record["knowledge_version"], 2)

    def test_user_correction_remains_reviewed_after_new_catalog_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(directory + "/knowledge.db")
            source = {"fuente": "Fixture", "url": "https://example.test/fci", "version": "1", "consultado_en": "2026-10-29T12:00:00+00:00"}
            fund = {"nombre": "Fondo V", "fondoId": "11", "claseId": "2", "fecha": "2026-10-29",
                    "tipoRenta": "Renta Variable", "moneda": "ARS", "monedaInversion": "ARS", "inversionMinima": 100}
            first = research_instruments(RESULT, SNAPSHOT, [{**source, "fondos": [fund]}], provider=False,
                store=store, limits=ResearchLimits(0, 10, 5), today=date(2026, 10, 29))
            cid = first["categories"][0]["evaluated"][0]["canonical_id"]
            store.feedback(cid, "correction", "el mínimo estaba mal")
            fund["inversionMinima"] = 999
            latest = research_instruments(RESULT, SNAPSHOT, [{**source, "fondos": [fund]}], provider=False,
                store=store, limits=ResearchLimits(0, 10, 5), today=date(2026, 10, 29))
        record = next(x["record"] for x in latest["categories"][0]["evaluated"] if x["canonical_id"] == "AR:FCI:11:2")
        self.assertEqual(record["minimum"], 100)
        self.assertEqual(record["validation_status"], "review")

    def test_generic_fixed_fund_is_retained_as_original_in_both_fixed_categories(self):
        result = {**RESULT, "cartera_porcentual": {"Renta fija inflación": 50, "Renta fija cambiaria": 50}}
        source = {"fuente": "Fixture", "url": "https://example.test/fci", "consultado_en": "2026-10-29T12:00:00+00:00", "fondos": [
            {"nombre": "Fondo renta fija", "fondoId": "20", "claseId": "3", "fecha": "2026-10-29",
             "tipoRenta": "Renta Fija", "moneda": "ARS", "monedaInversion": "ARS", "inversionMinima": 1}]}
        with tempfile.TemporaryDirectory() as directory:
            research = research_instruments(result, SNAPSHOT, [source], provider=False,
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(0, 10, 8),
                today=date(2026, 10, 29))
        originals = [category["original_id"] for category in research["categories"]]
        self.assertEqual(originals, ["AR:FCI:20:3", "AR:FCI:20:3"])
        self.assertTrue(all(category["evaluated"][0]["decision"] == "INFORMACION_INSUFICIENTE" for category in research["categories"]))


if __name__ == "__main__":
    unittest.main()
