"""Offline public-source boundary, eligibility and frozen execution evidence."""

from copy import deepcopy
from datetime import date
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from nexus.instruments import build_examples, execution_id, query_examples
from nexus.market_data import ArgentinaDatosClient, MarketDataError, valid_data_date, _cache


TODAY = date(2026, 10, 23)


def fund(**overrides):
    return {"fondoId": "12", "claseId": "34", "nombre": "Fondo de prueba offline", "fecha": "2026-10-22",
            "tipoRenta": "Renta Variable", "moneda": "Peso Argentino", "monedaInversion": "Peso Argentino",
            "inversionMinima": 100, "plazoLiquidacionDias": 2, "horizonte": "Largo Plazo", **overrides}


def catalog(*funds):
    return {"fondos": list(funds), "fuente": "Fixture offline", "url": "https://example.test/catalog",
            "consultado_en": "2026-10-23T00:00:00+00:00", "fecha_publicacion": "2026-10-22T15:00:00Z", "cache": False}


def result(**overrides):
    return {"estado": "RECOMENDACION_EXITOSA", "capital": 10000, "moneda": "ARS",
            "cartera_porcentual": {"Renta variable": 20, "Renta fija inflación": 40,
                                    "Renta fija cambiaria": 20, "Liquidez inmediata": 20}, **overrides}


SNAPSHOT = {"perfil": {"capital": 10000, "moneda": "ARS", "horizonte": 24}, "escenario": {"inflacion_alta": True}}


