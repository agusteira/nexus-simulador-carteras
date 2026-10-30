"""Bounded, read-only identity research from a small fixed set of references."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import unescape as html_unescape
from html.parser import HTMLParser
import json
import re
import ssl
from threading import Lock
from time import monotonic
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from urllib.request import HTTPSHandler
from .market_data import MarketDataError
from .instrument_knowledge import _FUND_EDUCATION, _fold_name


ALLOWLIST = frozenset({
    "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy",
    "https://www.comafi.com.ar/custodiaglobal/Programas-CEDEARs-2483.note.aspx",
    "https://cajadevalores.com.ar/Servicios/Cedears",
    "https://inversores.ypf.com/faq.html",
    "https://bitcoin.org/es/faq",
} | {url for family in _FUND_EDUCATION["families"] for url in (family["source_url"], family["provider_url"])})
_FIMA_BY_URL = {url: family for family in _FUND_EDUCATION["families"] for url in (family["source_url"], family["provider_url"])}
_FIMA_BY_MODEL_URL = {family["provider_url"]: family for family in _FUND_EDUCATION["families"]}
_FIMA_BY_ID = {family["education_id"]: family for family in _FUND_EDUCATION["families"]}
MAX_BYTES = 2_000_000
CACHE_TTL = 900
_cache, _lock = {}, Lock()


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl not in ALLOWLIST:
            raise MarketDataError("La fuente intentó redirigir fuera de la lista permitida.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.rows, self._row, self._cell = [], [], None, None
        self.headings, self._heading = [], None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "br" and not self.skip:
            self.parts.append(" ")
            if self._cell is not None: self._cell.append(" ")
            if self._heading is not None: self._heading.append(" ")
        if tag == "tr": self._row = []
        if tag in ("td", "th"): self._cell = []
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6"): self._heading = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip: self.skip -= 1
        if tag in ("td", "th") and self._cell is not None:
            value = " ".join("".join(self._cell).split())
            if self._row is not None: self._row.append(value)
            self._cell = None
        if tag == "tr" and self._row is not None:
            if self._row: self.rows.append(tuple(self._row))
            self._row = None
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            self.headings.append(" ".join("".join(self._heading).split()))
            self._heading = None

    def handle_data(self, data):
        if self.skip: return
        self.parts.append(data)
        if self._cell is not None: self._cell.append(data)
        if self._heading is not None: self._heading.append(data)


def _key(text):
    import re
    import unicodedata
    text = "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _has_token(text, token):
    return re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text.upper()) is not None


def _fima_model_facts(payload, family):
    """Extract only the issuer's exact product card from its AEM page model."""
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    if _fold_name(title) not in {_fold_name(alias) for alias in family["aliases"]}:
        return None
    try:
        card = payload[":items"]["root"][":items"]["responsivegrid"][":items"]["cardfund"]["cardFund"]["fundDescriptionCard"]
    except (KeyError, TypeError):
        return None
    card_title = card.get("title") if isinstance(card, dict) else None
    if not isinstance(card_title, str) or not any(_key(alias) in _key(card_title) for alias in family["aliases"]):
        return None
    description = card.get("description")
    if not isinstance(description, str):
        return None
    # This is an inert description field; strip markup and inspect only fixed
    # mandate terms. No links, scripts, ratios or composition tables are used.
    safe_description = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", description, flags=re.I | re.S)
    text = _key(re.sub(r"<[^>]*>", " ", html_unescape(safe_description)))
    if family["education_id"] == "FIMA_PREMIUM":
        adequate = all(_key(term) in text for term in family["mandate_terms"])
    elif family["education_id"] == "FIMA_RENTA_PESOS":
        adequate = "cer" in text and "inflacion" in text
    else:
        adequate = "dollar linked" in text and "tipo de cambio" in text
    if not adequate:
        return None
    return {"fields": {"category": family["category_hint"], "exposure": family["exposure_hint"],
                        "exposure_basis": "mandate"}, "scope": "mandate", "source_type": "issuer"}


def _source_type_for_url(url):
    if url in _FIMA_BY_MODEL_URL or url in _FIMA_BY_URL or url.startswith(("https://www.ssga.com/", "https://inversores.ypf.com/")):
        return "issuer"
    if url.startswith("https://www.comafi.com.ar/") or url == "https://cajadevalores.com.ar/Servicios/Cedears":
        return "depositary"
    if url.startswith("https://bitcoin.org/"):
        return "official_documentation"
    return "official_source"


