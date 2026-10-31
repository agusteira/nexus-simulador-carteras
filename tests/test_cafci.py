import json
import unittest
from datetime import date, datetime, timezone

from nexus.cafci import CAFCIClient, CAFCIReferenceProvider, CATALOG_URL, _cache, _normalize
from nexus.instrument_rules import evaluate_candidate
from nexus.market_data import MarketDataError


CATALOG_FIXTURE = {
    "generated_at": "2026-10-29T20:31:36-03:00",
    "total_fondos": 5,
    "total_clases": 6,
    "fondos": [
        {"id": 11, "nombre": "Fondo variable", "estado": 1, "objetivo": "Invertir en acciones",
         "dias_liquidacion": 2, "moneda": {"id": 1, "nombre": "Peso Argentina"},
         "mm_puro": False, "mm_indice": False, "tipo_renta_mixta": None, "codigo_cnv": 881,
         "tipo_renta": {"id": 2, "nombre": "Renta Variable"}, "horizonte": {"id": 1, "nombre": "Corto Plazo"},
         "duration": {"id": 1, "nombre": "No Registrada"}, "benchmark": {"id": 0, "nombre": "No Registrado"},
         "clases": [{"id": 101, "nombre": "Fondo variable - Clase A", "moneda": {"id": 1, "nombre": "Peso Argentina"},
                     "inversion_minima": 1000, "rg384": False, "codigo_cnv": 101,
                     "honorarios": {"administracion_gerente": "0.5", "administracion_depositaria": "0.25",
                                    "gasto_ordinario_gestion": "0.1", "ingreso": "0.0", "rescate": None},
                     "suscripcion": True, "liquidez": True, "log_abierto": True},
                    {"id": 102, "nombre": "Fondo variable - Clase B", "moneda": {"id": 2, "nombre": "Dolar Estadounidense"},
                     "inversion_minima": None, "honorarios": None, "suscripcion": True, "liquidez": True, "log_abierto": True},
                    {"id": 103, "nombre": "Clase cerrada", "moneda": {"id": 1, "nombre": "Peso Argentina"},
                     "inversion_minima": 0, "suscripcion": True, "liquidez": True, "log_abierto": False}]},
        {"id": 12, "nombre": "Fondo MM", "estado": 1, "objetivo": "Mercado de dinero",
         "dias_liquidacion": 0, "moneda": {"id": 1, "nombre": "Peso Argentina"},
         "tipo_renta": {"id": 4, "nombre": "Mercado de Dinero"}, "clases": [
             {"id": 201, "nombre": "Fondo MM", "moneda": {"id": 1, "nombre": "Peso Argentina"},
              "inversion_minima": 0, "honorarios": {}, "suscripcion": True, "liquidez": True, "log_abierto": True}]},
        {"id": 13, "nombre": "Cartera CER", "estado": 1,
         "objetivo": "Administrar títulos públicos CER para obtener rendimientos reales",
         "dias_liquidacion": 1, "moneda": {"id": 1, "nombre": "Peso Argentina"},
         "tipo_renta": {"id": 3, "nombre": "Renta Fija"}, "clases": [
             {"id": 301, "nombre": "Cartera CER - Clase A", "moneda": {"id": 1, "nombre": "Peso Argentina"},
              "inversion_minima": 5000, "honorarios": {"administracion_gerente": "0.1"},
              "suscripcion": True, "liquidez": True, "log_abierto": True}]},
        {"id": 14, "nombre": "Cobertura de cambio", "estado": 1,
         "objetivo": "Cobertura del capital por movimientos del tipo de cambio oficial mediante instrumentos Dollar Linked",
         "dias_liquidacion": 1, "moneda": {"id": 1, "nombre": "Peso Argentina"},
         "tipo_renta": {"id": 5, "nombre": "Renta Mixta"}, "clases": [
             {"id": 401, "nombre": "Cobertura de cambio - Clase A", "moneda": {"id": 1, "nombre": "Peso Argentina"},
              "inversion_minima": 1000, "honorarios": {"administracion_gerente": "0.2"},
              "suscripcion": True, "liquidez": True, "log_abierto": True}]},
        {"id": 15, "nombre": "Inactivo", "estado": 0, "clases": [
            {"id": 501, "nombre": "Inactivo", "log_abierto": True}]},
    ],
}

