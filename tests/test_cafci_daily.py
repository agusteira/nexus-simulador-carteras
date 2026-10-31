import json
from datetime import date
from io import BytesIO
import unittest
import zipfile

from nexus.cafci import CAFCIClient, CATALOG_URL, _cache
from nexus.cafci_daily import DAILY_URL, CAFCIDailyClient, parse_daily_xlsx, _cache as daily_cache
from nexus.market_data import MarketDataError


HEADERS = {
    "A": "Fondo", "E": "Fecha", "F": "Valor (mil cuotapartes)",
    "O": "Patrimonio", "Q": "Market Share", "T": "Calificación",
    "U": "Codigo CAFCI", "AU": "Calificado",
}


def _cell(ref, value, *, string=False):
    if string:
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    return f'<c r="{ref}"><v>{value}</v></c>'


def _xlsx(rows=None, *, headers=None, dtd=False):
    rows = rows or []
    headers = headers or HEADERS
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if dtd:
        parts.append('<!DOCTYPE x [<!ENTITY x "boom">]>')
    parts.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
    header_cells = "".join(_cell(f"{col}8", text, string=True) for col, text in headers.items())
    parts.append(f'<row r="8">{header_cells}</row>')
    parts.append('<row r="9"><c r="B9" t="inlineStr"><is><t>Moneda</t></is></c></row>')
    parts.append('<row r="11"><c r="A11" t="inlineStr"><is><t>Clases abiertas</t></is></c></row>')
    for row_number, values in enumerate(rows, 12):
        cells = []
        for column, value in values.items():
            if value is None:
                cells.append(f'<c r="{column}{row_number}" t="inlineStr"><is><t></t></is></c>')
            elif isinstance(value, str):
                cells.append(_cell(f"{column}{row_number}", value, string=True))
            else:
                cells.append(_cell(f"{column}{row_number}", value))
        parts.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    parts.append('</sheetData></worksheet>')
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "".join(parts))
    return stream.getvalue()


def _daily_row(class_id, name, day, nav, aum, share, rating, qualified):
    return {"A": name, "E": day, "F": nav, "O": aum, "Q": share,
            "T": rating, "U": class_id, "AU": qualified}


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
        self.mapping, self.calls = mapping, []

    def __call__(self, request, timeout=0):
        self.calls.append((request.full_url, timeout, dict(request.header_items())))
        value = self.mapping[request.full_url]
        if isinstance(value, Exception):
            raise value
        body, url = value if isinstance(value, tuple) else (value, request.full_url)
        return FakeResponse(body, url)