class PublicSourceTest(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def response(self, payload):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode()
        return response

    def test_fetch_cache_expiry_refresh_and_isolated_copies(self):
        opener = Mock(return_value=self.response({"fechaActualizacion": "2026-10-22T15:00:00Z", "fondos": [fund()]}))
        clock = Mock(return_value=0)
        client = ArgentinaDatosClient(opener=opener, clock=clock)
        first = client.fund_catalog(today=TODAY)
        first["fondos"].clear()
        second = client.fund_catalog(today=TODAY)
        self.assertTrue(second["cache"])
        self.assertEqual(len(second["fondos"]), 1)
        self.assertEqual(opener.call_count, 1)
        clock.return_value = 901
        client.fund_catalog(today=TODAY)
        client.fund_catalog(refresh=True, today=TODAY)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(opener.call_args.kwargs["timeout"], 8)

    def test_source_failures_and_bad_schema_are_controlled(self):
        for payload in ([], {"fondos": []}, {"fechaActualizacion": "2099-01-01T00:00:00Z", "fondos": []},
                        {"fechaActualizacion": "2020-01-01T00:00:00Z", "fondos": []}):
            _cache.clear()
            with self.subTest(payload=payload), self.assertRaises(MarketDataError):
                ArgentinaDatosClient(opener=Mock(return_value=self.response(payload))).fund_catalog(today=TODAY)
        with self.assertRaises(MarketDataError):
            ArgentinaDatosClient(opener=Mock(side_effect=URLError("offline"))).fund_catalog(today=TODAY)
        for value in ("2026-10-24", "2026-10-15", "not-a-date", None):
            self.assertIsNone(valid_data_date(value, TODAY))
        self.assertEqual(valid_data_date("2026-10-16", TODAY), "2026-10-16")


class InstrumentExamplesTest(unittest.TestCase):
    def test_diagnostics_count_first_exclusion_once_and_budget_per_category(self):
        funds = [
            fund(tipoRenta="Renta Fija", fecha="2020-01-01", inversionMinima=999999),
            fund(nombre="", fecha="2020-01-01"),
            fund(fecha="2020-01-01"),
            fund(moneda="USD", monedaInversion="USD"),
            fund(inversionMinima=-1),
            fund(inversionMinima=3000),
            fund(nombre="Variable minimum unknown", inversionMinima=None),
            fund(nombre="Minimum unknown", tipoRenta="Renta Fija", inversionMinima=None),
        ]
        output = build_examples(result(), SNAPSHOT, [catalog(*funds)], today=TODAY)
        variable, fixed = output["categorias"][:2]
        self.assertEqual(variable["monto_asignado"], 2000)
        self.assertEqual(fixed["monto_asignado"], 4000)
        self.assertEqual(variable["diagnostico"]["registros_revisados"], len(funds))
        self.assertEqual(variable["diagnostico"]["descartados"], {
            "categoria": 2, "metadatos": 1, "fecha": 1, "moneda": 1,
            "minimo_invalido": 1, "minimo_superior": 1})
        self.assertEqual(variable["diagnostico"]["candidatos_compatibles"], 1)
        self.assertEqual(fixed["diagnostico"]["descartados"]["minimo_superior"], 0)
        self.assertEqual(len(fixed["alternativas"]), 1)

    def test_empty_catalog_has_zeroed_diagnostics(self):
        output = build_examples(result(), SNAPSHOT, [], today=TODAY)
        diag = output["categorias"][0]["diagnostico"]
        self.assertEqual(diag["registros_revisados"], 0)
        self.assertTrue(all(value == 0 for value in diag["descartados"].values()))
        self.assertEqual(diag["candidatos_compatibles"], 0)

    def test_two_classes_are_one_fund_and_verified_minimum_takes_precedence(self):
        funds = [fund(nombre="A clase desconocida", claseId="1", inversionMinima=None),
                 fund(nombre="A clase válida", claseId="2"),
                 fund(nombre="B otro fondo", fondoId="99", claseId="1")]
        output = build_examples(result(), SNAPSHOT, [catalog(*funds)], today=TODAY)
        examples = output["categorias"][0]["ejemplos"]
        self.assertEqual([item["identificador"] for item in examples], ["12/2", "99/1"])

    def test_only_positive_categories_and_explicit_currency_match(self):
        allocation = result(cartera_porcentual={"Renta variable": 0, "Liquidez inmediata": 100})
        output = build_examples(allocation, SNAPSHOT, [catalog(fund(tipoRenta="Mercado de Dinero", plazoLiquidacionDias=0))], today=TODAY)
        self.assertEqual([c["categoria"] for c in output["categorias"]], ["Liquidez inmediata"])
        item = output["categorias"][0]
        self.assertFalse(item["ejemplos"], "Money market is not a promise of immediate rescue")
        self.assertEqual(len(item["alternativas"]), 1)
        dollar = result(moneda="USD", cartera_porcentual={"Renta variable": 100})
        output = build_examples(dollar, SNAPSHOT, [catalog(fund())], today=TODAY)
        self.assertFalse(output["categorias"][0]["ejemplos"])
        usd = fund(moneda="Dolar Estadounidense", monedaInversion="Dolar Estadounidense")
        output = build_examples(dollar, SNAPSHOT, [catalog(usd)], today=TODAY)
        self.assertEqual(output["categorias"][0]["ejemplos"][0]["moneda"], "USD")

    def test_dates_minimum_and_explicit_metadata_guard_classification(self):
        funds = [fund(nombre="Nombre CER dollar linked no prueba cobertura", tipoRenta="Renta Fija"),
                 fund(nombre="Old", fecha="2020-01-01"), fund(nombre="Future", fecha="2026-10-24"),
                 fund(nombre="Missing", fecha=None), fund(nombre="High minimum", inversionMinima=3000),
                 fund(nombre="Invalid minimum", inversionMinima=-1), fund(nombre="Unknown currency", monedaInversion=None),
                 fund(nombre="Good")]
        output = build_examples(result(), SNAPSHOT, [catalog(*funds)], today=TODAY)
        by_cat = {c["categoria"]: c for c in output["categorias"]}
        self.assertEqual([i["nombre"] for i in by_cat["Renta variable"]["ejemplos"]], ["Good"])
        self.assertFalse(by_cat["Renta fija inflación"]["ejemplos"])
        self.assertFalse(by_cat["Renta fija cambiaria"]["ejemplos"])
        self.assertEqual(len(by_cat["Renta fija inflación"]["alternativas"]), 1)
        unknown = build_examples(result(), SNAPSHOT, [catalog(fund(inversionMinima=None))], today=TODAY)
        self.assertFalse(unknown["categorias"][0]["ejemplos"])
        self.assertIn("mínima", unknown["categorias"][0]["alternativas"][0]["criterio"])
        fx = build_examples(result(), SNAPSHOT, [catalog(fund(tipoRenta="Renta Fija", benchmark="A3500"))], today=TODAY)
        example = next(c for c in fx["categorias"] if c["categoria"] == "Renta fija cambiaria")["alternativas"][0]
        self.assertIn("A3500", example["criterio"])
        self.assertEqual(example["compatibilidad_categoria"], "no_verificada")

    def test_snapshot_copies_failure_and_execution_identity(self):
        original = result()
        snapshot = deepcopy(SNAPSHOT)
        source = catalog(fund())
        output = build_examples(original, snapshot, [source], today=TODAY)
        identifier = output["ejecucion_id"]
        original["ejemplos_instrumentos"] = output
        self.assertEqual(execution_id(original, snapshot), identifier)
        source["fondos"][0]["nombre"] = "Changed"
        snapshot["perfil"]["capital"] = 999
        self.assertEqual(output["entradas_evaluacion"]["perfil"]["capital"], 10000)
        self.assertEqual(output["categorias"][0]["ejemplos"][0]["nombre"], "Fondo de prueba offline")
        client = Mock()
        client.fund_catalog.side_effect = MarketDataError("Offline fixture")
        failure = query_examples(original, SNAPSHOT, client=client, today=TODAY)
        self.assertEqual(failure["errores_fuente"], ["Offline fixture"])
        self.assertEqual(original["cartera_porcentual"], result()["cartera_porcentual"])


if __name__ == "__main__":
    unittest.main()
