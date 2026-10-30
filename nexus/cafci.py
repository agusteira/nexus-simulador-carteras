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
import unicodedata
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
MAX_HOLDINGS_AGE_DAYS = 35
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
    if key in {"dolar estadounidense", "usd", "us$"}:
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


def _mandate_hints(objective):
    if not isinstance(objective, str):
        return []
    normalized = unicodedata.normalize("NFKD", objective.casefold())
    key = " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())
    hints = []
    if re.search(r"\b(cer|uva|inflacion(?:aria|ario|arias|arios)?)\b", key):
        hints.append({"category": "Renta fija inflación", "exposure": "inflation"})
    if re.search(r"dollar[\s-]*linked|dolar[\s-]*linked|tipo de cambio(?: oficial)?", key):
        hints.append({"category": "Renta fija cambiaria", "exposure": "fx"})
    return hints


def _mandate_hint(objective):
    """Backward-compatible single hint for callers outside this adapter."""
    hints = _mandate_hints(objective)
    return hints[0] if hints else None


def _fee_value(raw):
    value = _finite_number(raw)
    return value if value is not None and value >= 0 else None


def _annual_fee_metadata(raw_fees):
    raw_fees = raw_fees if isinstance(raw_fees, dict) else {}
    keys = ("administracion_gerente", "administracion_depositaria", "gasto_ordinario_gestion")
    components = {key: _fee_value(raw_fees.get(key)) for key in keys}
    annual = sum(components.values()) if all(value is not None for value in components.values()) else None
    return components, annual


def _daily_facts(record, observation, observed_at):
    daily_date = observation.get("daily_date")
    if not isinstance(daily_date, date):
        return
    expires = datetime.combine(daily_date + timedelta(days=MAX_DATA_AGE_DAYS), time.max,
                               timezone.utc).isoformat(timespec="seconds")
    fields = {"daily_date": daily_date.isoformat()}
    record["daily_date"] = daily_date.isoformat()
    qualified = observation.get("qualified_only")
    if isinstance(qualified, bool):
        record["qualified_only"] = qualified
        fields["qualified_only"] = qualified
    fund_aum = observation.get("fund_aum")
    if isinstance(fund_aum, (int, float)) and not isinstance(fund_aum, bool) and math.isfinite(fund_aum) and fund_aum >= 0:
        record["fund_aum"] = fund_aum
        fields["fund_aum"] = fund_aum
        metric = {"metric": "patrimonio_clase", "value": fund_aum,
                  "currency": record.get("fund_currency_label"), "period": daily_date.isoformat(),
                  "market": "AR:FCI", "source": "CAFCI"}
        record["market_metric"] = metric
        fields["market_metric"] = deepcopy(metric)
    nav = observation.get("nav_per_thousand")
    if isinstance(nav, (int, float)) and not isinstance(nav, bool) and math.isfinite(nav) and nav >= 0:
        record["nav_per_thousand"] = nav
        record["nav_date"] = daily_date.isoformat()
        fields.update({"nav_per_thousand": nav, "nav_date": daily_date.isoformat(),
                       "daily_date": daily_date.isoformat()})
    if fields:
        record.setdefault("evidence", []).append({
            "source": "CAFCI · Planilla Diaria", "url": "https://api.pub.cafci.org.ar/pb_get",
            "fields": fields, "raw_source_fields": {"calificacion": observation.get("calificacion"),
                                                        "market_share": observation.get("market_share")},
            "observed_at": observed_at, "data_date": daily_date.isoformat(), "expires_at": expires,
            "kind": "observed", "version": "daily-v1",
        })


