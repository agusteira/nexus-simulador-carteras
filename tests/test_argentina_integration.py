"""Offline end-to-end checks for the Argentina public-source research path."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from nexus.byma_public import (
    BYMAPublicClient,
    BYMAPublicReferenceProvider,
    INSTRUMENT_DETAIL_URL,
    MARKET_DATA_URL,
    _cache as byma_cache,
)
from nexus.cafci import CAFCIClient, CATALOG_URL, _cache as cafci_cache
from nexus.cafci_daily import _cache as daily_cache
from nexus.instruments import _ResearchProviders, query_examples
from nexus.market_data import MarketDataError


TODAY = datetime.now(timezone.utc).date()


class FakeResponse:
    def __init__(self, body, url):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]

    def geturl(self):
        return self.url


class FixtureOpener:
    """Routes requests by endpoint and records only public request bodies."""
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, request, timeout=0):
        body = None
        if request.data:
            raw = request.data.decode("utf-8")
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw
        call = {"url": request.full_url, "method": request.get_method(),
                "body": body, "timeout": timeout}
        self.calls.append(call)
        payload = self.handler(call)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload, call["url"])


class FakeDaily:
    def __init__(self, class_id):
        self.class_id = class_id
        self.calls = 0

    def class_observations(self, refresh=False, today=None):
        self.calls += 1
        return {"observations": {self.class_id: {
            "daily_date": today or TODAY,
            "qualified_only": False,
            "fund_aum": 1_250_000,
            "nav_per_thousand": 1_024.25,
            "calificacion": "N",
            "market_share": 1_250_000,
        }}, "source": "Fixture planilla diaria", "url": "https://api.pub.cafci.org.ar/pb_get",
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cache": False}


class EmptyMarketClient:
    def __init__(self):
        self.calls = 0

    def instrument_catalog(self, refresh=False, today=None):
        self.calls += 1
        return {"normalized_records": [], "fondos": [], "fuente": "BYMADATA público",
                "url": "https://open.bymadata.com.ar/", "consultado_en": "2026-10-30T00:00:00+00:00",
                "fecha_publicacion": None, "cache": False, "source_errors": [],
                "source_coverage": {"normalized_records": 0, "truncated": False}}


class FailingCAFClient:
    def __init__(self):
        self.calls = 0

    def fund_catalog(self, refresh=False, today=None):
        self.calls += 1
        raise MarketDataError("CAFCI fixture unavailable")


def cafci_catalog_fixture():
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_fondos": 1, "total_clases": 1, "fondos": [{
                "id": 731, "nombre": "FCI mercado de dinero de prueba", "estado": 1,
                "objetivo": "Administración de liquidez de corto plazo", "dias_liquidacion": 0,
                "moneda": {"id": 1, "nombre": "Peso Argentina"},
                "mm_puro": True, "tipo_renta": {"id": 4, "nombre": "Mercado de Dinero"},
                "horizonte": {"id": 1, "nombre": "Corto Plazo"},
                "duration": {"id": 9, "nombre": "No Aplicable"},
                "clases": [{"id": 73101, "nombre": "Clase A", "moneda": {"id": 1, "nombre": "Peso Argentina"},
                            "inversion_minima": 100, "suscripcion": True, "liquidez": True,
                            "log_abierto": True,
                            "honorarios": {"administracion_gerente": "1", "administracion_depositaria": "0.1",
                                           "gasto_ordinario_gestion": "0.05", "ingreso": "0", "rescate": "0"}}]}]}


def quote_payload(rows):
    return {"content": {"page_number": 1, "page_count": 1, "page_size": 2000,
                         "total_elements_count": len(rows)},
            "data": rows, "empty": not bool(rows), "upgrade": False}


def cedear_quote(symbol):
    return {"symbol": symbol, "market": "BYMA", "securityType": "CD", "securitySubType": "",
            "denominationCcy": "ARS", "settlementType": "1", "trade": 99, "tradeHour": "12:11:00",
            "bidPrice": 99, "quantityBid": 10, "offerPrice": 100, "quantityOffer": 10,
            "volume": 100, "volumeAmount": 9900, "vwap": 99, "description": "", "securityDesc": ""}


class ArgentinaSourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        cafci_cache.clear()
        daily_cache.clear()
        byma_cache.clear()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = patch.dict(os.environ, {"NEXUS_DATA_DIR": directory.name})
        data_dir.start()
        self.addCleanup(data_dir.stop)

    def _snapshot(self, **profile):
        base = {"capital": 10_000, "moneda": "ARS", "horizonte": 24,
                "objetivo": "Preservacion", "tolerancia": 20, "liquidez": 20}
        base.update(profile)
        return {"perfil": base, "escenario": {"inflacion_alta": False}}

    def _result(self, category, weight=100):
        return {"estado": "RECOMENDACION_EXITOSA", "capital": 10_000, "moneda": "ARS",
                "perfil_riesgo": "MODERADO", "cartera_porcentual": {category: weight}}

    def _category(self, output, category):
        return next(row for row in output["investigacion"]["categories"] if row["category"] == category)

    def test_cafci_daily_candidate_selected_without_broker_execution_claim(self):
        daily = FakeDaily(73101)
        payload = json.dumps(cafci_catalog_fixture()).encode("utf-8")
        caf_opener = FixtureOpener(lambda call: payload if call["url"] == CATALOG_URL else AssertionError(call))
        cafci = CAFCIClient(opener=caf_opener, clock=lambda: 100, daily_client=daily)
        market = EmptyMarketClient()
        original_result = self._result("Liquidez inmediata")
        original_snapshot = self._snapshot()
        result_copy, snapshot_copy = deepcopy(original_result), deepcopy(original_snapshot)

        output = query_examples(original_result, original_snapshot, refresh=True, client=cafci,
                                market_client=market, provider=False)

        decision = self._category(output, "Liquidez inmediata")
        self.assertTrue(decision["selected"], decision["reasons"])
        selected = decision["selected"][0]
        self.assertEqual(selected["canonical_id"], "AR:FCI:731:73101")
        self.assertEqual(selected["instrument_type"], "FCI")
        self.assertEqual(selected["minimum"], 100)
        self.assertEqual(selected["fund_aum"], 1_250_000)
        self.assertEqual(selected["nav_per_thousand"], 1_024.25)
        self.assertEqual(selected["daily_date"], TODAY.isoformat())
        self.assertEqual(selected["fund_fee_annual_pct"], 1.15)
        self.assertEqual(selected["entry_fee_pct"], 0)
        self.assertEqual(selected["redemption_fee_pct"], 0)
        self.assertEqual(decision["selection_scope"], "ARGENTINA_SIN_BROKER")
        self.assertEqual(output["investigacion"]["schema_version"], 4)
        self.assertEqual(decision["educational_selection"]["status"], "SELECTED_BY_RULES")
        selected_check = next(row for row in decision["evaluated"] if row["canonical_id"] == selected["canonical_id"])
        self.assertEqual(selected_check["execution_checks"]["status"], "PENDIENTE_INTERMEDIARIO")
        self.assertIn("broker_fees", selected_check["execution_checks"]["missing_fields"])
        self.assertEqual(original_result, result_copy)
        self.assertEqual(original_snapshot, snapshot_copy)
        self.assertEqual(len(caf_opener.calls), 1)
        self.assertEqual(daily.calls, 1)
        self.assertEqual(market.calls, 1)
        self.assertEqual(len(output["investigacion"]["source_coverage"]), 2)
        self.assertEqual([row["source"] for row in output["investigacion"]["source_coverage"]],
                         ["CAFCI", "BYMADATA público"])
        self.assertEqual(output["investigacion"]["source_coverage"][0]["candidate_count"], 1)

    def test_byma_candidate_survives_cafci_failure_but_quote_is_not_execution_price(self):
        symbol = "QZX7"
        def handler(call):
            if call["url"] == MARKET_DATA_URL:
                body = call["body"]
                panel = "btnCedears" if body.get("btnCedears") else "btnGeneral"
                return quote_payload([cedear_quote(symbol)] if panel == "btnCedears" else [])
            if call["url"] == INSTRUMENT_DETAIL_URL:
                return {"content": {"page_number": 1, "page_count": 1, "page_size": 50,
                                    "total_elements_count": 1},
                        "data": [{"codigoIsin": "ARTEST010001", "tipoEspecie": "Cedears",
                                  "mercadoOrigen": "NASDAQ", "denominacion": "Empresa ficticia de prueba",
                                  "simboloMercado": "QZXF", "valorRepresentado": "Ordinarias",
                                  "emisor": "Depositario de prueba"}], "empty": False, "upgrade": False}
            raise AssertionError(call["url"])

        opener = FixtureOpener(handler)
        market = BYMAPublicClient(opener=opener, clock=lambda: 100)
        providers = _ResearchProviders(BYMAPublicReferenceProvider(opener=opener, clock=lambda: 100))
        cafci = FailingCAFClient()
        original_result = self._result("Renta variable", 10)
        original_snapshot = self._snapshot()
        result_copy, snapshot_copy = deepcopy(original_result), deepcopy(original_snapshot)

        output = query_examples(original_result, original_snapshot, refresh=True, client=cafci,
                                market_client=market, provider=providers)

        decision = self._category(output, "Renta variable")
        self.assertTrue(decision["selected"], decision["reasons"])
        selected = decision["selected"][0]
        self.assertEqual(selected["canonical_id"], f"CEDEAR:{symbol}:BYMA")
        self.assertEqual(selected["instrument_type"], "CEDEAR")
        self.assertEqual(selected["indicative_minimum"], 100)
        self.assertIsNone(selected["unit_price"])
        self.assertIsNone(selected["quote_data_date"])
        selected_check = next(row for row in decision["evaluated"] if row["canonical_id"] == selected["canonical_id"])
        self.assertEqual(selected_check["execution_checks"]["status"], "PENDIENTE_INTERMEDIARIO")
        self.assertIn("final_execution_price", selected_check["execution_checks"]["missing_fields"])
        self.assertIsNone(selected["costs"])
        self.assertEqual(cafci.calls, 1)
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(sum(call["url"] == MARKET_DATA_URL for call in opener.calls), 2)
        self.assertEqual(sum(call["url"] == INSTRUMENT_DETAIL_URL for call in opener.calls), 1)
        self.assertTrue(all(call["timeout"] <= 8 for call in opener.calls))
        for call in opener.calls:
            encoded = json.dumps(call["body"])
            for private_field in ("capital", "horizonte", "objetivo", "tolerancia", "liquidez", "perfil"):
                self.assertNotIn(private_field, encoded)
        self.assertEqual(original_result, result_copy)
        self.assertEqual(original_snapshot, snapshot_copy)
        self.assertTrue(any("CAFCI fixture unavailable" in error
                            for error in output["investigacion"]["search"]["errors"]))

    def test_known_spy_ticker_with_etf_detail_is_not_selected_or_mislabeled_equity(self):
        symbol = "SPY"
        def handler(call):
            if call["url"] == MARKET_DATA_URL:
                body = call["body"]
                panel = "btnCedears" if body.get("btnCedears") else "btnGeneral"
                return quote_payload([cedear_quote(symbol)] if panel == "btnCedears" else [])
            if call["url"] == INSTRUMENT_DETAIL_URL:
                return {"content": {"page_number": 1, "page_count": 1, "page_size": 50,
                                    "total_elements_count": 1},
                        "data": [{"codigoIsin": "ARTEST010002", "tipoEspecie": "Cedears",
                                  "mercadoOrigen": "NYSE", "denominacion": "Fondo índice de prueba",
                                  "simboloMercado": "SPY", "valorRepresentado": "Cuotas de ETF",
                                  "emisor": "Depositario de prueba"}], "empty": False, "upgrade": False}
            raise AssertionError(call["url"])

        opener = FixtureOpener(handler)
        market = BYMAPublicClient(opener=opener, clock=lambda: 100)
        providers = _ResearchProviders(BYMAPublicReferenceProvider(opener=opener, clock=lambda: 100))
        result = self._result("Renta variable", 10)
        snapshot = self._snapshot()

        output = query_examples(result, snapshot, refresh=True, client=FailingCAFClient(),
                                market_client=market, provider=providers)

        decision = self._category(output, "Renta variable")
        self.assertEqual(decision["selected"], [])
        evaluated_spy = next((row for row in decision.get("evaluated", [])
                              if row.get("canonical_id") == "CEDEAR:SPY:BYMA"), None)
        self.assertIsNotNone(evaluated_spy)
        self.assertIsNone(evaluated_spy["record"].get("category"))
        self.assertEqual(evaluated_spy["record"].get("exposure"), "unknown")
        self.assertIn("ordinary_share_representation", evaluated_spy.get("missing_fields", []))
        self.assertFalse(any(card.get("canonical_id") == "CEDEAR:SPY:BYMA"
                             for card in decision["educational_selection"]["cards"]))
        self.assertEqual(len(opener.calls), 3)
        self.assertEqual(opener.calls[2]["body"], {"symbol": "SPY", "Content-Type": "application/json"})


if __name__ == "__main__":
    unittest.main()
