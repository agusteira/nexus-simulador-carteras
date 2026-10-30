import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from nexus.instrument_knowledge import KnowledgeStore, decorate_fund, load_universe, normalize_fund


class KnowledgeTests(unittest.TestCase):
    def test_universe_keeps_share_classes_and_crypto_separate(self):
        items = load_universe()
        ids = {x["canonical_id"] for x in items}
        self.assertIn("FOREIGN_SHARE:MELI:NASDAQ", ids)
        self.assertIn("CEDEAR:MELI:BYMA", ids)
        self.assertIn("CRYPTO:BTC:BITCOIN", ids)
        self.assertIn("CRYPTO_FUND:IBIT:NASDAQ", ids)
        familiar_ids = {x["canonical_id"] for x in items if x["familiar"]}
        self.assertIn("ETF:SPY:NYSE_ARCA", familiar_ids)
        self.assertIn("FOREIGN_SHARE:MELI:NASDAQ", familiar_ids)
        self.assertIn("LOCAL_SHARE:YPFD:BYMA", familiar_ids)
        self.assertIn("ADR:YPF:NYSE", familiar_ids)
        self.assertIn("CRYPTO:BTC:BITCOIN", familiar_ids)
        self.assertNotIn("CRYPTO_FUND:IBIT:NASDAQ", familiar_ids)
        self.assertTrue(all("no afirma que la persona lo conozca" in x["familiarity_basis"] for x in items if x["familiar"]))
        self.assertTrue(all(x["market_metric"] is None for x in items))
        self.assertNotEqual(next(x for x in items if x["canonical_id"].startswith("CRYPTO:"))["canonical_id"],
                            next(x for x in items if x["canonical_id"].startswith("CRYPTO_FUND:"))["canonical_id"])
        items[0]["name"] = "mutated"
        self.assertNotEqual(load_universe()[0]["name"], "mutated")

    def test_fund_normalization_does_not_infer_from_names_or_horizon(self):
        rec = normalize_fund({"fondoId": 4, "claseId": 7, "nombre": "CER USD Bitcoin", "fecha": "2026-10-27",
                              "tipoRenta": "Renta Fija", "horizonte": "Corto plazo"},
                             {"fuente": "fixture", "url": "https://example.test"}, today=date(2026, 10, 29))
        self.assertEqual(rec["canonical_id"], "AR:FCI:4:7")
        self.assertEqual(rec["underlying_id"], "AR:FCI:4")
        self.assertIsNone(rec["category"])
        self.assertEqual(rec["exposure"], "unknown")
        self.assertEqual(rec["settlement_days"], None)
        self.assertEqual(rec["evidence"][0]["data_date"], "2026-10-27")
        self.assertEqual(rec["evidence"][0]["raw_source_fields"]["horizonte"], "Corto plazo")

    def test_exact_renta_variable_and_money_market_taxonomy(self):
        def norm(kind): return normalize_fund({"fondoId":1,"claseId":1,"fecha":"2026-10-29","tipoRenta":kind,"moneda":"Peso Argentino","monedaInversion":"ARS"}, {"url":"u","consultado_en":"2026-10-29T12:00:00+00:00"}, today=date(2026,10,29))
        self.assertEqual(norm("renta variáble")["category"], "Renta variable")
        self.assertEqual(norm("Mercado de Dinero")["category"], "Liquidez inmediata")
        self.assertIsNone(norm("Renta Fija")["category"])
        self.assertEqual(norm("Renta Variable")["quotation_currency"], "ARS")
        self.assertEqual(norm("Renta Variable")["subscription_currency"], "ARS")
        ev = norm("Renta Variable")["evidence"][0]
        self.assertEqual(ev["fields"]["quotation_currency"], "ARS")
        self.assertEqual(ev["raw_source_fields"]["moneda"], "Peso Argentino")
        self.assertIn("canonical_id", ev["fields"])
        self.assertEqual(ev["observed_at"], "2026-10-29T12:00:00+00:00")

    def test_store_versions_expiry_copy_restore_and_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(Path(d) / "k.db")
            record = {"canonical_id":"ETF:TEST:NYSE","validation_status":"proposal","evidence":[{"expires_at":"2026-01-01T00:00:00+00:00"}]}
            saved = store.save(record)
            record["validation_status"] = "validated"
            self.assertEqual(store.latest("ETF:TEST:NYSE")["validation_status"], "expired")
            changed = store.save({"canonical_id":"ETF:TEST:NYSE","validation_status":"proposal","foo":"bar"})
            self.assertEqual(changed["knowledge_version"], 2)
            restored = store.restore("ETF:TEST:NYSE", 1)
            self.assertEqual(restored["knowledge_version"], 3)
            restored_again = store.restore("ETF:TEST:NYSE", 3)
            self.assertEqual(restored_again["knowledge_version"], 4)
            self.assertEqual(len(store.history("ETF:TEST:NYSE")), 4)
            original_count = len(store.history("ETF:TEST:NYSE"))
            store.feedback("ETF:TEST:NYSE", "known", "ya lo conozco")
            store.feedback("ETF:TEST:NYSE", "understood", "entendido")
            self.assertEqual(len(store.history("ETF:TEST:NYSE")), original_count)
            store.feedback("ETF:TEST:NYSE", "correction", "ticker incorrecto")
            latest = store.latest("ETF:TEST:NYSE")
            self.assertEqual(latest["validation_status"], "review")
            self.assertIn("ticker incorrecto", latest["contradictions"])
            with self.assertRaises(ValueError): store.latest("bad value")

    def test_stale_invalid_timestamp_and_nonfinite_records_are_safe(self):
        rec = normalize_fund({"fondoId":1,"claseId":2,"fecha":"not-a-date","tipoRenta":"Renta Fija","inversionMinima":float("nan")}, {"url":"u","consultado_en":"bad-time"}, today=date(2026,10,29))
        self.assertEqual(rec["validation_status"], "expired")
        self.assertIsNone(rec["minimum"])
        with tempfile.TemporaryDirectory() as d:
            store = KnowledgeStore(Path(d) / "bad.db")
            store.save({"canonical_id":"ETF:SAFE:NYSE","evidence":[{"expires_at":"bad-time"}]})
            self.assertEqual(store.latest("ETF:SAFE:NYSE")["validation_status"], "expired")
            with self.assertRaises(ValueError): store.save({"canonical_id":"ETF:NAN:NYSE","value":float("nan")})

    def test_fima_education_exact_names_class_suffixes_and_separate_classes(self):
        def record(name, cls):
            return normalize_fund({"fondoId":"same", "claseId":cls, "nombre":name, "fecha":"2026-10-29", "tipoRenta":"Renta Fija", "inversionMinima":1},
                {"fuente":"API","url":"https://example.test","consultado_en":"2026-10-29T12:00:00+00:00"}, today=date(2026,10,29))
        premium_a=record("FÍMA   PREMIUM - Clase A", "A")
        premium_b=record("FimaPremium -ClaseB", "B")
        self.assertEqual(premium_a["education_id"], "FIMA_PREMIUM")
        self.assertEqual(premium_b["education_id"], "FIMA_PREMIUM")
        self.assertNotEqual(premium_a["canonical_id"], premium_b["canonical_id"])
        self.assertIsNone(premium_a["category"])
        self.assertEqual(premium_a["exposure"], "unknown")
        self.assertIsNone(premium_a["minimum"])
        self.assertIn("minimum",premium_a["missing_fields"])
        curated=[e for e in premium_a["evidence"] if e["kind"]=="curated"]
        self.assertEqual(len(curated),1)
        self.assertIn("category_hint",curated[0]["fields"])
        self.assertNotIn("category",curated[0]["fields"])
        self.assertFalse(any(e["kind"]=="observed" and "category" in e["fields"] for e in premium_a["evidence"]))
        raw_api=next(e for e in premium_a["evidence"] if e["kind"]=="observed")
        self.assertEqual(raw_api["raw_source_fields"]["inversionMinima"],1)
        self.assertNotIn("minimum",raw_api["fields"])
        self.assertNotIn("education_id", decorate_fund({"name":"Fima Premium Plus"}))
        self.assertNotIn("education_id", decorate_fund({"name":"Mi Fima Premium del mes"}))
        self.assertNotIn("education_id", decorate_fund({"name":"Fima Renta en Pesos II"}))
        self.assertEqual(decorate_fund({"name":"  fima RENTA en pesos clase C "})["education_id"],"FIMA_RENTA_PESOS")
        self.assertEqual(decorate_fund({"name":"FimaRentaPesos -ClaseA"})["education_id"],"FIMA_RENTA_PESOS")
        self.assertEqual(decorate_fund({"name":"FimaCapitalPlus -ClaseC"})["education_id"],"FIMA_CAPITAL_PLUS")


if __name__ == "__main__": unittest.main()
