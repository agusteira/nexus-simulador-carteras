"""Explainable examples, kept separate from the deterministic allocation engine."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import unicodedata

from .market_data import ArgentinaDatosClient, MarketDataError, MAX_DATA_AGE_DAYS, valid_data_date


class _ResearchProviders:
    """Route by provider-supported identity, never by a preferred investment."""

    def __init__(self, *providers):
        self.providers = providers

    def _for(self, record):
        return next((provider for provider in self.providers if provider.supports(record)), None)

    def supports(self, record):
        return self._for(record) is not None

    def source_key(self, record):
        provider = self._for(record)
        return provider.source_key(record) if provider else None

    def research(self, record, **kwargs):
        provider = self._for(record)
        if provider is None:
            raise MarketDataError("No hay un proveedor habilitado para investigar este instrumento.")
        return provider.research(record, **kwargs)


def _text(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(c)).lower().split())


def _currency(value):
    return {"ars": "ARS", "pesos": "ARS", "peso argentino": "ARS", "pesos argentinos": "ARS",
            "$": "ARS", "usd": "USD", "dolares": "USD", "dolar estadounidense": "USD",
            "dolares estadounidenses": "USD", "us$": "USD"}.get(_text(value))


def execution_id(result, snapshot):
    base = {key: value for key, value in result.items() if key != "ejemplos_instrumentos"}
    encoded = json.dumps({"resultado": base, "entradas": snapshot}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fund_kind(fund):
    value = _text(fund.get("tipoRenta"))
    return {"renta variable": "variable", "renta fija": "fija", "mercado de dinero": "dinero",
            "mercado dinero": "dinero", "money market": "dinero", "mixta": "mixta",
            "renta mixta": "mixta"}.get(value)


def _rejection_reason(fund, category, currency, today, budget):
    """Return the first exclusion reason, so each source record is counted once."""
    kind = _fund_kind(fund)
    allowed = (category == "Renta variable" and kind == "variable") or (
        category == "Liquidez inmediata" and kind == "dinero") or (
        category in ("Renta fija inflación", "Renta fija cambiaria") and kind == "fija")
    if not allowed:
        return "categoria"
    name = fund.get("nombre")
    if not isinstance(name, str) or not name.strip() or not fund.get("fondoId") or not fund.get("claseId"):
        return "metadatos"
    if not valid_data_date(fund.get("fecha"), today):
        return "fecha"
    if _currency(fund.get("moneda")) != currency or _currency(fund.get("monedaInversion")) != currency:
        return "moneda"
    minimum = fund.get("inversionMinima")
    minimum_valid = isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and math.isfinite(minimum) and minimum >= 0
    if minimum is not None and not minimum_valid:
        return "minimo_invalido"
    if minimum_valid and minimum > budget:
        return "minimo_superior"
    return None


LIMITATIONS = {
    "Renta fija inflación": "La renta fija genérica no prueba ajuste por inflación. Hace falta identificar CER/UVA explícitamente y confirmar sus condiciones.",
    "Renta fija cambiaria": "Una moneda o un nombre comercial no prueban cobertura cambiaria. Hace falta una clasificación dollar-linked explícita y documentación del instrumento.",
    "Renta variable": "La categoría y la moneda permiten explorar ejemplos; el riesgo específico y las condiciones de cada fondo requieren revisión.",
    "Liquidez inmediata": "Un fondo de mercado de dinero no garantiza disponibilidad inmediata. Hay que confirmar plazo de liquidación, horarios de corte y rescate con la administradora.",
}


def _candidate(fund, source, category, currency, today, budget):
    """Return a candidate only from explicit metadata, never inferred names."""
    if _rejection_reason(fund, category, currency, today, budget):
        return None
    name = fund.get("nombre")
    dated = valid_data_date(fund.get("fecha"), today)
    minimum = fund.get("inversionMinima")
    minimum_valid = isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and math.isfinite(minimum) and minimum >= 0
    kind = _fund_kind(fund)
    matched, evidence = False, ""
    if category == "Renta variable" and kind == "variable":
        matched, evidence = True, "La fuente clasifica este fondo como renta variable y declara la misma moneda de denominación y de inversión que tu simulación."
    # T+0 is useful operational evidence, but never equated with instant access.
    if category == "Liquidez inmediata" and kind == "dinero":
        days = fund.get("plazoLiquidacionDias")
        if isinstance(days, (int, float)) and not isinstance(days, bool) and math.isfinite(days) and days == 0:
            evidence = "La fuente lo clasifica como mercado de dinero e informa liquidación T+0. Eso no certifica acceso inmediato: confirmá horarios y condiciones de rescate."
        else:
            evidence = "La fuente lo clasifica como mercado de dinero, pero no verificamos un plazo de rescate compatible con disponibilidad inmediata."
    elif category in ("Renta fija inflación", "Renta fija cambiaria") and kind == "fija":
        evidence = "Es un fondo de renta fija en tu moneda. La fuente no permite confirmar la exposición específica que pide esta categoría."
        if category == "Renta fija cambiaria" and _text(fund.get("benchmark")) == "a3500":
            evidence = "Declara benchmark A3500 (tipo de cambio de referencia mayorista). Un benchmark no demuestra cobertura efectiva: revisá cartera y documentación del fondo."
    if not evidence:
        return None
    if not minimum_valid:
        matched = False
        evidence += " No pudimos verificar la inversión mínima, por lo que queda como alternativa para investigar."
    return {
        "nombre": name.strip(), "identificador": f"{fund.get('fondoId', '')}/{fund.get('claseId', '')}",
        "tipo": fund.get("tipoRenta"), "moneda": currency, "fecha_dato": dated,
        "fuente": source["fuente"], "url_fuente": source["url"],
        "consultado_en": source["consultado_en"], "criterio": evidence,
        "riesgos": "Puede perder valor; revisá cartera, comisiones, inversión mínima y condiciones de rescate antes de decidir.",
        "plazo_liquidacion_dias": fund.get("plazoLiquidacionDias"),
        "inversion_minima_informada": fund.get("inversionMinima"),
        "administradora": fund.get("administradora"),
        "horizonte_informado": fund.get("horizonte"), "benchmark": fund.get("benchmark"),
        "valor_cuotaparte_reportado": (fund.get("rendimientos") or {}).get("valorCuotaparte") if isinstance(fund.get("rendimientos"), dict) else None,
        "compatibilidad_categoria": "clasificacion_verificada" if matched else "no_verificada",
    }


def build_examples(result, snapshot, catalogs, *, errors=None, today=None):
    """Freeze source evidence for THIS evaluation; no holdings or unit amounts."""
    today = today or datetime.now(timezone.utc).date()
    currency = result.get("moneda", (snapshot.get("perfil") or {}).get("moneda"))
    categories = []
    capital = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0))
    for category, weight in result.get("cartera_porcentual", {}).items():
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight <= 0:
            continue
        candidates = []
        budget = capital * weight / 100
        discarded_date = 0
        reasons = {key: 0 for key in ("categoria", "metadatos", "fecha", "moneda", "minimo_invalido", "minimo_superior")}
        reviewed = 0
        compatible_count = 0
        for source in catalogs:
            for fund in source.get("fondos", []):
                if not isinstance(fund, dict):
                    continue
                reviewed += 1
                if not valid_data_date(fund.get("fecha"), today):
                    discarded_date += 1
                reason = _rejection_reason(fund, category, currency, today, budget)
                if reason:
                    reasons[reason] += 1
                    continue
                item = _candidate(fund, source, category, currency, today, budget)
                if item:
                    candidates.append(item)
                    compatible_count += 1
        candidates.sort(key=lambda item: (0 if item["compatibilidad_categoria"] == "clasificacion_verificada" else 1,
                                         0 if category == "Renta fija cambiaria" and _text(item.get("benchmark")) == "a3500" else 1,
                                         item["nombre"].casefold(), item["identificador"]))
        unique = {}
        for candidate in candidates:
            unique.setdefault(candidate["identificador"].split("/")[0], candidate)
        candidates = list(unique.values())
        verified = [item for item in candidates if item["compatibilidad_categoria"] == "clasificacion_verificada"][:2]
        alternatives = [item for item in candidates if item["compatibilidad_categoria"] == "no_verificada"][:2]
        categories.append({"categoria": category, "peso": weight, "ejemplos": verified,
                           "alternativas": alternatives if not verified else [],
                           "limitacion": LIMITATIONS.get(category, "No tenemos datos suficientes para verificar ejemplos de esta categoría."),
                           "registros_sin_fecha_vigente": discarded_date, "monto_asignado": budget,
                           "diagnostico": {"registros_revisados": reviewed, "descartados": reasons,
                                           "candidatos_compatibles": compatible_count}})
    return {"ejecucion_id": execution_id(result, snapshot), "entradas_evaluacion": deepcopy(snapshot),
            "consultado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "moneda": currency, "ventana_datos_dias": MAX_DATA_AGE_DAYS,
            "categorias": categories, "errores_fuente": list(errors or []),
            "fuentes": [{key: source.get(key) for key in ("fuente", "url", "consultado_en", "cache", "fecha_publicacion", "documentacion")} for source in catalogs],
            "criterio_orden": "Hasta dos ejemplos por categoría, en orden alfabético. En cambiaria se prioriza el benchmark A3500 explícito, sin dar por verificada su cobertura. No es un ranking de rendimiento.",
            "advertencia": "Ejemplos para investigar, no una orden ni una recomendación personalizada. No se calculan cantidades ni rendimientos futuros."}


def query_examples(result, snapshot, *, refresh=False, client=None, today=None,
                   provider=None, store=None, limits=None):
    # Explicit clients/providers remain injectable for offline tests. The live
    # FCI universe is supplied by CAFCI, rather than a reviewed list of names.
    if client is not None and provider is None:
        provider = False
    if client is None:
        from .cafci import CAFCIClient, CAFCIReferenceProvider
        from .instrument_providers import ReferenceProvider
        client = CAFCIClient()
        if provider is None:
            provider = _ResearchProviders(CAFCIReferenceProvider(), ReferenceProvider())
    catalogs, errors = [], []
    try:
        catalogs.append(client.fund_catalog(refresh=refresh, today=today))
    except MarketDataError as exc:
        errors.append(str(exc))
    examples = build_examples(result, snapshot, catalogs, errors=errors, today=today)
    from .instrument_research import research_instruments
    examples["investigacion"] = research_instruments(
        result, snapshot, catalogs, refresh=refresh, today=today,
        provider=provider, store=store, limits=limits,
    )
    examples["investigacion"]["search"]["errors"] = list(errors) + examples["investigacion"]["search"].get("errors", [])
    examples["investigacion"]["source_coverage"] = [
        {"source": source.get("fuente"), "url": source.get("url"),
         "published_at": source.get("fecha_publicacion"),
         "candidate_count": len(source.get("normalized_records", [])) + len(source.get("fondos", [])),
         "classes": ["FCI"]}
        for source in catalogs
    ]
    return examples