DETAIL_FIXTURE = b'''<html><div id="cartera"><h2>Composicion</h2>
<div class="valores">Valores al 09/10/2026</div>
<div id="pie-chart"><canvas data-pie-chart-items-value="[{&quot;nombre&quot;:&quot;Bono Boncer TZXS7&quot;,&quot;porcentaje&quot;:23.4},{&quot;nombre&quot;:&quot;Resto de Activos&quot;,&quot;porcentaje&quot;:76.6}]"></canvas></div>
</div></html>'''


class FakeResponse:
    def __init__(self, body, url):
        self.body, self.url = body, url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, request, timeout=0):
        self.calls.append((request.full_url, timeout))
        value = self.mapping[request.full_url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            body, final_url = value
        else:
            body, final_url = value, request.full_url
        return FakeResponse(body, final_url)


class CAFCTest(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def _client(self, mapping, timeout=8, clock=lambda: 100):
        return CAFCIClient(timeout=timeout, opener=FakeOpener(mapping), clock=clock, daily_client=False)

    def test_catalog_normalizes_only_active_open_classes_and_keeps_unknowns(self):
        opener = FakeOpener({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()})
        result = CAFCIClient(opener=opener, clock=lambda: 1, daily_client=False).fund_catalog(today=date(2026, 10, 30))
        records = result["normalized_records"]
        self.assertEqual(result["fuente"], "CAFCI")
        self.assertEqual(result["fondos"], [])
        self.assertEqual(result["source_fund_count"], 4)
        self.assertEqual(result["source_class_count"], 5)
        self.assertEqual(len(records), 5)
        ids = [r["canonical_id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("AR:FCI:11:103", ids)
        self.assertFalse(any(r["cafci_fund_id"] == 15 for r in records))
        self.assertFalse(any("clases" in f for f in result["fondos"]))
        var_a = next(r for r in records if r["canonical_id"] == "AR:FCI:11:101")
        var_b = next(r for r in records if r["canonical_id"] == "AR:FCI:11:102")
        self.assertEqual(var_a["category"], "Renta variable")
        self.assertEqual(var_a["exposure"], "equity")
        self.assertEqual(var_a["minimum"], 1000.0)
        self.assertEqual(var_a["raw_fees"]["administracion_gerente"], "0.5")
        self.assertEqual(var_a["fund_fee_annual_pct"], 0.85)
        self.assertEqual(var_a["fund_fee_components_annual_pct"]["gasto_ordinario_gestion"], 0.1)
        self.assertEqual(var_a["entry_fee_pct"], 0)
        self.assertIsNone(var_a["redemption_fee_pct"])
        self.assertTrue(var_a["fund_open"])
        self.assertTrue(var_a["subscription_open"])
        self.assertTrue(var_a["redemption_open"])
        self.assertFalse(var_a["mm_pure"])
        self.assertEqual(var_a["raw_metadata"]["codigo_cnv"], 101)
        self.assertIsNone(var_a["costs"])
        self.assertIsNone(var_b["minimum"])
        self.assertEqual(var_b["quotation_currency"], "USD")
        self.assertIsNone(var_b["subscription_currency"])
        self.assertEqual(var_b["missing_fields"][0], "subscription_currency")
        self.assertEqual(var_a["settlement_days"], 2)
        self.assertEqual(var_a["liquidity"], "unknown")

    def test_observed_catalog_evidence_is_recognized_by_candidate_evaluator(self):
        result = self._client({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()}).fund_catalog(today=date(2026, 10, 30))
        record = next(r for r in result["normalized_records"] if r["canonical_id"] == "AR:FCI:11:101")
        outcome = evaluate_candidate(record, {}, today=date(2026, 10, 30))
        missing = outcome["missing_fields"]
        self.assertNotIn("category_evidence", missing)
        self.assertNotIn("quotation_currency_evidence", missing)
        self.assertNotIn("minimum_evidence", missing)
        self.assertIn("subscription_currency", missing)
        self.assertIn("costs", missing)
        self.assertIn("access_authorization", missing)
        evidence = next(ev for ev in record["evidence"] if ev["kind"] == "observed")
        self.assertEqual(evidence["expires_at"], "2026-11-05T23:59:59+00:00")

    def test_money_market_does_not_claim_immediate_liquidity_and_zero_minimum_is_explicit(self):
        result = self._client({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()}).fund_catalog(today=date(2026, 10, 30))
        mm = next(r for r in result["normalized_records"] if r["cafci_fund_id"] == 12)
        self.assertEqual(mm["category"], "Liquidez inmediata")
        self.assertEqual(mm["exposure"], "money_market")
        self.assertEqual(mm["liquidity"], "unknown")
        self.assertEqual(mm["settlement_days"], 0)
        self.assertEqual(mm["minimum"], 0.0)
        self.assertIsNone(mm["fund_fee_annual_pct"])
        self.assertIsNone(mm["costs"])

    def test_mandate_hints_are_not_inferred_from_fund_or_class_name(self):
        result = self._client({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()}).fund_catalog(today=date(2026, 10, 30))
        cer = next(r for r in result["normalized_records"] if r["cafci_fund_id"] == 13)
        fx = next(r for r in result["normalized_records"] if r["cafci_fund_id"] == 14)
        self.assertEqual(cer["category"], "Renta fija inflación")
        self.assertEqual(cer["exposure"], "inflation")
        self.assertEqual(cer["exposure_basis"], "mandate")
        self.assertEqual(cer["category_hint"], cer["category"])
        self.assertIn("actual_exposure_or_holdings", cer["missing_fields"])
        self.assertEqual(fx["category"], "Renta fija cambiaria")
        self.assertEqual(fx["exposure"], "fx")
        self.assertEqual(fx["exposure_basis"], "mandate")
        unknown = next(r for r in result["normalized_records"] if r["cafci_fund_id"] == 11)
        self.assertIsNone(unknown["category_hint"])

    def test_mandate_can_have_both_hints_and_currency_label_keeps_mep_or_cable(self):
        fund = {"id": 99, "nombre": "Nombre comercial irrelevante", "estado": 1,
                "objetivo": "Administrar bonos CER y cobertura dólar-linked", "tipo_renta": {"nombre": "Renta Fija"},
                "moneda": {"nombre": "Dolar Estadounidense Cable"}, "horizonte": {"nombre": "Mediano Plazo"}}
        klass = {"id": 990, "nombre": "Clase A", "log_abierto": True,
                 "moneda": {"nombre": "Dolar Estadounidense Cable"}, "honorarios": {}}
        record = _normalize(fund, klass, datetime(2026, 10, 29, tzinfo=timezone.utc),
                            "2026-10-30T00:00:00+00:00", CATALOG_URL)
        self.assertIsNone(record["category"])
        self.assertEqual(record["category_hints"], ["Renta fija inflación", "Renta fija cambiaria"])
        self.assertEqual(record["exposure_basis"], "mandate")
        self.assertEqual(record["fund_currency_label"], "Dolar Estadounidense Cable")
        self.assertIsNone(record["quotation_currency"])

    def test_catalog_rejects_future_and_stale_publication_dates(self):
        for stamp in ("2026-10-31T00:00:00Z", "2026-10-20T00:00:00Z"):
            payload = dict(CATALOG_FIXTURE, generated_at=stamp)
            with self.subTest(stamp=stamp), self.assertRaises(MarketDataError):
                self._client({CATALOG_URL: json.dumps(payload).encode()}).fund_catalog(today=date(2026, 10, 30))

    def test_catalog_requires_timezone_and_timeout_is_safe(self):
        payload = dict(CATALOG_FIXTURE, generated_at="2026-10-29T20:31:36")
        with self.assertRaises(MarketDataError):
            self._client({CATALOG_URL: json.dumps(payload).encode()}).fund_catalog(today=date(2026, 10, 30))
        with self.assertRaises(MarketDataError):
            self._client({CATALOG_URL: TimeoutError("timeout")}).fund_catalog(today=date(2026, 10, 30))

    def test_catalog_cache_and_timeout_forwarding(self):
        opener = FakeOpener({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()})
        client = CAFCIClient(timeout=3, opener=opener, clock=lambda: 10, daily_client=False)
        first = client.fund_catalog(today=date(2026, 10, 30))
        second = client.fund_catalog(today=date(2026, 10, 30))
        self.assertFalse(first["cache"])
        self.assertTrue(second["cache"])
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][1], 3)

    def test_detail_extracts_date_and_labels_without_fabricated_instrument_ids(self):
        catalog = self._client({CATALOG_URL: json.dumps(CATALOG_FIXTURE).encode()}).fund_catalog(today=date(2026, 10, 30))
        record = next(r for r in catalog["normalized_records"] if r["cafci_fund_id"] == 13)
        url = "https://estadisticas.cafci.org.ar/fondos/13?clase=301"
        opener = FakeOpener({url: DETAIL_FIXTURE})
        provider = CAFCIReferenceProvider(opener=opener, clock=lambda: 5)
        self.assertTrue(provider.supports(record))
        self.assertEqual(provider.source_key(record), url)
        result = provider.research(record, today=date(2026, 10, 30))
        self.assertEqual(result["reference_status"], "details_observed")
        self.assertEqual(result["holdings_date"], "2026-10-09")
        self.assertEqual(result["holdings_details"][0], {"name": "Bono Boncer TZXS7", "weight": 23.4})
        self.assertEqual(result["holding_labels"][0], "Bono Boncer TZXS7")
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["exposure_basis"], "mandate")
        self.assertEqual(result["evidence"][-1]["expires_at"], "2026-11-13T23:59:59+00:00")
        self.assertEqual(opener.calls[0][1], 4)

    def test_missing_or_future_composition_date_is_not_promoted_as_current(self):
        record = {"source_provider": "cafci", "cafci_fund_id": 13, "cafci_class_id": 301,
                  "evidence": [], "exposure_basis": "mandate"}
        url = "https://estadisticas.cafci.org.ar/fondos/13?clase=301"
        html_no_date = b'<div id="cartera"><canvas data-pie-chart-items-value="[{&quot;nombre&quot;:&quot;Activo&quot;,&quot;porcentaje&quot;:100}]"></canvas></div>'
        provider = CAFCIReferenceProvider(opener=FakeOpener({url: html_no_date}))
        with self.assertRaises(MarketDataError):
            provider.research(record, today=date(2026, 10, 30))
        future = DETAIL_FIXTURE.replace(b"09/10/2026", b"31/10/2026")
        future_provider = CAFCIReferenceProvider(opener=FakeOpener({url: future}))
        with self.assertRaises(MarketDataError):
            future_provider.research(record, today=date(2026, 10, 30), refresh=True)
        stale = DETAIL_FIXTURE.replace(b"09/10/2026", b"01/09/2026")
        stale_provider = CAFCIReferenceProvider(opener=FakeOpener({url: stale}))
        with self.assertRaises(MarketDataError):
            stale_provider.research(record, today=date(2026, 10, 30), refresh=True)

    def test_reference_rejects_unrecognized_ids_redirect_and_timeout(self):
        provider = CAFCIReferenceProvider(opener=FakeOpener({}))
        self.assertFalse(provider.supports({"source_provider": "cafci", "cafci_fund_id": True, "cafci_class_id": 2}))
        self.assertIsNone(provider.source_key({"source_provider": "cafci", "cafci_fund_id": "../x", "cafci_class_id": 2}))
        record = {"source_provider": "cafci", "cafci_fund_id": 13, "cafci_class_id": 301}
        url = provider.source_key(record)
        redirected = CAFCIReferenceProvider(opener=FakeOpener({url: (DETAIL_FIXTURE, "https://example.com/evil")}))
        with self.assertRaises(MarketDataError):
            redirected.research(record)
        timed = CAFCIReferenceProvider(opener=FakeOpener({url: TimeoutError("timeout")}))
        with self.assertRaises(MarketDataError):
            timed.research(record, timeout=1)


if __name__ == "__main__":
    unittest.main()