def parse_reference(url, body, *, observed_at=None):
    """Offline-fixture entry point. Returns positively corroborated identity fields."""
    if url not in ALLOWLIST:
        raise ValueError("URL no permitida")
    if isinstance(body, bytes):
        if len(body) > MAX_BYTES: raise MarketDataError("La respuesta supera el tamaño permitido.")
        body = body.decode("utf-8", "replace")
        if "\ufffd" in body:
            body = body.encode("utf-8", "replace").decode("latin-1", "replace")
    elif len(str(body).encode("utf-8")) > MAX_BYTES:
        raise MarketDataError("La respuesta supera el tamaño permitido.")
    parser = _Text()
    parser.feed(str(body))
    text = " ".join(" ".join(parser.parts).split())
    stamp = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    parsed_stamp = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    if parsed_stamp.tzinfo is None:
        parsed_stamp = parsed_stamp.replace(tzinfo=timezone.utc)
    stamp = parsed_stamp.isoformat(timespec="seconds")
    out = {}
    if url in _FIMA_BY_MODEL_URL:
        try:
            payload = json.loads(str(body))
        except (TypeError, ValueError):
            return {}
        family = _FIMA_BY_MODEL_URL[url]
        facts = _fima_model_facts(payload, family)
        if facts:
            out[family["education_id"]] = facts
        for result in out.values():
            result.setdefault("source_type", _source_type_for_url(url))
            result["observed_at"] = stamp
            result["data_date"] = None
            result["expires_at"] = (parsed_stamp + timedelta(days=30)).isoformat(timespec="seconds")
        return out
    if url.startswith("https://www.ssga.com/"):
        heading = " ".join(_key(h) for h in parser.headings)
        normalized = _key(text)
        listing = None
        for idx, row in enumerate(parser.rows):
            header = [_key(cell) for cell in row]
            exchange_i = next((i for i, h in enumerate(header) if h == "exchange"), None)
            ticker_i = next((i for i, h in enumerate(header) if h == "ticker"), None)
            currency_i = next((i for i, h in enumerate(header) if "trading currency" in h), None)
            if exchange_i is not None and ticker_i is not None:
                listing = next((r for r in parser.rows[idx + 1:] if len(r) > max(exchange_i, ticker_i) and _key(r[exchange_i]) == "nyse arca" and _key(r[ticker_i]) == "spy"), None)
                if listing and currency_i is not None and len(listing) > currency_i:
                    listing = (listing, currency_i)
                break
        if "spdr s p 500 etf trust" in heading and " spy " in f" {normalized} " and "s p 500" in normalized and listing:
            row, currency_i = listing if isinstance(listing, tuple) else (listing, None)
            fields = {"ticker": "SPY", "market": "NYSE_ARCA", "name": "SPDR S&P 500 ETF Trust",
                      "category": "Renta variable", "exposure": "equity", "educational_role": "index_basket"}
            if currency_i is not None and _key(row[currency_i]) == "usd": fields["quotation_currency"] = "USD"
            out["ETF:SPY:NYSE_ARCA"] = {"fields": {"canonical_id": "ETF:SPY:NYSE_ARCA", "instrument_type": "ETF", **fields}}
    elif url.startswith("https://www.comafi.com.ar/"):
        # Require the official CEDEAR table's exact headers and then match exact cells.
        header_indexes = None
        for index, row in enumerate(parser.rows):
            headers = [_key(cell) for cell in row]
            isin_i = next((i for i, h in enumerate(headers) if "isin cedear" in h), None)
            ticker_i = next((i for i, h in enumerate(headers) if "ticker en mercado de origen" in h), None)
            market_i = next((i for i, h in enumerate(headers) if h == "mercado de valor subyacente"), None)
            if isin_i is not None and ticker_i is not None and market_i is not None:
                header_indexes = (index, isin_i, ticker_i, market_i)
                break
        if header_indexes:
            header_i, isin_i, ticker_i, market_i = header_indexes
            rows = parser.rows[header_i + 1:]
            for ticker, expected_market in (("MELI", "nasdaq gs"),):
                matches = list(dict.fromkeys(row for row in rows if len(row) > max(isin_i, ticker_i, market_i)
                           and _key(row[ticker_i]) == ticker.casefold()
                           and _key(row[market_i]) == expected_market
                           and _key(row[isin_i]).startswith("ar")))
                if len(matches) == 1:
                    row = matches[0]
                    cid = f"CEDEAR:{ticker}:BYMA"
                    out[cid] = {"fields": {"canonical_id": cid, "ticker": ticker, "instrument_type": "CEDEAR", "stable_id": row[isin_i].strip(), "underlying_id": f"US:{ticker}", "underlying_name": row[0].strip(), "category": "Renta variable", "exposure": "equity"}}
                    if ticker == "MELI":
                        out["FOREIGN_SHARE:MELI:NASDAQ"] = {"fields": {"canonical_id": "FOREIGN_SHARE:MELI:NASDAQ", "ticker": "MELI", "market": "NASDAQ", "instrument_type": "FOREIGN_SHARE", "underlying_id": "US:MELI", "name": row[0].strip(), "category": "Renta variable", "exposure": "equity"},
                            "raw_source_fields": {"issuer_name": row[0].strip(), "market_of_origin": row[market_i].strip()}}
    elif url == "https://cajadevalores.com.ar/Servicios/Cedears":
        indexes = None
        for idx, row in enumerate(parser.rows):
            header = [_key(cell) for cell in row]
            symbol_i = next((i for i, h in enumerate(header) if h == "simbolo byma"), None)
            ticker_i = next((i for i, h in enumerate(header) if h == "ticker en mercado de origen"), None)
            isin_i = next((i for i, h in enumerate(header) if h == "isin cedear"), None)
            market_i = next((i for i, h in enumerate(header) if h == "mercado de origen"), None)
            if None not in (symbol_i, ticker_i, isin_i, market_i):
                indexes = (idx, symbol_i, ticker_i, isin_i, market_i)
                break
        if indexes:
            idx, symbol_i, ticker_i, isin_i, market_i = indexes
            matches = [r for r in parser.rows[idx + 1:] if len(r) > max(symbol_i, ticker_i, isin_i, market_i)
                       and _key(r[symbol_i]) == "spy" and _key(r[ticker_i]) == "spy"
                       and _key(r[market_i]) == "nyse arca" and _key(r[isin_i]).startswith("ar")]
            if len(matches) == 1:
                row = matches[0]
                out["CEDEAR:SPY:BYMA"] = {"fields": {"canonical_id": "CEDEAR:SPY:BYMA", "ticker": "SPY", "market": "BYMA", "instrument_type": "CEDEAR",
                    "stable_id": row[isin_i].strip(), "underlying_id": "US:SPY", "underlying_name": row[0].strip(),
                    "category": "Renta variable", "exposure": "equity"}}
    elif url in _FIMA_BY_URL:
        family = _FIMA_BY_URL[url]
        title_keys = [_key(x) for x in parser.headings]
        named = any(any(_key(alias) in heading for alias in family["aliases"]) for heading in title_keys)
        body_key = _key(text)
        if named:
            if family["education_id"] == "FIMA_PREMIUM":
                adequate = all(_key(term) in body_key for term in family["mandate_terms"])
            elif family["education_id"] == "FIMA_RENTA_PESOS":
                cer_section = any("fondos de bonos cer" in heading for heading in title_keys)
                direct_cer_mandate = "benchmark cer" in body_key and "tasa fija y variable" in body_key
                adequate = cer_section or direct_cer_mandate
            else:
                adequate = "dollar linked" in body_key and "tipo de cambio" in body_key
            if adequate:
                out[family["education_id"]] = {"fields": {"category": family["category_hint"], "exposure": family["exposure_hint"],
                    "exposure_basis": "mandate"}, "scope": "mandate", "source_type": "issuer"}
    elif url.startswith("https://inversores.ypf.com/"):
        lower = text.casefold()
        if _has_token(text, "YPF") and "adr" in lower and "nyse" in lower:
            out["ADR:YPF:NYSE"] = {"fields": {"canonical_id": "ADR:YPF:NYSE", "ticker": "YPF", "market": "NYSE", "instrument_type": "ADR", "issuer": "YPF S.A.", "category": "Renta variable", "exposure": "equity"}}
        if _has_token(text, "YPFD") and "byma" in lower and ("accion" in lower or "share" in lower):
            out["LOCAL_SHARE:YPFD:BYMA"] = {"fields": {"canonical_id": "LOCAL_SHARE:YPFD:BYMA", "ticker": "YPFD", "market": "BYMA", "instrument_type": "LOCAL_SHARE", "issuer": "YPF S.A.", "category": "Renta variable", "exposure": "equity"}}
    else:
        if "bitcoin" in text.casefold() and "btc" in text.casefold():
            out["CRYPTO:BTC:BITCOIN"] = {"fields": {"canonical_id": "CRYPTO:BTC:BITCOIN", "ticker": "BTC", "market": "BITCOIN", "instrument_type": "CRYPTO", "name": "Bitcoin"}}
    for result in out.values():
        result.setdefault("source_type", _source_type_for_url(url))
        result["observed_at"] = stamp
        result["data_date"] = None
        result["expires_at"] = (datetime.fromisoformat(stamp.replace("Z", "+00:00")) + timedelta(days=30)).isoformat(timespec="seconds")
    return out