class CAFCDailyTest(unittest.TestCase):
    def setUp(self):
        _cache.clear()
        daily_cache.clear()

    def test_reader_uses_real_headers_class_ids_and_three_qualification_states(self):
        body = _xlsx([
            _daily_row(101, "Mismo nombre", "29/10/26", 6057.342, None, 0, "AAAf", "N"),
            _daily_row(102, "Otro fondo", "29/10/26", 0, 0, 0.1, "", "Si"),
            _daily_row(103, "Tercero", "29/10/26", 832.5, 12, 0.2, "rating sin fecha", None),
        ])
        observations = parse_daily_xlsx(body, today=date(2026, 10, 30))
        self.assertEqual(set(observations), {101, 102, 103})
        self.assertFalse(observations[101]["qualified_only"])
        self.assertTrue(observations[102]["qualified_only"])
        self.assertIsNone(observations[103]["qualified_only"])
        self.assertIsNone(observations[101]["fund_aum"])
        self.assertEqual(observations[102]["fund_aum"], 0)
        self.assertEqual(observations[101]["nav_per_thousand"], 6057.342)
        self.assertEqual(observations[101]["daily_date"], date(2026, 10, 29))

    def test_latest_recent_class_row_wins_and_future_or_stale_rows_are_ignored(self):
        body = _xlsx([
            _daily_row(101, "A", "29/10/26", 10, 20, 1, None, "N"),
            _daily_row(101, "A", "30/10/26", 11, 21, 1, None, "Si"),
            _daily_row(102, "B", "31/10/26", 99, 99, 1, None, "Si"),
            _daily_row(103, "C", "20/10/26", 99, 99, 1, None, "Si"),
        ])
        observations = parse_daily_xlsx(body, today=date(2026, 10, 30))
        self.assertEqual(observations[101]["daily_date"], date(2026, 10, 30))
        self.assertTrue(observations[101]["qualified_only"])
        self.assertNotIn(102, observations)
        self.assertNotIn(103, observations)

    def test_xlsx_rejects_bad_zip_xml_headers_and_entity_declarations(self):
        with self.assertRaises(MarketDataError):
            parse_daily_xlsx(b"not a zip", today=date(2026, 10, 30))
        with self.assertRaises(MarketDataError):
            parse_daily_xlsx(_xlsx([_daily_row(1, "x", "29/10/26", 1, 1, 1, None, "N")], dtd=True),
                              today=date(2026, 10, 30))
        headers = dict(HEADERS, U="Código equivocado")
        with self.assertRaises(MarketDataError):
            parse_daily_xlsx(_xlsx([], headers=headers), today=date(2026, 10, 30))
        entries = BytesIO()
        with zipfile.ZipFile(entries, "w", zipfile.ZIP_STORED) as archive:
            for index in range(1001):
                archive.writestr(f"empty/{index}.txt", b"")
        with self.assertRaises(MarketDataError):
            parse_daily_xlsx(entries.getvalue(), today=date(2026, 10, 30))

    def test_client_caches_parsed_sheet_for_fifteen_minutes_and_sends_official_headers(self):
        body = _xlsx([_daily_row(101, "A", "29/10/26", 1, 2, 3, None, "N")])
        opener = FakeOpener({DAILY_URL: body})
        client = CAFCIDailyClient(opener=opener, clock=lambda: 10)
        first = client.class_observations(today=date(2026, 10, 30))
        second = client.class_observations(today=date(2026, 10, 30))
        self.assertFalse(first["cache"])
        self.assertTrue(second["cache"])
        self.assertEqual(len(opener.calls), 1)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      opener.calls[0][2]["Accept"])

    def test_client_rejects_redirect_outside_fixed_official_route(self):
        opener = FakeOpener({DAILY_URL: (_xlsx([]), "https://example.test/pb_get")})
        client = CAFCIDailyClient(opener=opener, clock=lambda: 10)
        with self.assertRaises(MarketDataError):
            client.class_observations(today=date(2026, 10, 30))

    def test_catalog_join_is_exact_numeric_class_id_and_daily_failure_preserves_catalog(self):
        catalog = {"generated_at": "2026-10-29T20:31:36Z", "fondos": [
            {"id": 1, "nombre": "Mismo nombre", "estado": 1,
             "tipo_renta": {"nombre": "Renta Variable"}, "clases": [
                 {"id": 101, "nombre": "Clase A", "log_abierto": True, "moneda": {"nombre": "Peso Argentina"},
                  "suscripcion": True, "liquidez": True, "honorarios": {}}]},
            {"id": 2, "nombre": "Otro nombre", "estado": 1,
             "tipo_renta": {"nombre": "Renta Variable"}, "clases": [
                 {"id": 102, "nombre": "Mismo nombre", "log_abierto": True, "moneda": {"nombre": "Peso Argentina"},
                  "suscripcion": True, "liquidez": True, "honorarios": {}}]},
        ]}
        daily = _xlsx([_daily_row(102, "Mismo nombre", "29/10/26", 12.5, 0, 0, None, "N")])
        opener = FakeOpener({CATALOG_URL: json.dumps(catalog).encode(), DAILY_URL: daily})
        result = CAFCIClient(opener=opener, clock=lambda: 1).fund_catalog(today=date(2026, 10, 30))
        by_id = {row["cafci_class_id"]: row for row in result["normalized_records"]}
        self.assertIsNone(by_id[101]["fund_aum"])
        self.assertEqual(by_id[102]["fund_aum"], 0)
        self.assertEqual(by_id[102]["nav_per_thousand"], 12.5)
        self.assertIsNone(by_id[102]["unit_price"])
        self.assertFalse(by_id[102]["qualified_only"])
        evidence = by_id[102]["evidence"][-1]
        self.assertEqual(evidence["data_date"], "2026-10-29")
        self.assertEqual(evidence["fields"]["market_metric"]["metric"], "patrimonio_clase")
        self.assertEqual(evidence["expires_at"], "2026-11-05T23:59:59+00:00")

        failing = CAFCIClient(opener=FakeOpener({CATALOG_URL: json.dumps(catalog).encode(),
                                                 DAILY_URL: TimeoutError("offline")}), clock=lambda: 2)
        result = failing.fund_catalog(refresh=True, today=date(2026, 10, 30))
        self.assertEqual(len(result["normalized_records"]), 2)
        self.assertTrue(result["source_errors"])
        self.assertTrue(all(row.get("fund_aum") is None for row in result["normalized_records"]))


if __name__ == "__main__":
    unittest.main()