def _normalize(fund, klass, generated_at, observed_at, catalog_url):
    fund_id, class_id = _safe_id(fund.get("id")), _safe_id(klass.get("id"))
    if not fund_id or not class_id:
        return None
    fund_name, class_name = _ref_name(fund.get("nombre")), _ref_name(klass.get("nombre"))
    name = class_name or fund_name
    tipo = _ref_name(fund.get("tipo_renta"))
    class_currency_label = _ref_name(klass.get("moneda"))
    currency = _currency(klass.get("moneda")) if class_currency_label else _currency(fund.get("moneda"))
    minimum = _finite_number(klass.get("inversion_minima"))
    settlement = _finite_number(fund.get("dias_liquidacion"))
    objective = fund.get("objetivo") if isinstance(fund.get("objetivo"), str) else None
    category = exposure = basis = None
    hints = []
    if tipo == "Renta Variable":
        category, exposure = "Renta variable", "equity"
    elif tipo == "Mercado de Dinero":
        category, exposure = "Liquidez inmediata", "money_market"
    else:
        hints = _mandate_hints(objective)
        if len(hints) == 1:
            category, exposure, basis = hints[0]["category"], hints[0]["exposure"], "mandate"
        elif hints:
            basis = "mandate"

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
        "fund_currency_label": _ref_name(klass.get("moneda")) or _ref_name(fund.get("moneda")),
        "clase_suscripcion": deepcopy(klass.get("suscripcion")),
        "clase_liquidez": deepcopy(klass.get("liquidez")),
        "clase_log_abierto": deepcopy(klass.get("log_abierto")),
        "mm_puro": deepcopy(fund.get("mm_puro")), "mm_indice": deepcopy(fund.get("mm_indice")),
        "rg384": deepcopy(klass.get("rg384", fund.get("rg384"))),
        "tipo_renta_mixta": deepcopy(fund.get("tipo_renta_mixta")),
        "codigo_cnv": deepcopy(klass.get("codigo_cnv", fund.get("codigo_cnv"))),
        "codigo_cnv_clase": deepcopy(klass.get("codigo_cnv")),
        "codigo_cnv_fondo": deepcopy(fund.get("codigo_cnv")),
    }
    raw_fees = deepcopy(klass.get("honorarios")) if isinstance(klass.get("honorarios"), dict) else None
    fee_components, annual_fee = _annual_fee_metadata(raw_fees)
    fee_derived = {"method": "suma de administración gerente, administración depositaria y gasto ordinario de gestión; solo cuando los tres campos numéricos no negativos están publicados",
                   "source": "CAFCI · catálogo y reportes regulatorios", "source_url": catalog_url,
                   "basis": "porcentual anual según nomenclatura regulatoria", "components": deepcopy(fee_components)}
    fund_open = fund.get("estado") == 1 and not isinstance(fund.get("estado"), bool)
    subscription_open = klass.get("suscripcion") if isinstance(klass.get("suscripcion"), bool) else None
    redemption_open = klass.get("liquidez") if isinstance(klass.get("liquidez"), bool) else None
    fund_currency_label = class_currency_label or _ref_name(fund.get("moneda"))
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
    backed.update({"fund_open": fund_open, "subscription_open": subscription_open,
                   "redemption_open": redemption_open, "fund_currency_label": fund_currency_label,
                   "mm_pure": fund.get("mm_puro") if isinstance(fund.get("mm_puro"), bool) else None,
                   "mm_kind": _ref_name(fund.get("tipo_dinero")), "horizon": _ref_name(fund.get("horizonte")),
                   "duration": _ref_name(fund.get("duration"))})
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
        "mm_puro": deepcopy(fund.get("mm_puro")), "mm_indice": deepcopy(fund.get("mm_indice")),
        "rg384": deepcopy(klass.get("rg384", fund.get("rg384"))),
        "tipo_renta_mixta": deepcopy(fund.get("tipo_renta_mixta")),
        "codigo_cnv": deepcopy(klass.get("codigo_cnv", fund.get("codigo_cnv"))),
        "codigo_cnv_clase": deepcopy(klass.get("codigo_cnv")),
        "codigo_cnv_fondo": deepcopy(fund.get("codigo_cnv")),
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
        "category_hint": hints[0]["category"] if len(hints) == 1 else None,
        "exposure_hint": hints[0]["exposure"] if len(hints) == 1 else None,
        "category_hints": [hint["category"] for hint in hints],
        "quotation_currency": currency, "subscription_currency": None, "fund_currency_label": fund_currency_label,
        "economic_currency": None, "minimum": minimum, "lot_size": None,
        "unit_price": None, "costs": None, "raw_fees": raw_fees,
        "fund_fee_components_annual_pct": fee_components, "fund_fee_annual_pct": annual_fee,
        "fund_fee_inference": fee_derived,
        "entry_fee_pct": _fee_value(raw_fees.get("ingreso")) if raw_fees else None,
        "redemption_fee_pct": _fee_value(raw_fees.get("rescate")) if raw_fees else None,
        "settlement_days": settlement, "liquidity": "unknown", "access": "unknown",
        "fund_open": fund_open, "subscription_open": subscription_open, "redemption_open": redemption_open,
        "qualified_only": None, "fund_aum": None, "nav_per_thousand": None, "nav_date": None, "daily_date": None,
        "mm_pure": fund.get("mm_puro") if isinstance(fund.get("mm_puro"), bool) else None,
        "mm_kind": _ref_name(fund.get("tipo_dinero")),
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
    def __init__(self, timeout=8, opener=urlopen, clock=monotonic, daily_client=None):
        self.timeout, self.opener, self.clock = timeout, opener, clock
        if daily_client is False:
            self.daily_client = None
        elif daily_client is None:
            from .cafci_daily import CAFCIDailyClient
            self.daily_client = CAFCIDailyClient(timeout=timeout, opener=opener, clock=clock)
        else:
            self.daily_client = daily_client

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
        source_errors = []
        daily_source = None
        if self.daily_client is not None:
            try:
                daily_source = self.daily_client.class_observations(refresh=refresh, today=today)
            except MarketDataError as exc:
                source_errors.append(str(exc))
        if daily_source:
            observations = daily_source.get("observations") or {}
            daily_observed_at = daily_source.get("observed_at") or _utc_now()
            for record in normalized:
                observation = observations.get(record.get("cafci_class_id"))
                if observation:
                    _daily_facts(record, observation, daily_observed_at)
        return {"fondos": [], "normalized_records": normalized,
                "source_fund_count": len(funds), "source_class_count": len(normalized),
                "fuente": "CAFCI", "url": CATALOG_URL, "consultado_en": observed,
                "fecha_publicacion": generated.isoformat(timespec="seconds"),
                "cache": cache_hit, "documentacion": CONSULT_URL,
                "source_errors": source_errors,
                "daily_source": ({key: daily_source.get(key) for key in ("source", "url", "observed_at", "cache")}
                                 if daily_source else None),
                "daily_match_count": sum(record.get("daily_date") is not None for record in normalized)}


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
        if (today_date - date.fromisoformat(data_date)).days > MAX_HOLDINGS_AGE_DAYS:
            raise MarketDataError("La composición CAFCI supera la ventana histórica permitida.")
        result = deepcopy(record)
        result.update({"holdings_details": details, "holding_labels": labels,
                       "holdings": [], "holdings_date": data_date,
                       "reference_status": "details_observed"})
        expires = datetime.combine(date.fromisoformat(data_date) + timedelta(days=MAX_HOLDINGS_AGE_DAYS), time.max,
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
