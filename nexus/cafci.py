"""Read-only client for CAFCI's public FCI catalog and class detail pages.

This adapter reports published facts and mandate clues. It does not decide
whether an instrument is suitable or executable through a broker.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
import json
import math
import re
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener, urlopen
from html import unescape

from .market_data import MarketDataError


CATALOG_URL = "https://estadisticas.cafci.org.ar/consulta-de-fondos.json"
CONSULT_URL = "https://estadisticas.cafci.org.ar/consulta-avanzada"
DETAIL_BASE_URL = "https://estadisticas.cafci.org.ar/fondos/"
SOURCE = "CAFCI · catálogo público de fondos y clases"
CACHE_TTL_SECONDS = 900
MAX_CATALOG_BYTES = 8_000_000
MAX_DETAIL_BYTES = 2_000_000
MAX_DATA_AGE_DAYS = 7
_cache = {}
_cache_lock = Lock()


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value)
    return text if text.isdigit() else None


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _ref_name(value):
    if isinstance(value, dict):
        name = value.get("nombre")
        return name.strip() if isinstance(name, str) and name.strip() else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _currency(value):
    name = _ref_name(value)
    if not name:
        return None
    key = " ".join(name.casefold().replace("á", "a").split())
    if key in {"peso argentina", "peso argentino", "pesos argentinos", "ars"}:
        return "ARS"
    if key in {"dolar estadounidense", "dolar estadounidense billete", "usd", "us$"}:
        return "USD"
    return None


def _published_at(value, today=None):
    if not isinstance(value, str):
        raise MarketDataError("El catálogo CAFCI no publica una fecha válida.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MarketDataError("El catálogo CAFCI no publica una fecha válida.") from None
    if parsed.tzinfo is None:
        raise MarketDataError("La fecha del catálogo CAFCI no indica zona horaria.")
    parsed = parsed.astimezone(timezone.utc)
    today = today or datetime.now(timezone.utc).date()
    age = (today - parsed.date()).days
    if age < 0:
        raise MarketDataError("La fecha del catálogo CAFCI está en el futuro.")
    if age > MAX_DATA_AGE_DAYS:
        raise MarketDataError("El catálogo CAFCI está vencido; no se usa como universo vigente.")
    return parsed


def _detail_url(fund_id, class_id):
    fund_text, class_text = _safe_id(fund_id), _safe_id(class_id)
    if not fund_text or not class_text:
        raise MarketDataError("La identidad CAFCI requiere IDs numéricos de fondo y clase.")
    return f"{DETAIL_BASE_URL}{fund_text}?clase={class_text}"


class _SafeRedirect(HTTPRedirectHandler):
    """Allow only the CAFCI catalog or an ID-built public fund detail route."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        allowed = (parsed.scheme == "https" and parsed.hostname == "estadisticas.cafci.org.ar"
                   and parsed.port in (None, 443) and
                   (newurl == CATALOG_URL or re.fullmatch(r"https://estadisticas\.cafci\.org\.ar/fondos/\d+\?clase=\d+", newurl)))
        if not allowed:
            raise MarketDataError("CAFCI intentó redirigir fuera de sus rutas públicas permitidas.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = build_opener(_SafeRedirect(), HTTPSHandler())


def _fetch(url, *, limit, timeout, opener):
    req = Request(url, headers={"Accept": "application/json, text/html;q=0.9",
                               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
                               "Referer": CONSULT_URL})
    try:
        call = _SAFE_OPENER.open if opener is urlopen else opener
        with call(req, timeout=timeout) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else url
            parsed = urlparse(final_url)
            if (final_url != url or parsed.scheme != "https" or parsed.hostname != "estadisticas.cafci.org.ar"
                    or parsed.port not in (None, 443)):
                raise MarketDataError("La respuesta de CAFCI terminó fuera del dominio público permitido.")
            body = response.read(limit + 1)
    except MarketDataError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise MarketDataError("No pudimos consultar CAFCI. Podés volver a intentar.") from exc
    if len(body) > limit:
        raise MarketDataError("La respuesta CAFCI supera el tamaño permitido.")
    return body


def _mandate_hint(objective):
    if not isinstance(objective, str):
        return None
    key = " ".join(objective.casefold().replace("á", "a").replace("í", "i").split())
    if re.search(r"\b(cer|uva|inflacion|inflacionario|inflacionarios)\b", key):
        return {"category": "Renta fija inflación", "exposure": "inflation"}
    if re.search(r"dollar\s*linked|dolar\s*linked|tipo de cambio|tipo de cambio oficial", key):
        return {"category": "Renta fija cambiaria", "exposure": "fx"}
    return None


def _normalize(fund, klass, generated_at, observed_at, catalog_url):
    fund_id, class_id = _safe_id(fund.get("id")), _safe_id(klass.get("id"))
    if not fund_id or not class_id:
        return None
    fund_name, class_name = _ref_name(fund.get("nombre")), _ref_name(klass.get("nombre"))
    name = class_name or fund_name
    tipo = _ref_name(fund.get("tipo_renta"))
    currency = _currency(klass.get("moneda")) or _currency(fund.get("moneda"))
    minimum = _finite_number(klass.get("inversion_minima"))
    settlement = _finite_number(fund.get("dias_liquidacion"))
    objective = fund.get("objetivo") if isinstance(fund.get("objetivo"), str) else None
    category = exposure = basis = None
    hint = None
    if tipo == "Renta Variable":
        category, exposure = "Renta variable", "equity"
    elif tipo == "Mercado de Dinero":
        category, exposure = "Liquidez inmediata", "money_market"
    else:
        hint = _mandate_hint(objective)
        if hint:
            category, exposure, basis = hint["category"], hint["exposure"], "mandate"

    cid = f"AR:FCI:{fund_id}:{class_id}"
    raw_metadata = {
        "tipo_dinero": deepcopy(fund.get("tipo_dinero")),
        "valuacion": deepcopy(fund.get("valuacion")),
        "inicio": deepcopy(fund.get("inicio")),
        "tipo_renta": deepcopy(fund.get("tipo_renta")),
        "region": deepcopy(fund.get("region")),
        "duration": deepcopy(fund.get("duration")),
        "benchmark": deepcopy(fund.get("benchmark")),
        "horizonte": deepcopy(fund.get("horizonte")),
        "clase_suscripcion": deepcopy(klass.get("suscripcion")),
        "clase_liquidez": deepcopy(klass.get("liquidez")),
        "clase_log_abierto": deepcopy(klass.get("log_abierto")),
    }
    raw_fees = deepcopy(klass.get("honorarios")) if isinstance(klass.get("honorarios"), dict) else None
    backed = {"canonical_id": cid, "instrument_type": "FCI", "market": "AR:FCI",
              "underlying_id": f"AR:FCI:{fund_id}", "cafci_fund_id": int(fund_id),
              "cafci_class_id": int(class_id), "source_provider": "cafci"}
    if name:
        backed["name"] = name
    if currency:
        backed["quotation_currency"] = currency
    if category:
        backed.update({"category": category, "exposure": exposure})
    if basis:
        backed["exposure_basis"] = basis
    if minimum is not None:
        backed["minimum"] = minimum
    if settlement is not None:
        backed["settlement_days"] = settlement
    if objective:
        backed["description"] = objective
    raw_fields = {
        "fund_id": fund.get("id"), "class_id": klass.get("id"),
        "fund_name": fund.get("nombre"), "class_name": klass.get("nombre"),
        "objective": objective, "type": deepcopy(fund.get("tipo_renta")),
        "fund_currency": deepcopy(fund.get("moneda")),
        "class_currency": deepcopy(klass.get("moneda")),
        "minimum": deepcopy(klass.get("inversion_minima")),
        "settlement_days": deepcopy(fund.get("dias_liquidacion")),
        "fees": raw_fees,
        "manager": deepcopy(fund.get("sociedad_gerente")),
        "depository": deepcopy(fund.get("sociedad_depositaria")),
        "metadata": raw_metadata,
    }
    evidence = {"source": SOURCE, "url": catalog_url, "fields": backed,
                "raw_source_fields": raw_fields, "observed_at": observed_at,
                "data_date": generated_at.date().isoformat(),
                "expires_at": datetime.combine(generated_at.date() + timedelta(days=7), time.max,
                                                timezone.utc).isoformat(timespec="seconds"),
                "kind": "observed", "version": "catalog-v1"}
    missing_fields = ["subscription_currency", "economic_currency", "lot_size", "unit_price",
                      "costs", "liquidity", "access", "broker"]
    if currency is None:
        missing_fields.append("quotation_currency")
    if minimum is None:
        missing_fields.append("minimum")
    if settlement is None:
        missing_fields.append("settlement_days")
    if basis == "mandate":
        missing_fields.append("actual_exposure_or_holdings")
    record = {
        "canonical_id": cid, "instrument_type": "FCI", "ticker": None, "market": "AR:FCI",
        "stable_id": None, "underlying_id": f"AR:FCI:{fund_id}", "name": name,
        "source_provider": "cafci", "cafci_fund_id": int(fund_id), "cafci_class_id": int(class_id),
        "category": category, "exposure": exposure, "exposure_basis": basis,
        "category_hint": hint["category"] if hint else None,
        "exposure_hint": hint["exposure"] if hint else None,
        "quotation_currency": currency, "subscription_currency": None,
        "economic_currency": None, "minimum": minimum, "lot_size": None,
        "unit_price": None, "costs": None, "raw_fees": raw_fees,
        "settlement_days": settlement, "liquidity": "unknown", "access": "unknown",
        "broker": None, "issuer": _ref_name(fund.get("sociedad_gerente")),
        "issuer_role": "fund_manager", "depository": _ref_name(fund.get("sociedad_depositaria")),
        "sector": None, "country": "AR", "holdings": [], "holdings_details": [],
        "holdings_date": None, "holding_labels": [], "description": objective,
        "fund_objective": objective, "risks": [], "familiar": False,
        "familiarity_basis": None, "market_metric": None, "horizon": _ref_name(fund.get("horizonte")),
        "duration": _ref_name(fund.get("duration")), "benchmark": _ref_name(fund.get("benchmark")),
        "raw_metadata": raw_metadata, "validation_status": "observed",
        "reference_status": "catalog_observed", "contradictions": [],
        "missing_fields": missing_fields,
        "evidence": [evidence],
    }
    return record


class _DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cartera_depth = 0
        self.values_div_depth = None
        self.values_started_at_depth = 0
        self.in_values = False
        self.value_parts = []
        self.cartera_date = None
        self.chart = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and (attrs.get("id") == "cartera" or self.cartera_depth):
            self.cartera_depth += 1
        if tag == "div" and self.cartera_depth and "valores" in (attrs.get("class") or "").split():
            self.in_values = True
            self.value_parts = []
            self.values_div_depth = self.cartera_depth
        elif self.cartera_depth and tag == "canvas":
            raw = attrs.get("data-pie-chart-items-value")
            if raw:
                try:
                    payload = json.loads(unescape(raw))
                    if isinstance(payload, list):
                        self.chart = payload
                except (ValueError, TypeError):
                    self.chart = None

    def handle_endtag(self, tag):
        if tag == "div" and self.in_values and self.cartera_depth == self.values_div_depth:
            text = " ".join(" ".join(self.value_parts).split())
            match = re.fullmatch(r"Valores al (\d{2})/(\d{2})/(\d{4})", text, re.I)
            if match:
                day, month, year = map(int, match.groups())
                try:
                    self.cartera_date = date(year, month, day).isoformat()
                except ValueError:
                    self.cartera_date = None
            self.in_values = False
            self.values_div_depth = None
        if tag == "div" and self.cartera_depth:
            self.cartera_depth -= 1

    def handle_data(self, data):
        if self.in_values:
            self.value_parts.append(data)


def _parse_detail(body):
    parser = _DetailParser()
    parser.feed(body.decode("utf-8", "replace"))
    details, labels = [], []
    if parser.chart:
        for item in parser.chart:
            if not isinstance(item, dict):
                continue
            name = item.get("nombre")
            weight = _finite_number(item.get("porcentaje"))
            if not isinstance(name, str) or not name.strip() or weight is None or not 0 <= weight <= 100:
                continue
            name = name.strip()
            details.append({"name": name, "weight": weight})
            labels.append(name)
    return parser.cartera_date, details, labels


class CAFCIClient:
    def __init__(self, timeout=8, opener=urlopen, clock=monotonic):
        self.timeout, self.opener, self.clock = timeout, opener, clock

    def fund_catalog(self, refresh=False, today=None):
        now_mono = self.clock()
        with _cache_lock:
            cached = _cache.get(CATALOG_URL)
            if not refresh and cached and 0 <= now_mono - cached[0] < CACHE_TTL_SECONDS:
                payload, generated, observed = deepcopy(cached[1]), cached[2], cached[3]
                cache_hit = True
            else:
                payload = generated = observed = None
                cache_hit = False
        if payload is None:
            body = _fetch(CATALOG_URL, limit=MAX_CATALOG_BYTES, timeout=self.timeout, opener=self.opener)
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                raise MarketDataError("El catálogo CAFCI devolvió JSON inválido.") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("fondos"), list):
                raise MarketDataError("El catálogo CAFCI cambió de formato.")
            generated = _published_at(payload.get("generated_at"), today=today)
            observed = _utc_now()
            with _cache_lock:
                _cache[CATALOG_URL] = (now_mono, deepcopy(payload), generated, observed)
        else:
            generated = _published_at(generated.isoformat(), today=today)
        normalized, funds = [], []
        for fund in payload["fondos"]:
            if not isinstance(fund, dict):
                continue
            state = fund.get("estado")
            if isinstance(state, bool) or state != 1:
                continue
            classes = fund.get("clases")
            if not isinstance(classes, list):
                continue
            open_classes = []
            for klass in classes:
                if not isinstance(klass, dict) or klass.get("log_abierto") is not True:
                    continue
                record = _normalize(fund, klass, generated, observed, CATALOG_URL)
                if record is not None:
                    normalized.append(record)
                    open_classes.append(klass)
            if open_classes:
                public_fund = deepcopy(fund)
                public_fund["clases"] = open_classes
                funds.append(public_fund)
        return {"fondos": [], "normalized_records": normalized,
                "source_fund_count": len(funds), "source_class_count": len(normalized),
                "fuente": "CAFCI", "url": CATALOG_URL, "consultado_en": observed,
                "fecha_publicacion": generated.isoformat(timespec="seconds"),
                "cache": cache_hit, "documentacion": CONSULT_URL}


