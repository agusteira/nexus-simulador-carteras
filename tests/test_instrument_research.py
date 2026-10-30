import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from nexus.instrument_knowledge import KnowledgeStore, load_universe
from nexus.market_data import MarketDataError
from nexus.instrument_research import ResearchLimits, research_instruments
from nexus.instrument_rules import POLICY_VERSION


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
    def test_familiar_fci_after_many_unknown_api_rows_is_investigated(self):
        source = {"fuente":"API fixture", "url":"https://example.test/fci", "consultado_en":"2026-10-29T12:00:00+00:00", "fondos": []}
        for i in range(100):
            source["fondos"].append({"nombre":f"A Fondo desconocido {i:03}", "fondoId":str(i+1), "claseId":"1",
                "fecha":"2026-10-29", "tipoRenta":"Renta Fija", "moneda":"ARS", "monedaInversion":"ARS", "inversionMinima":1})
        source["fondos"].append({"nombre":"Fima Renta en Pesos - Clase A", "fondoId":"68", "claseId":"1",
            "fecha":"2026-10-29", "tipoRenta":"Renta Fija", "moneda":"ARS", "monedaInversion":"ARS", "inversionMinima":1})
        class FimaProvider:
            def __init__(self): self.calls=[]
            def supports(self, record): return bool(record.get("education_id"))
            def source_key(self, record): return record.get("education_source_url")
            def research(self, record, **kwargs):
                self.calls.append(record["canonical_id"])
                result = dict(record, category="Renta fija inflación", exposure="inflation", exposure_basis="mandate", validation_status="observed", reference_status="identity_observed")
                fields = {"canonical_id":result["canonical_id"], "instrument_type":"FCI", "market":"AR:FCI", "name":result["name"],
                          "category":"Renta fija inflación", "exposure":"inflation", "exposure_basis":"mandate"}
                result["evidence"] = [*result.get("evidence", []), {"source":record["education_source_url"], "url":record["education_source_url"],
                    "fields":fields, "observed_at":"2026-10-29T12:00:00+00:00", "data_date":None,
                    "expires_at":"2026-11-28T12:00:00+00:00", "kind":"observed", "version":"fixture", "source_type":"issuer", "scope":"mandate"}]
                return result
        result = {**RESULT, "cartera_porcentual":{"Renta fija inflación":100}}
        with tempfile.TemporaryDirectory() as directory:
            provider=FimaProvider()
            research=research_instruments(result, SNAPSHOT, [source], provider=provider,
                store=KnowledgeStore(directory+"/knowledge.db"), limits=ResearchLimits(1,16,20), today=date(2026,10,29))
        self.assertTrue(provider.calls)
        self.assertIn("AR:FCI:68:1", provider.calls)
        self.assertIn(POLICY_VERSION, research["policy_version"])
        category=research["categories"][0]
        self.assertEqual(category["educational_selection"]["status"], "REFERENCIA_EDUCATIVA")
        self.assertEqual(category["initial_evaluation"]["original_id"], "AR:FCI:1:1")
        self.assertLessEqual(len(category["educational_selection"]["cards"]),2)
        self.assertTrue(any("FIMA_RENTA_PESOS" in x.get("education_id", "") for x in category["educational_selection"]["cards"]))
        fima = next(x for x in category["educational_selection"]["cards"] if x.get("education_id") == "FIMA_RENTA_PESOS")
        self.assertIsNone(fima.get("minimum"))
        self.assertIn("minimum", fima.get("missing_fields", []))

    def test_spy_can_be_an_educational_reference_when_operations_and_currency_are_unknown(self):
        class SpyProvider:
            def supports(self, record): return record.get("canonical_id") == "ETF:SPY:NYSE_ARCA"
            def source_key(self, record): return "https://example.test/spy"
            def research(self, record, **kwargs):
                result=dict(record, validation_status="observed", reference_status="identity_observed")
                fields={k:result[k] for k in ("canonical_id","instrument_type","market","name")}
                fields.update({"category":"Renta variable", "exposure":"equity", "educational_role":"index_basket"})
                result["category"],result["exposure"]="Renta variable","equity"
                result["educational_role"]="index_basket"
                result["evidence"]=[*result.get("evidence",[]),{"source":"fixture","url":"https://example.test/spy","fields":fields,
                    "observed_at":"2026-10-29T12:00:00+00:00","data_date":None,"expires_at":"2026-11-28T12:00:00+00:00","kind":"observed","source_type":"issuer","scope":"product"}]
                return result
        result={**RESULT,"cartera_porcentual":{"Renta variable":20},"perfil_riesgo":"MODERADO"}
        snapshot={"perfil":{"horizonte":24,"objetivo":"Crecimiento","tolerancia":30,"liquidez":20,"acceso":["local"]}}
        with tempfile.TemporaryDirectory() as directory:
            research=research_instruments(result,snapshot,[],provider=SpyProvider(),store=KnowledgeStore(directory+"/knowledge.db"),
                limits=ResearchLimits(6,16,20),today=date(2026,10,29))
        category=research["categories"][0]
        self.assertEqual(category["decision"],"INFORMACION_INSUFICIENTE")
        card=category["educational_selection"]["cards"][0]
        self.assertEqual(card["canonical_id"],"ETF:SPY:NYSE_ARCA")
        self.assertEqual(card["currency_status"],"unknown")
        self.assertEqual(card["operational_status"],"operación pendiente")

    def test_provider_failure_does_not_fallback_to_unresearched_universe(self):
        class FailureProvider:
            def supports(self, record): return record.get("canonical_id")=="ETF:SPY:NYSE_ARCA"
            def source_key(self, record): return "https://example.test/spy"
            def research(self, record, **kwargs): raise MarketDataError("offline")
        result={**RESULT,"cartera_porcentual":{"Renta variable":20}}
        with tempfile.TemporaryDirectory() as directory:
            research=research_instruments(result,SNAPSHOT,[],provider=FailureProvider(),store=KnowledgeStore(directory+"/knowledge.db"),
                limits=ResearchLimits(6,16,20),today=date(2026,10,29))
        category=research["categories"][0]
        self.assertEqual(category["educational_selection"]["status"],"SIN_REFERENCIA_VERIFICADA")
        self.assertEqual(category["educational_selection"]["cards"],[])
        self.assertTrue(category["educational_selection"]["excluded"])
        self.assertTrue(any("fuente educativa no respondió" in " ".join(item["reasons"]) for item in category["educational_selection"]["excluded"]))

    def test_provider_researches_fci_and_equity_in_same_bounded_run_without_profile(self):
        source={"fuente":"API fixture","url":"https://example.test/fci","consultado_en":"2026-10-29T12:00:00+00:00","fondos":[
            {"nombre":"Fima Renta en Pesos - Clase A","fondoId":"68","claseId":"1","fecha":"2026-10-29","tipoRenta":"Renta Fija","moneda":"ARS","monedaInversion":"ARS","inversionMinima":1}]}
        class CombinedProvider:
            def __init__(self): self.calls=[]
            def supports(self, record): return record.get("education_id") or record.get("canonical_id")=="ETF:SPY:NYSE_ARCA"
            def source_key(self, record): return record.get("education_source_url") or "https://example.test/spy"
            def research(self, record, **kwargs):
                self.calls.append(record["canonical_id"])
                self.assert_private="private-user" not in repr(record)
                result=dict(record,validation_status="observed",reference_status="identity_observed")
                fields={"canonical_id":result["canonical_id"],"instrument_type":result["instrument_type"],"market":result["market"],"name":result["name"]}
                if result["instrument_type"]=="FCI": fields.update({"category":"Renta fija inflación","exposure":"inflation"})
                else: fields.update({"category":"Renta variable","exposure":"equity"})
                result.update({k:v for k,v in fields.items() if k in ("category","exposure")})
                result["evidence"]=[*result.get("evidence",[]),{"source":self.source_key(record),"url":self.source_key(record),"fields":fields,
                    "observed_at":"2026-10-29T12:00:00+00:00","data_date":None,"expires_at":"2026-11-28T12:00:00+00:00","kind":"observed"}]
                return result
        result={**RESULT,"cartera_porcentual":{"Renta variable":50,"Renta fija inflación":50}}
        with tempfile.TemporaryDirectory() as directory:
            provider=CombinedProvider()
            research=research_instruments(result,SNAPSHOT,[source],provider=provider,store=KnowledgeStore(directory+"/knowledge.db"),
                limits=ResearchLimits(6,16,20),today=date(2026,10,29))
        ids=provider.calls
        self.assertTrue(any(x.startswith("AR:FCI:68:") for x in ids))
        self.assertIn("ETF:SPY:NYSE_ARCA",ids)
        self.assertLessEqual(research["search"]["queries"],6)

    def test_default_ars_source_priority_reaches_local_cedears_and_ypf_after_three_fima_urls(self):
        source={"fuente":"API fixture","url":"https://example.test/fci","consultado_en":"2026-10-29T12:00:00+00:00","fondos":[]}
        for fund_id,name in (("68","Fima Renta en Pesos - Clase A"),("540","Fima Capital Plus - Clase A"),("345","Fima Premium - Clase A")):
            source["fondos"].append({"nombre":name,"fondoId":fund_id,"claseId":"A","fecha":"2026-10-29",
                "tipoRenta":"Renta Fija","moneda":"ARS","monedaInversion":"ARS","inversionMinima":1})
        source_urls={"FIMA_RENTA_PESOS":"https://fixture/fima/cer","FIMA_CAPITAL_PLUS":"https://fixture/fima/fx",
                     "FIMA_PREMIUM":"https://fixture/fima/cash","CEDEAR:SPY:BYMA":"https://fixture/caja",
                     "CEDEAR:MELI:BYMA":"https://fixture/comafi","LOCAL_SHARE:YPFD:BYMA":"https://fixture/ypf"}
        class Provider:
            def __init__(self): self.calls=[]
            def supports(self,r): return bool(r.get("education_id")) or r.get("canonical_id") in source_urls
            def source_key(self,r): return source_urls.get(r.get("education_id") or r.get("canonical_id"))
            def research(self,r,**kwargs):
                self.calls.append(r["canonical_id"])
                result=dict(r,validation_status="observed",reference_status="identity_observed")
                if r.get("instrument_type")=="FCI": category,exposure=r["category_hint"],r["exposure_hint"]
                else: category,exposure="Renta variable","equity"
                fields={k:result[k] for k in ("canonical_id","instrument_type","market","name")}
                fields.update({"category":category,"exposure":exposure})
                result.update({"category":category,"exposure":exposure})
                url=self.source_key(r)
                result["evidence"]=[*result.get("evidence",[]),{"source":url,"url":url,"fields":fields,
                    "observed_at":"2026-10-29T12:00:00+00:00","data_date":None,"expires_at":"2026-11-28T12:00:00+00:00","kind":"observed"}]
                return result
        result={**RESULT,"cartera_porcentual":{"Renta variable":40,"Renta fija inflación":20,"Renta fija cambiaria":20,"Liquidez inmediata":20}}
        snapshot={"perfil":{"horizonte":60,"objetivo":"Crecimiento","tolerancia":30,"liquidez":20,"acceso":["local","international"]}}
        with tempfile.TemporaryDirectory() as directory:
            provider=Provider()
            research=research_instruments(result,snapshot,[source],provider=provider,store=KnowledgeStore(directory+"/knowledge.db"),
                limits=ResearchLimits(),today=date(2026,10,29))
        self.assertEqual(research["search"]["queries"],6)
        self.assertTrue(any(x.startswith("AR:FCI:68:") for x in provider.calls))
        self.assertIn("CEDEAR:SPY:BYMA",provider.calls)
        self.assertIn("CEDEAR:MELI:BYMA",provider.calls)
        self.assertIn("LOCAL_SHARE:YPFD:BYMA",provider.calls)
        self.assertNotIn("ETF:SPY:NYSE_ARCA",provider.calls)
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
                store=KnowledgeStore(directory + "/knowledge.db"), limits=ResearchLimits(4, 10, 5),
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