def _url_for(record):
    cid = record.get("canonical_id")
    if record.get("instrument_type") == "FCI" and record.get("education_id") in _FIMA_BY_ID:
        return _FIMA_BY_ID[record["education_id"]]["provider_url"]
    if cid == "ETF:SPY:NYSE_ARCA": return next(u for u in ALLOWLIST if "ssga.com" in u)
    if cid == "CEDEAR:SPY:BYMA": return "https://cajadevalores.com.ar/Servicios/Cedears"
    if cid in ("CEDEAR:MELI:BYMA", "FOREIGN_SHARE:MELI:NASDAQ"): return next(u for u in ALLOWLIST if "comafi.com.ar" in u)
    if cid in ("ADR:YPF:NYSE", "LOCAL_SHARE:YPFD:BYMA"): return next(u for u in ALLOWLIST if "inversores.ypf.com" in u)
    if cid == "CRYPTO:BTC:BITCOIN": return next(u for u in ALLOWLIST if "bitcoin.org" in u)
    return None


class ReferenceProvider:
    def __init__(self, timeout=4, opener=urlopen, clock=monotonic):
        self.timeout, self.opener, self.clock = timeout, opener, clock

    def supports(self, record):
        """Whether this curated identity has a fixed approved reference source."""
        return _url_for(record) is not None

    def source_key(self, record):
        """Fixed source URL for batching/grouping, or None when unsupported."""
        return _url_for(record)

    def _get(self, url, *, refresh, timeout):
        now = self.clock()
        with _lock:
            cached = _cache.get(url)
            if not refresh and cached and 0 <= now - cached[0] < CACHE_TTL:
                return deepcopy(cached[1])
        try:
            req = Request(url, headers={"User-Agent": "NEXUS-reference-check/1.0", "Accept": "text/html"})
            opener = self.opener
            if opener is urlopen:
                handlers = [_SafeRedirect()]
                if url == "https://cajadevalores.com.ar/Servicios/Cedears":
                    try:
                        import certifi
                        context = ssl.create_default_context(cafile=certifi.where())
                    except ImportError:
                        context = ssl.create_default_context()
                    handlers.append(HTTPSHandler(context=context))
                opener = build_opener(*handlers).open
            with opener(req, timeout=self.timeout if timeout is None else timeout) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else url
                if final_url not in ALLOWLIST: raise MarketDataError("La respuesta provino de una URL no permitida.")
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES: raise MarketDataError("La respuesta supera el tamaño permitido.")
            parsed = parse_reference(url, raw)
        except MarketDataError:
            raise
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MarketDataError("No pudimos consultar la fuente de referencia.") from exc
        with _lock: _cache[url] = (now, deepcopy(parsed))
        return parsed

    def research(self, record, *, refresh=False, today=None, timeout=None):
        result = deepcopy(record)
        url = _url_for(result)
        if not url:
            result["reference_status"] = "unsupported"
            return result
        results = self._get(url, refresh=refresh, timeout=timeout)
        lookup_id = result.get("education_id") if result.get("instrument_type") == "FCI" else result.get("canonical_id")
        found = results.get(lookup_id) or results.get(result.get("canonical_id"))
        if not found:
            result["reference_status"] = "source_unavailable"
            return result
        fields = found["fields"]
        result["reference_status"] = "identity_observed"
        conflicts = []
        for key, value in fields.items():
            if key == "name" and isinstance(result.get(key), str) and isinstance(value, str) and _key(result[key]) == _key(value):
                fields[key] = result[key]
        for key, value in fields.items():
            current = result.get(key)
            if key == "exposure" and current == "unknown":
                result[key] = deepcopy(value)
            elif current is not None and current != value:
                conflicts.append(f"{key}: curated={current!r}, observed={value!r}")
            elif current is None:
                result[key] = deepcopy(value)
        if conflicts:
            result["reference_status"] = "identity_conflict"
            result.setdefault("contradictions", []).extend(conflicts)
        elif result.get("instrument_type") == "FCI" and result.get("validation_status") in ("proposal", "expired"):
            result["validation_status"] = "observed"
        if found.get("scope") == "mandate":
            result["exposure_basis"] = "mandate"
        entry = {"source": url, "url": url, "fields": deepcopy(fields),
            "observed_at": found["observed_at"], "data_date": None, "expires_at": found["expires_at"],
            "kind": "observed", "version": "reference-v1",
            "source_type": found.get("source_type", _source_type_for_url(url))}
        if found.get("scope"):
            entry["scope"] = found["scope"]
        if found.get("raw_source_fields"):
            entry["raw_source_fields"] = deepcopy(found["raw_source_fields"])
        result.setdefault("evidence", []).append(entry)
        # Only source-backed identity fields are enriched; conflicts remain visible for review.
        return result