class CAFCIReferenceProvider:
    def __init__(self, timeout=4, opener=urlopen, clock=monotonic):
        self.timeout, self.opener, self.clock = timeout, opener, clock

    @staticmethod
    def supports(record):
        if not isinstance(record, dict) or record.get("source_provider") != "cafci":
            return False
        return bool(_safe_id(record.get("cafci_fund_id")) and _safe_id(record.get("cafci_class_id")))

    @staticmethod
    def source_key(record):
        if not CAFCIReferenceProvider.supports(record):
            return None
        try:
            return _detail_url(record["cafci_fund_id"], record["cafci_class_id"])
        except MarketDataError:
            return None

    def research(self, record, refresh=False, today=None, timeout=None):
        if not self.supports(record):
            raise MarketDataError("El registro no tiene identidad de fondo y clase CAFCI verificable.")
        url = _detail_url(record["cafci_fund_id"], record["cafci_class_id"])
        cache_key = url
        now_mono = self.clock()
        with _cache_lock:
            cached = _cache.get(cache_key)
            if not refresh and cached and 0 <= now_mono - cached[0] < CACHE_TTL_SECONDS:
                body, observed = bytes(cached[1]), cached[2]
                cache_hit = True
            else:
                body = observed = None
                cache_hit = False
        if body is None:
            body = _fetch(url, limit=MAX_DETAIL_BYTES, timeout=self.timeout if timeout is None else timeout, opener=self.opener)
            observed = _utc_now()
            with _cache_lock:
                _cache[cache_key] = (now_mono, bytes(body), observed)
        data_date, details, labels = _parse_detail(body)
        today_date = today or datetime.now(timezone.utc).date()
        untrusted_future_date = data_date if data_date and date.fromisoformat(data_date) > today_date else None
        if untrusted_future_date:
            raise MarketDataError("La composición CAFCI tiene una fecha futura; no se trata como dato observado.")
        if not data_date or not details:
            raise MarketDataError("La ficha CAFCI no contiene composición con fecha verificable.")
        result = deepcopy(record)
        result.update({"holdings_details": details, "holding_labels": labels,
                       "holdings": [], "holdings_date": data_date,
                       "reference_status": "details_observed"})
        expires = datetime.combine(date.fromisoformat(data_date) + timedelta(days=7), time.max,
                                   timezone.utc).isoformat(timespec="seconds")
        evidence_fields = {"holdings_details": deepcopy(details), "holdings_date": data_date}
        result.setdefault("evidence", []).append({
            "source": SOURCE, "url": url, "fields": evidence_fields,
            "raw_source_fields": {"holding_labels": labels, "untrusted_future_date": untrusted_future_date}, "observed_at": observed,
            "data_date": data_date, "expires_at": expires, "kind": "observed",
            "version": "detail-v1", "cache": cache_hit,
        })
        # These are labels and percentages, not stable instrument identities.
        # Do not promote them to `holdings` or replace mandate-only exposure.
        return result
