"""Read-only access to BYMADATA's public delayed market snapshots.

Rows are observations from an open web panel, not dated executable quotes.
Instrument facts are enriched only from the portal's public detail endpoint.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener, urlopen

from .market_data import MarketDataError


PORTAL_URL = "https://open.bymadata.com.ar/"
API_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
MARKET_DATA_URL = API_BASE + "/get-market-data"
INSTRUMENT_DETAIL_URL = API_BASE + "/bnown/fichatecnica/especies/general"
SOURCE = "BYMADATA público · BYMA"
SOURCE_BUNDLE_URL = "https://open.bymadata.com.ar/main.cd077c72f0dab8d2.js"
DELAY_MINUTES = 20
CACHE_TTL_SECONDS = 900
SNAPSHOT_TTL_MINUTES = 15
MAX_RESPONSE_BYTES = 4_000_000
MAX_PAGES = 2
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_ALLOWED_URLS = frozenset({MARKET_DATA_URL, INSTRUMENT_DETAIL_URL})
_cache = {}
_cache_lock = Lock()


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def _expires(observed_at, *, minutes=SNAPSHOT_TTL_MINUTES):
    return (_parse_utc(observed_at) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _valid_symbol(value):
    return isinstance(value, str) and _SYMBOL.fullmatch(value) is not None


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _known_currency(value):
    return value if value in ("ARS", "USD") else None


def _source_code(record):
    code = record.get("source_security_type") if isinstance(record, dict) else None
    return code if code in ("CS", "CD") else None


def _identity_key(record):
    return (record.get("canonical_id"), record.get("instrument_type"), record.get("market"),
            record.get("ticker"), record.get("quotation_currency"), record.get("quote_settlement_code"))


def _allowed_url(url):
    parsed = urlparse(url)
    return (url in _ALLOWED_URLS and parsed.scheme == "https"
            and parsed.hostname == "open.bymadata.com.ar" and parsed.port in (None, 443))


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise MarketDataError("BYMADATA intentó redirigir fuera de las rutas públicas permitidas.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = build_opener(_SafeRedirect(), HTTPSHandler())


def _request(url, body, *, timeout, opener):
    if not _allowed_url(url):
        raise MarketDataError("La ruta BYMADATA no está permitida.")
    payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    request = Request(url, data=payload, method="POST", headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": PORTAL_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
    })
    try:
        call = _SAFE_OPENER.open if opener is None else (opener if callable(opener) else opener.open)
        with call(request, timeout=timeout) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if not _allowed_url(final_url) or final_url != url:
                raise MarketDataError("La respuesta BYMADATA terminó en una ruta no solicitada.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except MarketDataError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise MarketDataError("No pudimos consultar BYMADATA público.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MarketDataError("La respuesta BYMADATA supera el tamaño permitido.")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError):
        raise MarketDataError("BYMADATA devolvió JSON inválido.") from None
    if not isinstance(result, dict):
        raise MarketDataError("BYMADATA devolvió una respuesta con formato inesperado.")
    return result


def _page_body(panel, page_number):
    return {"excludeZeroPxAndQty": False, "T0": True, "page_number": page_number,
            "page_size": 2000, panel: True}


def _get_page(panel, page_number, *, refresh, timeout, opener, clock):
    body = _page_body(panel, page_number)
    cache_key = (MARKET_DATA_URL, json.dumps(body, sort_keys=True, separators=(",", ":")))
    now = clock()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if not refresh and cached and 0 <= now - cached[0] < CACHE_TTL_SECONDS:
            return deepcopy(cached[1]), cached[2], True
    result = _request(MARKET_DATA_URL, body, timeout=timeout, opener=opener)
    rows = result.get("data")
    content = result.get("content")
    if not isinstance(rows, list) or not isinstance(content, dict):
        raise MarketDataError(f"BYMADATA {panel} no publicó datos/paginación con formato válido.")
    observed_at = _utc_now()
    cache_item = {"data": rows, "content": content, "empty": result.get("empty"),
                  "upgrade": result.get("upgrade")}
    with _cache_lock:
        _cache[cache_key] = (now, deepcopy(cache_item), observed_at)
    return cache_item, observed_at, False


def _market_settlement(code):
    if code == "1":
        return "CI", 0
    if code == "2":
        return "24hs", 1
    return None, None


def _normalize_quote(row, *, panel, observed_at, page_body):
    if not isinstance(row, dict):
        return None, "invalid_row"
    expected_type = "CS" if panel == "btnGeneral" else "CD"
    code = row.get("securityType")
    if row.get("market") != "BYMA" or code != expected_type:
        return None, "source_class_mismatch"
    currency = _known_currency(row.get("denominationCcy"))
    if currency is None:
        return None, "unsupported_currency"
    symbol = row.get("symbol")
    if not _valid_symbol(symbol):
        return None, "invalid_symbol"
    instrument_type = "LOCAL_SHARE" if code == "CS" else "CEDEAR"
    canonical_id = f"{instrument_type}:{symbol}:BYMA"
    settlement_code = row.get("settlementType")
    if not isinstance(settlement_code, str):
        settlement_code = None
    settlement_label, settlement_days = _market_settlement(settlement_code)
    offer = _finite_number(row.get("offerPrice"))
    offer_quantity = _finite_number(row.get("quantityOffer"))
    bid = _finite_number(row.get("bidPrice"))
    bid_quantity = _finite_number(row.get("quantityBid"))
    reference_offer = offer if offer is not None and offer > 0 and offer_quantity is not None and offer_quantity > 0 else None
    reference_bid = bid if bid is not None and bid > 0 and bid_quantity is not None and bid_quantity > 0 else None
    volume = _finite_number(row.get("volume"))
    volume_amount = _finite_number(row.get("volumeAmount"))
    quote_url = MARKET_DATA_URL
    metric = None
    if volume_amount is not None:
        metric = {"name": "Monto negociado observado", "value": volume_amount,
                  "unit": currency, "period": "snapshot sin fecha de mercado",
                  "observed_at": observed_at, "source": SOURCE, "market": "BYMA",
                  "metric": "monto_negociado_observado", "currency": currency}
    raw_market = {key: deepcopy(row.get(key)) for key in (
        "trade", "tradeHour", "tradeVolume", "volume", "volumeAmount", "vwap", "bidPrice",
        "quantityBid", "offerPrice", "quantityOffer", "settlementPrice", "settlementType",
        "denominationCcy", "securityType", "securitySubType", "market", "description", "securityDesc",
    ) if key in row}
    if "maturityDate" in row:
        raw_market["maturityDate"] = row["maturityDate"]
    if "daysToMaturity" in row:
        raw_market["daysToMaturity"] = row["daysToMaturity"]
    name = row.get("securityDesc") or row.get("description")
    if not isinstance(name, str) or not name.strip():
        name = None

    fields = {"canonical_id": canonical_id, "instrument_type": instrument_type,
              "ticker": symbol, "market": "BYMA", "quotation_currency": currency,
              "reference_offer_price": reference_offer,
              "reference_offer_quantity": offer_quantity if reference_offer is not None else None,
              "reference_bid_price": reference_bid,
              "reference_bid_quantity": bid_quantity if reference_bid is not None else None,
              "quote_volume": volume, "quote_volume_amount": volume_amount,
              "market_metric": deepcopy(metric), "market_settlement_label": settlement_label,
              "settlement_days": settlement_days}
    evidence = {"source": SOURCE, "url": quote_url, "fields": fields,
                "raw_source_fields": {"request_body": deepcopy(page_body), "quote": raw_market,
                                      "source_security_type": code},
                "observed_at": observed_at, "data_date": None,
                "expires_at": _expires(observed_at), "kind": "observed",
                "source_type": "exchange_market_data", "scope": "market_snapshot",
                "delay_minutes": DELAY_MINUTES, "version": "public-snapshot-v1"}
    record = {
        "canonical_id": canonical_id, "instrument_type": instrument_type,
        "ticker": symbol, "market": "BYMA", "stable_id": None,
        "underlying_id": None, "name": name, "description": None,
        "source_provider": "bymadata", "source_security_type": code,
        "source_security_subtype": row.get("securitySubType"),
        "source_panel": panel, "quotation_currency": currency,
        "subscription_currency": None, "economic_currency": None,
        "category": None, "exposure": "unknown", "category_hint": "Renta variable",
        "exposure_basis": None, "minimum": None, "lot_size": None,
        "unit_price": None, "costs": None, "settlement_days": settlement_days,
        "market_settlement_label": settlement_label, "quote_settlement_code": settlement_code,
        "liquidity": "unknown", "access": "unknown", "broker": None,
        "issuer": None, "issuer_role": None, "underlying_name": None,
        "underlying_ticker": None, "underlying_market": None,
        "underlying_type_source": None, "underlying_issuer_role": None,
        "holdings": [], "risks": [],
        "familiar": False, "familiarity_basis": None,
        "market_metric": metric,
        "snapshot_observed_at": observed_at, "quote_data_date": None,
        "snapshot_delay_minutes": DELAY_MINUTES,
        "reference_offer_price": reference_offer,
        "reference_offer_quantity": offer_quantity if reference_offer is not None else None,
        "reference_bid_price": reference_bid,
        "reference_bid_quantity": bid_quantity if reference_bid is not None else None,
        "quote_volume": volume, "quote_volume_amount": volume_amount,
        "trade_hour_source": row.get("tradeHour"), "raw_market_snapshot": raw_market,
        "market_unit_rule": ({"nominal": 1, "source": "https://data-widgets.byma.com.ar/wp-content/uploads/2020/08/BYMA-COM-17710-Modificacion-de-unidad-minima-de-negociacion-CEDEAR.pdf",
                               "published_at": "2020-08-14", "rule_id": "BYMA17710_CEDEAR_VN1"}
                              if code == "CD" else None),
        "validation_status": "observed", "reference_status": "snapshot_observed",
        "contradictions": [], "missing_fields": ["category", "exposure", "subscription_currency",
            "economic_currency", "minimum", "lot_size", "unit_price", "costs", "liquidity", "access", "broker"],
        "evidence": [evidence],
    }
    return record, None


def _field_value(detail, key):
    value = detail.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _slug(value):
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
    return cleaned or None


class BYMAPublicClient:
    def __init__(self, timeout=8, opener=None, clock=monotonic, *, max_pages=MAX_PAGES):
        self.timeout, self.opener, self.clock = timeout, opener, clock
        self.max_pages = min(MAX_PAGES, max(1, int(max_pages)))

    def instrument_catalog(self, refresh=False, today=None):
        del today  # BYMADATA has no publication/business date on the quote rows.
        panels = {}
        source_errors = []
        all_cached = True
        successful_panels = 0
        for panel in ("btnGeneral", "btnCedears"):
            panel_rows = []
            page_observations = []
            page_bodies = []
            page_infos = []
            page_number = 1
            truncated = False
            while page_number <= self.max_pages:
                body = _page_body(panel, page_number)
                try:
                    result, observed_at, was_cached = _get_page(
                        panel, page_number, refresh=refresh, timeout=self.timeout,
                        opener=self.opener, clock=self.clock)
                except MarketDataError as exc:
                    source_errors.append({"source": panel, "error": str(exc)})
                    break
                all_cached = all_cached and was_cached
                successful_panels += 1
                rows = result["data"]
                content = result["content"]
                panel_rows.extend(rows)
                page_observations.extend([observed_at] * len(rows))
                page_bodies.extend([body] * len(rows))
                page_infos.append({"page_number": content.get("page_number", page_number),
                                   "page_count": content.get("page_count"),
                                   "page_size": content.get("page_size"),
                                   "total_elements_count": content.get("total_elements_count"),
                                   "returned_rows": len(rows), "observed_at": observed_at,
                                   "cached": was_cached})
                page_count = content.get("page_count")
                total_count = content.get("total_elements_count")
                page_size = content.get("page_size")
                if not isinstance(page_count, int) and isinstance(total_count, int) and isinstance(page_size, int) and page_size > 0:
                    page_count = math.ceil(total_count / page_size)
                if isinstance(page_count, int) and page_count > self.max_pages:
                    truncated = True
                elif isinstance(total_count, int) and total_count > len(panel_rows) and not isinstance(page_count, int):
                    truncated = True
                if not isinstance(page_count, int) or page_number >= page_count or page_number >= self.max_pages:
                    if isinstance(total_count, int) and total_count > len(panel_rows):
                        truncated = True
                    break
                page_number += 1
            panels[panel] = {"raw_rows": panel_rows, "observations": page_observations,
                             "request_bodies": page_bodies,
                             "pages": page_infos, "truncated": truncated}

        normalized = []
        excluded = {"invalid_row": 0, "source_class_mismatch": 0, "unsupported_currency": 0,
                    "invalid_symbol": 0, "duplicate": 0}
        seen = set()
        for panel in ("btnGeneral", "btnCedears"):
            source = panels.get(panel, {})
            for row, observed_at, request_body in zip(source.get("raw_rows", []), source.get("observations", []),
                                                      source.get("request_bodies", [])):
                record, reason = _normalize_quote(row, panel=panel, observed_at=observed_at,
                                                  page_body=request_body)
                if reason:
                    excluded[reason] = excluded.get(reason, 0) + 1
                    continue
                identity = _identity_key(record)
                if identity in seen:
                    excluded["duplicate"] += 1
                    continue
                seen.add(identity)
                normalized.append(record)
        coverage_panels = {}
        for panel in ("btnGeneral", "btnCedears"):
            source = panels.get(panel, {})
            coverage_panels[panel] = {"raw_rows": len(source.get("raw_rows", [])),
                "normalized_records": sum(r.get("source_panel") == panel for r in normalized),
                "pages": source.get("pages", []), "truncated": bool(source.get("truncated", False))}
        return {"normalized_records": normalized, "fondos": [], "fuente": "BYMADATA público",
                "url": PORTAL_URL, "consultado_en": _utc_now(), "fecha_publicacion": None,
                "cache": successful_panels > 0 and all_cached, "source_errors": source_errors,
                "source_coverage": {"panels": coverage_panels, "excluded": excluded,
                    "raw_rows": sum(len(x.get("raw_rows", [])) for x in panels.values()),
                    "normalized_records": len(normalized),
                    "truncated": any(x.get("truncated", False) for x in panels.values())}}


class BYMAPublicReferenceProvider:
    def __init__(self, timeout=4, opener=None, clock=monotonic):
        self.timeout, self.opener, self.clock = timeout, opener, clock

    @staticmethod
    def supports(record):
        return (isinstance(record, dict) and record.get("source_provider") == "bymadata"
                and record.get("market") == "BYMA" and _valid_symbol(record.get("ticker"))
                and _source_code(record) is not None)

    @staticmethod
    def source_key(record):
        if not BYMAPublicReferenceProvider.supports(record):
            return None
        return f"bymadata:{record['ticker']}:{_source_code(record)}"

    def research(self, record, refresh=False, today=None, timeout=None):
        del today
        if not self.supports(record):
            raise MarketDataError("El registro no tiene símbolo/categoría BYMADATA verificable.")
        symbol = record["ticker"]
        body = {"symbol": symbol, "Content-Type": "application/json"}
        cache_key = (INSTRUMENT_DETAIL_URL, symbol)
        now = self.clock()
        with _cache_lock:
            cached = _cache.get(cache_key)
            if not refresh and cached and 0 <= now - cached[0] < CACHE_TTL_SECONDS:
                payload, observed_at, was_cached = deepcopy(cached[1]), cached[2], True
            else:
                payload = observed_at = None
                was_cached = False
        if payload is None:
            payload = _request(INSTRUMENT_DETAIL_URL, body,
                               timeout=self.timeout if timeout is None else timeout,
                               opener=self.opener)
            data = payload.get("data")
            if not isinstance(data, list):
                raise MarketDataError("La ficha de instrumento BYMADATA no publicó una lista de datos.")
            observed_at = _utc_now()
            with _cache_lock:
                _cache[cache_key] = (now, deepcopy(payload), observed_at)
        rows = payload.get("data")
        matching = [item for item in rows if isinstance(item, dict)
                    and (item.get("simboloMercado") == symbol or item.get("symbol") == symbol)]
        if not matching and len(rows) == 1 and isinstance(rows[0], dict):
            matching = [rows[0]]
        if len(matching) != 1:
            raise MarketDataError("La ficha BYMADATA no identifica unívocamente el símbolo consultado.")
        detail = matching[0]
        expected_code = _source_code(record)
        source_type_name = _field_value(detail, "tipoEspecie")
        normalized_type = source_type_name.casefold() if source_type_name else ""
        local_share_type = record.get("instrument_type") == "LOCAL_SHARE" and expected_code == "CS"
        cedear_type = record.get("instrument_type") == "CEDEAR" and expected_code == "CD"
        conflicts = []
        if local_share_type and (normalized_type != "acciones" or _field_value(detail, "insType") != "EQUITY"):
            conflicts.append("El panel CS no coincide con la ficha que debe confirmar Acciones/EQUITY.")
        if cedear_type and normalized_type != "cedears":
            conflicts.append("El panel CD no coincide con tipoEspecie Cedears de la ficha.")
        if (expected_code == "CS") != (normalized_type == "acciones"):
            conflicts.append("La clase de mercado del snapshot contradice tipoEspecie de la ficha.")
        result = deepcopy(record)
        raw = {key: deepcopy(detail[key]) for key in (
            "codigoIsin", "tipoEspecie", "descripcion", "valorNominal", "montoAutorizado",
            "denominacion", "lider", "insType", "mercadoOrigen", "maxAdmitido",
            "simboloMercado", "fechaAutorizada", "valorRepresentado", "emisor") if key in detail}
        issuer = _field_value(detail, "emisor")
        isin = _field_value(detail, "codigoIsin")
        instrument_description = _field_value(detail, "denominacion")
        underlying_type = _field_value(detail, "valorRepresentado")
        origin_market = _field_value(detail, "mercadoOrigen")
        origin_symbol = _field_value(detail, "simboloMercado")
        detail_name = (issuer if local_share_type else instrument_description) or issuer
        fields = {"canonical_id": record["canonical_id"], "instrument_type": record["instrument_type"],
                  "market": "BYMA", "ticker": symbol}
        if isin:
            result["stable_id"] = isin
            fields["stable_id"] = isin
        if detail_name:
            result["name"] = detail_name
            fields["name"] = detail_name
        if issuer:
            result["issuer"] = issuer
            result["issuer_role"] = "economic_issuer" if local_share_type and not conflicts else "depositary" if cedear_type else None
            fields["issuer"] = issuer
            if result["issuer_role"]:
                fields["issuer_role"] = result["issuer_role"]
        if local_share_type and not conflicts:
            result["category"] = "Renta variable"
            result["exposure"] = "equity"
            result["underlying_name"] = issuer
            result["underlying_issuer_role"] = "economic_issuer"
            result["underlying_id"] = f"AR:BYMA:{symbol}:{isin}" if isin else None
            fields.update({"category": result["category"], "exposure": result["exposure"]})
            fields["underlying_issuer_role"] = "economic_issuer"
            if result["underlying_id"]:
                fields["underlying_id"] = result["underlying_id"]
        elif cedear_type and underlying_type and _slug(underlying_type) in {"ORDINARIAS", "ORDINARIAS_ESCRITURALES", "ACCIONES_ORDINARIAS"} and not conflicts:
            result["category"] = "Renta variable"
            result["exposure"] = "equity"
            result["underlying_name"] = instrument_description
            result["underlying_ticker"] = origin_symbol
            result["underlying_market"] = origin_market
            result["underlying_type_source"] = underlying_type
            result["underlying_issuer_role"] = "economic_issuer"
            if origin_market and origin_symbol:
                result["underlying_id"] = f"FOREIGN:{_slug(origin_market)}:{_slug(origin_symbol)}:{_slug(underlying_type)}"
            fields.update({"category": result["category"], "exposure": result["exposure"]})
            if instrument_description:
                fields["underlying_name"] = instrument_description
            if origin_symbol:
                fields["underlying_ticker"] = origin_symbol
            if origin_market:
                fields["underlying_market"] = origin_market
            fields["underlying_type_source"] = underlying_type
            fields["underlying_issuer_role"] = "economic_issuer"
            if result.get("underlying_id"):
                fields["underlying_id"] = result["underlying_id"]
        result["reference_status"] = "identity_conflict" if conflicts else "details_observed"
        if conflicts:
            result["validation_status"] = "review"
            result.setdefault("contradictions", []).extend(conflicts)
        evidence = {"source": SOURCE, "url": INSTRUMENT_DETAIL_URL,
                    "fields": fields,
                    "raw_source_fields": {"request_body": body, "detail": raw,
                                          "portal_url": PORTAL_URL},
                    "observed_at": observed_at, "data_date": None,
                    "expires_at": _expires(observed_at), "kind": "observed",
                    "source_type": "exchange_instrument_detail", "scope": "product_identity",
                    "version": "instrument-detail-v1", "cache": was_cached}
        result.setdefault("evidence", []).append(evidence)
        return result
