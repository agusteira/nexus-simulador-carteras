"""Argentina instrument recommendation rules, separated from order execution.

The module deliberately keeps unknown broker, funding and execution facts
unknown. It consumes evidence emitted by CAFCI/BYMADATA adapters and never
turns a mandate, ticker or product name into observed exposure.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re
import unicodedata
from urllib.parse import urlparse


SELECTION_SCOPE = "instrument_recommendation"
_ALLOWED_TYPES = {"FCI", "LOCAL_SHARE", "CEDEAR"}
_CATEGORIES = {"Renta variable": "equity", "Renta fija inflación": "inflation",
               "Renta fija cambiaria": "fx", "Liquidez inmediata": "money_market"}
_UNDATED_PRODUCT_FIELDS = {
    "canonical_id", "instrument_type", "ticker", "market", "name", "stable_id",
    "category", "exposure", "underlying_type_source", "underlying_id",
    "underlying_name", "underlying_ticker", "underlying_market", "issuer",
    "issuer_role", "underlying_issuer_role",
}
_UNDATED_SNAPSHOT_FIELDS = {
    "canonical_id", "instrument_type", "ticker", "market", "quotation_currency",
    "reference_offer_price", "reference_offer_quantity", "reference_bid_price",
    "reference_bid_quantity", "quote_volume", "quote_volume_amount",
    "market_metric", "settlement_days",
}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fee_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _dt(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _evidence(record, field, today, *, max_age=7, scope=None, max_minutes=None):
    value = record.get(field)
    if value is None:
        return []
    matches = []
    now = datetime.now(timezone.utc)
    for evidence in record.get("evidence") or []:
        if not isinstance(evidence, dict) or evidence.get("kind") != "observed":
            continue
        fields = evidence.get("fields")
        if not isinstance(fields, dict) or fields.get(field) != value:
            continue
        if scope and evidence.get("scope") != scope:
            continue
        observed = _dt(evidence.get("observed_at"))
        expiry = _dt(evidence.get("expires_at"))
        url = urlparse(evidence.get("url", ""))
        if not observed or not expiry or expiry < observed or not evidence.get("source") or url.scheme != "https" or not url.netloc:
            continue
        if observed > now or expiry < now or observed.date() > today or expiry.date() < today:
            continue
        if max_minutes is not None:
            reference_now = datetime.now(timezone.utc)
            if observed > reference_now or (reference_now - observed).total_seconds() > max_minutes * 60 or expiry < reference_now:
                continue
        else:
            data_date_value = evidence.get("data_date")
            if data_date_value is None:
                # BYMA product identity is undated by the source; it may
                # support identity/category only, never a financial fact.
                scope_fields = (_UNDATED_PRODUCT_FIELDS if evidence.get("scope") == "product_identity"
                                else _UNDATED_SNAPSHOT_FIELDS if evidence.get("scope") == "market_snapshot"
                                else set())
                if field not in scope_fields:
                    continue
                data_date = observed.date()
            elif isinstance(data_date_value, str):
                try:
                    data_date = date.fromisoformat(data_date_value[:10])
                except ValueError:
                    continue
            else:
                continue
            if data_date > today or (today - data_date).days > max_age:
                continue
        matches.append(evidence)
    return matches


def _has(record, field, today, max_age=7):
    return bool(_evidence(record, field, today, max_age=max_age))


def _conflicting_evidence(record, field, today, max_age=7, *, scope=None):
    current = record.get(field)
    for evidence in record.get("evidence") or []:
        fields = evidence.get("fields") if isinstance(evidence, dict) else None
        if not isinstance(fields, dict) or field not in fields or fields[field] == current:
            continue
        probe = deepcopy(record)
        probe[field] = fields[field]
        if _evidence(probe, field, today, max_age=max_age, scope=scope):
            return True
    return False


def _missing_fields(record, fields, today, max_age=7):
    missing = []
    for field in fields:
        if record.get(field) is None or record.get(field) == "" or record.get(field) == "unknown":
            missing.append(field)
        elif not _has(record, field, today, max_age):
            missing.append(field + "_evidence")
    return missing


def _execution_checks(record):
    missing = ["broker", "broker_fees", "cash_subscription_route", "account_authorization",
               "final_execution_price", "order_quantity", "broker_settlement_confirmation"]
    if record.get("instrument_type") == "FCI":
        missing.extend(["broker_subscription_currency", "broker_redemption_channel"])
    return {"status": "PENDIENTE_INTERMEDIARIO", "missing_fields": missing,
            "reasons": ["La selección del instrumento no valida una orden ni una cuenta concreta.",
                        "Los cargos, el canal de fondeo y la autorización del intermediario permanecen sin verificar."]}


def _raw_fee_evidence(record, today):
    raw_fees = record.get("raw_fees")
    if not isinstance(raw_fees, dict):
        return None
    fee_keys = ("administracion_gerente", "administracion_depositaria", "gasto_ordinario_gestion")
    for item in record.get("evidence") or []:
        raw_source = item.get("raw_source_fields") if isinstance(item, dict) else None
        source_fees = raw_source.get("fees") if isinstance(raw_source, dict) else None
        if not isinstance(source_fees, dict) or item.get("kind") != "observed":
            continue
        # CAFCI may encode a percentage as a JSON string in raw_source_fields
        # and as a number in the same normalized record. Match its fee facts
        # numerically instead of requiring byte-for-byte container equality.
        if any(_fee_number(source_fees.get(key)) is None
               or _fee_number(source_fees.get(key)) != _fee_number(raw_fees.get(key))
               for key in fee_keys):
            continue
        try:
            data_date = date.fromisoformat(str(item.get("data_date"))[:10])
            observed, expiry = _dt(item.get("observed_at")), _dt(item.get("expires_at"))
            now = datetime.now(timezone.utc)
            if (data_date <= today and (today - data_date).days <= 7 and observed
                    and expiry and expiry >= observed and observed <= now and expiry >= now
                    and observed.date() <= today and expiry.date() >= today
                    and item.get("source") and urlparse(item.get("url", "")).scheme == "https"
                    and urlparse(item.get("url", "")).netloc):
                return item
        except (ValueError, TypeError):
            continue
    return None


def _annual_fund_fee(record, today):
    raw_fees = record.get("raw_fees")
    evidence = _raw_fee_evidence(record, today)
    if not isinstance(raw_fees, dict) or evidence is None:
        return None, None
    components = ("administracion_gerente", "administracion_depositaria", "gasto_ordinario_gestion")
    values = []
    for key in components:
        value = _fee_number(raw_fees.get(key))
        if value is None:
            return None, evidence
        values.append(value)
    annual = sum(values)
    return annual, evidence


def _reported_fee_mismatch(record, annual):
    components = ("administracion_gerente", "administracion_depositaria", "gasto_ordinario_gestion")
    reported = record.get("fund_fee_components_annual_pct")
    if isinstance(reported, dict):
        for key in components:
            value = _fee_number(reported.get(key))
            raw = _fee_number((record.get("raw_fees") or {}).get(key))
            if value is not None and raw is not None and not math.isclose(value, raw, rel_tol=0, abs_tol=1e-9):
                return True
    total = record.get("fund_fee_annual_pct")
    return _finite(total) and not math.isclose(total, annual, rel_tol=0, abs_tol=1e-8)


def _positive_selection_explanation(record, context, annual_fee, *, today):
    items = []
    category = context.get("category")
    currency = record.get("quotation_currency") or "moneda no informada"
    budget = context.get("budget")
    minimum = record.get("minimum")
    if record.get("instrument_type") == "FCI" and _finite(minimum) and _finite(budget):
        entry = _fee_number((record.get("raw_fees") or {}).get("ingreso"))
        entry_evidence = _raw_fee_evidence(record, today)
        floor = minimum * (1 + entry / 100) if entry is not None and entry_evidence else minimum
        items.append(
            f"Mínimo publicado {minimum:g} {currency} (cota con ingreso conocido {floor:g}); "
            f"presupuesto simulado {budget:g} {currency}; la moneda coincide."
        )
    elif record.get("instrument_type") in ("LOCAL_SHARE", "CEDEAR") and _finite(record.get("indicative_minimum")) and _finite(budget):
        items.append(
            f"Cota indicativa para una unidad: {record['indicative_minimum']:g} {currency}; "
            f"presupuesto simulado {budget:g} {currency} y moneda coincidente, antes de gastos; no se calcula cantidad."
        )
    if record.get("instrument_type") == "FCI":
        horizon = record.get("horizon")
        duration = record.get("duration")
        user_horizon = context.get("horizon_months")
        detail = None
        if horizon or duration:
            detail = f"Horizonte CAFCI {horizon}" if horizon else "Horizonte CAFCI flexible"
            if duration:
                detail += f", duración publicada {duration}"
            if _finite(user_horizon):
                detail += f"; el escenario prevé {user_horizon:g} meses."
        settlement = record.get("settlement_days")
        if _finite(settlement):
            detail = (detail + "; " if detail else "") + f"rescate publicado T+{settlement:g} (sujeto a días hábiles, horario y canal)."
        if detail:
            items.append(detail)
    if category in ("Renta fija inflación", "Renta fija cambiaria"):
        derived = record.get("derived_exposure")
        key = "inflation" if category == "Renta fija inflación" else "fx"
        if isinstance(derived, dict) and _finite(derived.get(key)):
            label = "exposición CER/UVA identificada" if key == "inflation" else "exposición vinculada al dólar identificada"
            items.append(
                f"Composición publicada {record.get('derived_exposure_date')}: "
                f"{derived[key]:g}% de renglones con {label}; el resto queda desconocido."
            )
    elif category == "Liquidez inmediata":
        items.append("La clase está identificada como mercado de dinero y el rescate informado es T+0; no es un depósito garantizado ni disponibilidad 24/7.")
    elif category == "Renta variable":
        if record.get("instrument_type") in ("LOCAL_SHARE", "CEDEAR"):
            spread = context.get("_ranking_factors", {}).get("observed_spread")
            items.append("La ficha acredita el instrumento de renta variable admitido; su cotización puede fluctuar y no se ha cuantificado su riesgo total.")
        else:
            items.append("La fuente clasifica la exposición como renta variable; la concentración y el riesgo total no se afirman como medidos.")
    if annual_fee is not None:
        fee_date = (record.get("fund_fee_inference") or {}).get("data_date")
        items.append(
            f"Gastos anuales del fondo derivados de componentes CAFCI publicados: {annual_fee:g}% "
            f"(porcentaje del fondo, fecha {fee_date}; no es costo en pesos ni arancel del intermediario)."
        )
    if record.get("instrument_type") in ("LOCAL_SHARE", "CEDEAR"):
        offer, bid = record.get("reference_offer_price"), record.get("reference_bid_price")
        if _finite(offer) and _finite(bid) and offer > 0:
            spread_pct = (offer - bid) / offer * 100
            items.append(
                f"Snapshot BYMADATA observado: bid {bid:g}, offer {offer:g}, spread {spread_pct:.3g}%; "
                "la fecha del último negocio no está informada y el precio no es ejecutable."
            )
    # Keep a concise, repeatable set of the facts that actually support the
    # selection. Broker and data-age caveats remain in separate warnings/checks.
    return list(dict.fromkeys(items))[:5]


def _selection_warnings(record, annual_fee, today):
    warnings = []
    if record.get("instrument_type") == "FCI" and annual_fee is None:
        warnings.append("Los componentes de gastos anuales no están completos o no tienen evidencia vigente; no se interpretan como cero.")
    if record.get("derived_exposure_date"):
        try:
            age = (today - date.fromisoformat(str(record["derived_exposure_date"])[:10])).days
            if 7 < age <= 35:
                warnings.append("La composición es la última publicada, tiene más de siete días y no representa las tenencias de hoy.")
        except ValueError:
            pass
    if record.get("instrument_type") == "FCI" and record.get("exposure") == "equity":
        warnings.append("La clasificación como renta variable no mide por sí sola el riesgo total ni la concentración de la cartera.")
    elif record.get("instrument_type") in ("LOCAL_SHARE", "CEDEAR"):
        warnings.append("El precio de referencia no es ejecutable y la fecha del último negocio no está informada.")
    if record.get("category") == "Liquidez inmediata" or record.get("derived_selection_category") == "Liquidez inmediata":
        warnings.append("Mercado de dinero no es un depósito garantizado; el rescate depende de días hábiles, horarios y canal.")
    return list(dict.fromkeys(warnings))


def _recommendation_concentration(record, context, field, today, max_age_days):
    """Concentration check that accepts BYMA's undated product identity facts."""
    from .instrument_rules import _concentration
    if field != "issuer" or record.get("instrument_type") not in ("LOCAL_SHARE", "CEDEAR"):
        return _concentration(record, context, field, today, max_age_days)
    def economic_issuer(candidate):
        if candidate.get("instrument_type") == "CEDEAR":
            value_field, role_field = "underlying_name", "underlying_issuer_role"
        else:
            value_field, role_field = "issuer", "issuer_role"
        value, role = candidate.get(value_field), candidate.get(role_field)
        identity = [item for item in _evidence(candidate, value_field, today, scope="product_identity")
                    if "fields" in item and item["fields"].get(role_field) == role]
        return value, role, identity

    value, role, identity_evidence = economic_issuer(record)
    if role != "economic_issuer" or not isinstance(value, str) or not value.strip() or not identity_evidence:
        return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": []}
    weight = context.get("allocation_weight")
    if not _finite(weight) or weight < 0:
        return {"value": value, "total_weight_percent": None, "status": "unknown",
                "provenance": identity_evidence}
    total = weight
    provenance = list(identity_evidence)
    for selected in context.get("already_selected") or []:
        selected_value, selected_role, selected_evidence = economic_issuer(selected)
        if selected_value is None or selected_role != "economic_issuer":
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        selected_weight = selected.get("allocation_weight")
        if not selected_evidence or not _finite(selected_weight) or selected_weight < 0:
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        if selected_value == value:
            total += selected_weight
            provenance.extend(selected_evidence)
    return {"value": value, "total_weight_percent": total, "status": "known",
            "provenance": provenance}


def _exposure_share(record, target, today, policy):
    details = record.get("holdings_details")
    data_date = record.get("holdings_date")
    max_age = policy.get("recommendation", {}).get("composition_max_age_days", 35)
    evidence = _evidence(record, "holdings_details", today, max_age=max_age)
    if not isinstance(details, list) or not details or not evidence or not _evidence(record, "holdings_date", today, max_age=max_age):
        return None, ["holdings_details", "holdings_date"]
    try:
        parsed_date = date.fromisoformat(str(data_date)[:10])
    except (ValueError, TypeError):
        return None, ["holdings_date"]
    if parsed_date > today or (today - parsed_date).days > max_age:
        return None, ["holdings_date_freshness"]
    total = specific = 0.0
    trace = []
    for row in details:
        if not isinstance(row, dict):
            return None, ["holdings_details_invalid"]
        label = str(row.get("name") or row.get("label") or "")
        weight = row.get("weight_percent", row.get("weight", row.get("porcentaje")))
        if not _finite(weight) or weight < 0:
            return None, ["holdings_weight_invalid"]
        total += weight
        text = unicodedata.normalize("NFKD", label.casefold())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"\s+", " ", text)
        # A holding row that names another FCI/fund does not identify its
        # underlying assets. Its own mandate words cannot prove exposure.
        opaque_fund = bool(re.search(r"\b(fci|fondo|fund|etf|cuotapartes?)\b|fondo comun de inversion", text))
        if target == "inflation":
            explicit_instrument = bool(
                re.search(r"\bboncer\b", text)
                or re.search(r"\b(bono|letra|titulo)\b[^.;]{0,80}\b(cer|uva)\b", text)
                or re.search(r"\bplazo fijo\b[^.;]{0,80}\buva\b", text))
            match = explicit_instrument and not opaque_fund
        else:
            match = (bool(re.search(r"(dollar\s*[- ]?linked|dolar\s*[- ]?linked|vinculad[oa]s?\s+(al\s+)?dolar|tipo\s+de\s+cambio)", text))
                     and not opaque_fund)
        if match:
            specific += weight
            trace.append({"label": label, "weight_percent": weight, "classification": target + "_explicit_term"})
    if total > 101:
        return None, ["holdings_total_invalid"]
    return { "percent": specific, "total_percent": total, "date": str(data_date), "trace": trace,
             "method": "Suma de porcentajes publicados cuyos rótulos contienen términos explícitos de exposición; otros renglones quedan desconocidos.",
             "source_evidence": evidence[0]}, []


def _fund_horizon(record, context, missing, policy, today):
    horizon = context.get("horizon_months")
    if not _finite(horizon) or horizon <= 0:
        missing.append("context.horizon_months")
        return
    name = str(record.get("horizon") or "").casefold()
    configured = policy.get("recommendation", {}).get("fund_horizon_min_months", {})
    mins = {str(key).casefold(): value for key, value in configured.items()}
    flexible = "flexible" in name
    floor = None if flexible else next((n for key, n in mins.items() if key in name), None)
    if floor is None and not flexible:
        missing.append("horizon")
    elif floor is not None and horizon < floor:
        missing.append("horizon_incompatible")
    duration = str(record.get("duration") or "").casefold()
    configured_duration = policy.get("recommendation", {}).get("fund_duration_max_months", {})
    duration_max = next((value for key, value in configured_duration.items()
                         if str(key).casefold() == duration), None)
    needs_duration = (context.get("category") in ("Renta fija inflación", "Renta fija cambiaria")
                      or record.get("category") in ("Renta fija inflación", "Renta fija cambiaria")
                      or flexible)
    if needs_duration and (record.get("duration") is None or not _has(record, "duration", today, 7)):
        missing.append("duration" if record.get("duration") is None else "duration_evidence")
    if needs_duration:
        if duration_max is None:
            missing.append("duration")
        elif horizon < duration_max:
            missing.append("duration_incompatible")


def evaluate_recommendation(record, context, *, today=None, policy=None):
    """Evaluate a candidate for an Argentina instrument recommendation."""
    from .instrument_rules import load_policy, _concentration
    policy = policy or load_policy()
    recommendation = policy.get("recommendation", {})
    today = today or datetime.now(timezone.utc).date()
    r = deepcopy(record) if isinstance(record, dict) else {}
    context = context or {}
    missing, reasons, rules = [], [], []
    excluded = False
    requires_review = bool(r.get("contradictions") or r.get("validation_status") == "review")
    def add(rule, reason):
        if rule not in rules:
            rules.append(rule)
        reasons.append(reason)
    if r.get("contradictions") or r.get("validation_status") == "review":
        add("R_CONTRADICCION", "Hay datos contradictorios que requieren revisión.")
    itype = r.get("instrument_type")
    market = r.get("market")
    if itype not in _ALLOWED_TYPES or market not in ("AR:FCI", "BYMA"):
        excluded = True
        add("R_MERCADO_NO_ADMITIDO", "La política solo evalúa FCI argentinos y valores BYMA de tipo admitido.")
    if itype in ("CRYPTO", "CRYPTO_FUND") or str(r.get("exposure") or "").casefold() == "bitcoin":
        excluded = True
        add("R_CRYPTO_POLICY", "La política de recomendación excluye criptoactivos y exposición Bitcoin.")
    category = context.get("category")
    if category not in _CATEGORIES:
        missing.append("context.category")
    mandate_hints = r.get("category_hints") if isinstance(r.get("category_hints"), list) else []
    sibling_mandate_category = (itype == "FCI" and r.get("exposure_basis") == "mandate"
                                and category in mandate_hints)
    if (category in _CATEGORIES and r.get("category") and r.get("category") != category
            and not sibling_mandate_category):
        excluded = True
        add("R_CATEGORIA_INCOMPATIBLE", "La categoría evidenciada no coincide con la asignación.")
    identity_fields = ["canonical_id", "instrument_type", "market", "quotation_currency"]
    missing.extend(_missing_fields(r, identity_fields, today, 30))
    for field in identity_fields:
        if _conflicting_evidence(r, field, today, 30):
            requires_review = True
            add("R_CONTRADICCION", f"Fuentes vigentes discrepan sobre {field}.")
    if not isinstance(r.get("name"), str) or not r["name"].strip():
        missing.append("name")
    if market == "BYMA" and not _evidence(r, "name", today, scope="product_identity"):
        missing.append("product_name_evidence")
    elif isinstance(r.get("name"), str) and r["name"].strip() and not _has(r, "name", today, 30):
        missing.append("name_evidence")
    currency = context.get("currency")
    if not isinstance(currency, str) or not currency or currency == "unknown":
        missing.append("context.currency")
    elif r.get("quotation_currency") and r["quotation_currency"] != currency:
        excluded = True
        add("R_MONEDA_INCOMPATIBLE", "La moneda de cotización no coincide con la moneda simulada.")
    defer_mandate_exposure = (itype == "FCI" and category in ("Renta fija inflación", "Renta fija cambiaria")
                              and r.get("exposure_basis") == "mandate"
                              and (sibling_mandate_category or r.get("category") is None))
    if (r.get("category") not in _CATEGORIES or r.get("exposure") in (None, "unknown")) and not defer_mandate_exposure:
        missing.extend(["category", "exposure"])
    elif not defer_mandate_exposure:
        missing.extend(_missing_fields(r, ["category", "exposure"], today, 30))
        if r.get("exposure") != _CATEGORIES.get(r.get("category")):
            requires_review = True
            add("R_CATEGORY_EXPOSURE_CONTRADICTION", "La exposición no corresponde a la categoría declarada.")
        for field in ("category", "exposure"):
            if _conflicting_evidence(r, field, today, 30):
                requires_review = True
                add("R_CONTRADICCION", f"Fuentes vigentes discrepan sobre {field}.")
    if context.get("objective") not in ("Preservacion", "Crecimiento", "Renta"):
        missing.append("context.objective")
    profile = context.get("profile")
    if profile not in ("CONSERVADOR", "MODERADO", "AGRESIVO"):
        missing.append("context.profile")
    tolerance = context.get("tolerance")
    if not _finite(tolerance) or not 0 <= tolerance <= 100:
        missing.append("context.tolerance")
    horizon = context.get("horizon_months")
    if not _finite(horizon) or horizon <= 0:
        missing.append("context.horizon_months")
    weight = context.get("allocation_weight")
    if not _finite(weight) or not 0 <= weight <= 100:
        missing.append("context.allocation_weight")
    budget = context.get("budget")
    if not _finite(budget) or budget < 0:
        missing.append("context.budget")
    if r.get("underlying_id") and _has(r, "underlying_id", today, 30):
        for previous in context.get("already_selected") or []:
            if (isinstance(previous, dict) and previous.get("underlying_id") == r.get("underlying_id")
                    and _has(previous, "underlying_id", today, 30)):
                excluded = True
                add("R_OVERLAP", "El mismo fondo o subyacente ya está representado en otra categoría.")
                break
    if _finite(horizon) and _finite(r.get("settlement_days")) and r["settlement_days"] > horizon * 30:
        excluded = True
        add("R_PLAZO_LIQUIDACION", "El plazo de liquidación excede el horizonte indicado.")
    derived_exposure = None
    if itype == "FCI":
        required = ["minimum", "settlement_days", "fund_open", "subscription_open", "redemption_open", "qualified_only", "horizon"]
        missing.extend(_missing_fields(r, required, today, 7))
        if r.get("fund_open") is False or r.get("subscription_open") is False or r.get("redemption_open") is False or r.get("qualified_only") is True:
            excluded = True
            add("R_FCI_NO_ABIERTO_MINORISTA", "La clase está cerrada o requiere calificación y no se recomienda.")
        before_horizon_missing = len(missing)
        _fund_horizon(r, context, missing, policy, today)
        incompatible = {"horizon_incompatible", "duration_incompatible"} & set(missing[before_horizon_missing:])
        if incompatible:
            excluded = True
            add("R_HORIZONTE_FCI_INCOMPATIBLE", "El horizonte declarado no cubre el horizonte mínimo o la duración informada del fondo.")
        if category == "Liquidez inmediata":
            if r.get("category") != "Liquidez inmediata" or not _evidence(r, "category", today, max_age=7):
                missing.append("money_market_classification_evidence")
            if r.get("settlement_days") != 0:
                excluded = True
                add("R_LIQUIDEZ_NO_T0", "Liquidez inmediata requiere rescate T+0 informado.")
            if r.get("mm_kind"):
                reasons.append("El tipo de dinero reportado es " + str(r["mm_kind"]) + "; no es un depósito garantizado.")
        elif category in ("Renta fija inflación", "Renta fija cambiaria"):
            derived_exposure, exp_missing = _exposure_share(r, "inflation" if category.endswith("inflación") else "fx", today, policy)
            missing.extend(exp_missing)
            if derived_exposure and derived_exposure["percent"] <= recommendation.get("minimum_specific_exposure_percent", 50):
                excluded = True
                add("R_EXPOSICION_ESPECIFICA_INSUFICIENTE", "La composición publicada no supera estrictamente 50% de exposición identificada.")
            elif derived_exposure:
                derived_key = "inflation" if category == "Renta fija inflación" else "fx"
                r["derived_exposure"] = {derived_key: derived_exposure["percent"]}
                r["derived_selection_category"] = category
                r["derived_exposure_date"] = derived_exposure["date"]
                r["derived_exposure_percent"] = derived_exposure["percent"]
                source_evidence = derived_exposure["source_evidence"]
                r["derived_exposure_trace"] = {
                    "method": derived_exposure["method"],
                    "identified_rows": deepcopy(derived_exposure["trace"]),
                    "observed_holdings_details": deepcopy(r["holdings_details"]),
                    "source_evidence": {key: source_evidence.get(key) for key in
                                        ("source", "url", "observed_at", "data_date", "version")},
                    "total_percent": derived_exposure["total_percent"],
                }
                add("R_EXPOSICION_INFERIDA_COMPOSICION", "La exposición se infiere de renglones explícitos de la composición publicada; no representa tenencias de hoy.")
                if (today - date.fromisoformat(str(derived_exposure["date"])[:10])).days > 7:
                    reasons.append("La composición es la última fecha publicada y tiene más de siete días; no representa la cartera de hoy.")
            if r.get("exposure_basis") == "mandate" and not derived_exposure:
                missing.append("actual_exposure_or_holdings")
        minimum = r.get("minimum")
        if not _finite(minimum) or minimum < 0:
            if "minimum" not in missing:
                missing.append("minimum")
        elif _finite(budget):
            fee_evidence = _raw_fee_evidence(r, today)
            raw_entry = (r.get("raw_fees") or {}).get("ingreso") if fee_evidence else None
            entry = _fee_number(raw_entry)
            if _finite(r.get("entry_fee_pct")) and entry is not None and r["entry_fee_pct"] != entry:
                requires_review = True
                add("R_CONTRADICCION", "La comisión de ingreso normalizada no coincide con el porcentaje publicado.")
            total = minimum * (1 + entry / 100) if _finite(entry) and entry >= 0 else minimum
            if budget < total:
                excluded = True
                add("R_PRESUPUESTO_MINIMO", "El presupuesto es inferior al mínimo de clase más la comisión de ingreso publicada, si existe.")
    elif itype in ("LOCAL_SHARE", "CEDEAR"):
        missing.extend(_missing_fields(r, ["ticker", "instrument_type", "market", "quotation_currency"], today, 30))
        if context.get("category") != "Renta variable":
            excluded = True
            add("R_CATEGORIA_INCOMPATIBLE", "El valor negociado se compara solo en renta variable.")
        if itype == "CEDEAR":
            ordinary = str(r.get("underlying_type_source") or "").casefold().replace("_", " ")
            if ordinary not in {"ordinarias", "ordinarias escritural", "ordinarias escriturales", "acciones ordinarias"}:
                missing.append("ordinary_share_representation")
            elif not _evidence(r, "underlying_type_source", today, scope="product_identity"):
                missing.append("ordinary_share_representation_evidence")
        elif not _evidence(r, "category", today, scope="product_identity") or not _evidence(r, "exposure", today, scope="product_identity"):
            missing.append("local_equity_classification_evidence")
        offer = r.get("reference_offer_price")
        bid = r.get("reference_bid_price")
        offer_qty, bid_qty = r.get("reference_offer_quantity"), r.get("reference_bid_quantity")
        for field in ("reference_offer_price", "reference_offer_quantity", "reference_bid_price", "reference_bid_quantity"):
            if not _evidence(r, field, today, scope="market_snapshot", max_minutes=15):
                missing.append(field + "_fresh_market_snapshot")
        if not all(_finite(x) and x > 0 for x in (offer, bid, offer_qty, bid_qty)):
            missing.append("valid_two_sided_market_snapshot")
        elif bid > offer:
            add("R_SNAPSHOT_SPREAD_INVALIDO", "La oferta observada tiene precios cruzados.")
        elif (offer - bid) / offer * 100 > recommendation.get("maximum_equity_spread_percent", 5):
            excluded = True
            add("R_SPREAD_EXCESIVO", "El spread observado supera el máximo configurado.")
        if offer is not None and _finite(budget):
            rule = r.get("market_unit_rule")
            if (itype == "CEDEAR" and isinstance(rule, dict)
                    and rule.get("rule_id") == "BYMA17710_CEDEAR_VN1" and rule.get("nominal") == 1
                    and rule.get("source") == "https://data-widgets.byma.com.ar/wp-content/uploads/2020/08/BYMA-COM-17710-Modificacion-de-unidad-minima-de-negociacion-CEDEAR.pdf"
                    and rule.get("published_at") == "2020-08-14"):
                r["indicative_minimum"] = offer
                r["indicative_minimum_inference"] = {"method": "precio de oferta referencial × unidad nominal normativa 1", "rule": deepcopy(rule)}
                if budget < offer:
                    excluded = True
                    add("R_PRESUPUESTO_MINIMO_INDICATIVO", "El presupuesto no alcanza la cota indicativa de una unidad, antes de gastos.")
            else:
                missing.append("documented_market_unit_rule")
        if r.get("unit_price") is not None or r.get("quote_data_date") is not None:
            if r.get("unit_price") is not None:
                add("R_PRECIO_NEGOCIO_NO_RESPALDADO", "La observación BYMADATA no informa fecha del último negocio.")
                missing.append("unit_price_must_remain_unknown")
            if r.get("quote_data_date") is not None:
                missing.append("quote_data_date_must_remain_unknown")
    is_equity = itype in ("LOCAL_SHARE", "CEDEAR") or r.get("exposure") == "equity"
    if is_equity:
        if profile == "CONSERVADOR":
            excluded = True; add("R_PERFIL_EQUITY", "La política no admite renta variable para perfil conservador.")
        caps = policy.get("equity_caps", {}).get("horizon_months", {})
        limit = caps.get("under_12", 0) if _finite(horizon) and horizon < 12 else (caps.get("12_to_35", 20) if _finite(horizon) and horizon < 36 else None)
        if limit is not None and _finite(weight) and weight > limit:
            excluded = True; add("R_HORIZONTE_EQUITY", f"La asignación excede el tope de {limit}% para el horizonte indicado.")
        if context.get("objective") == "Preservacion" and _finite(weight):
            limit = policy.get("equity_caps", {}).get("objectives", {}).get("Preservacion", 10)
            if limit is not None and weight > limit:
                excluded = True; add("R_OBJETIVO_PRESERVACION", f"La asignación excede el tope de {limit}% para preservación.")
        if tolerance == 0:
            excluded = True; add("R_TOLERANCIA_EQUITY", "La tolerancia declarada no admite renta variable.")
    concentration_checks = {
        field: _recommendation_concentration(r, context, field, today, 7 if itype == "FCI" else 30)
        for field in ("issuer", "sector", "country", "underlying_id")
    }
    for field, rule, label in (("issuer", "R_CONCENTRACION_EMISOR", "emisor"),
                               ("sector", "R_CONCENTRACION_SECTOR", "sector"),
                               ("country", "R_CONCENTRACION_PAIS", "país")):
        limit = policy.get("concentration_limits_percent", {}).get(field)
        check = concentration_checks[field]
        if limit is not None and check["status"] == "known" and check["total_weight_percent"] > limit:
            excluded = True
            add(rule, f"La concentración conocida por {label} supera el umbral configurado.")
    annual_fee, annual_fee_evidence = _annual_fund_fee(r, today) if itype == "FCI" else (None, None)
    if annual_fee is not None:
        if _reported_fee_mismatch(r, annual_fee):
            requires_review = True
            add("R_CONTRADICCION", "Los gastos anuales normalizados no coinciden con la suma de los componentes publicados en la misma fuente.")
        r["derived_fund_fee_annual_pct"] = annual_fee
        r["fund_fee_inference"] = {
            "method": "Suma de administración gerente, administración depositaria y gasto ordinario de gestión, solo si los tres porcentajes publicados están presentes.",
            "components": {key: r["raw_fees"][key] for key in (
                "administracion_gerente", "administracion_depositaria", "gasto_ordinario_gestion")},
            "source": annual_fee_evidence.get("source"), "url": annual_fee_evidence.get("url"),
            "data_date": annual_fee_evidence.get("data_date"), "kind": "inference",
        }
    elif itype == "FCI":
        reasons.append("Los gastos anuales del fondo no están completos o no tienen evidencia vigente; no se interpretan como cero.")
    factors = {"risk_fit": None,
               "risk_fit_status": "no comparable risk score in the inspected public source fields",
               "risk_classification": r.get("exposure"),
               "settlement_days": r.get("settlement_days") if _finite(r.get("settlement_days")) else None,
               "verified_diversification": None,
               "published_fund_fees": annual_fee,
               "observed_spread": ((r.get("reference_offer_price", 0) - r.get("reference_bid_price", 0)) / r["reference_offer_price"] * 100
                                   if _finite(r.get("reference_offer_price")) and _finite(r.get("reference_bid_price")) and r.get("reference_offer_price", 0) > 0 else None),
               "observed_market_presence": (
                   {"kind": "quote_volume_amount", "value": r.get("quote_volume_amount")}
                   if itype in ("LOCAL_SHARE", "CEDEAR") else
                   {"kind": "fund_aum", "value": r.get("fund_aum")} if itype == "FCI" else None),
               "familiarity": None, "instrument_type": itype,
               "canonical_id": str(r.get("canonical_id") or "")}
    for field in ("minimum", "settlement_days", "entry_fee_pct", "reference_offer_price",
                  "reference_bid_price", "reference_offer_quantity", "reference_bid_quantity",
                  "quote_volume_amount"):
        value = r.get(field)
        if value is not None and (not _finite(value) or value < 0 or
                                  (field in ("reference_offer_price", "reference_bid_price",
                                             "reference_offer_quantity", "reference_bid_quantity") and value == 0)):
            add("R_DATO_NUMERICO_INVALIDO", f"El campo {field} tiene un valor numérico inválido.")
    if "R_SNAPSHOT_SPREAD_INVALIDO" in rules:
        add("R_DATO_NUMERICO_INVALIDO", "El snapshot contiene precios cruzados.")
    invalid_holdings = any(key.endswith("_invalid") or key in ("holdings_total_invalid", "holdings_date_freshness")
                           for key in missing)
    if invalid_holdings:
        add("R_DATO_NUMERICO_INVALIDO", "La composición contiene porcentajes o fechas inválidos.")
    missing = sorted(set(missing))
    review = requires_review or "R_DATO_NUMERICO_INVALIDO" in rules
    if review:
        decision = "REQUIERE_REVISION"
    elif excluded:
        decision = "EXCLUIR"
    elif missing:
        decision = "INFORMACION_INSUFICIENTE"
    else:
        decision = "CONSERVAR_CANDIDATO"
    eligible = decision == "CONSERVAR_CANDIDATO"
    if eligible:
        explanation = _positive_selection_explanation(r, context, annual_fee, today=today)
    else:
        explanation = list(dict.fromkeys(reasons))
        if not explanation and missing:
            explanation = ["Faltan hechos requeridos para evaluar este instrumento: " + ", ".join(missing[:5]) + "."]
    warnings = _selection_warnings(r, annual_fee, today)
    return {"canonical_id": r.get("canonical_id"), "name": r.get("name"), "decision": decision,
            "eligible": eligible, "selection_scope": SELECTION_SCOPE, "selection_explanation": explanation,
            "selection_warnings": warnings,
            "rule_ids": rules, "reasons": reasons, "missing_fields": missing,
            "ranking_factors": factors, "policy_version": policy.get("version", "argentina-4"),
            "expert_review": "pending", "record": r, "concentration_checks": concentration_checks,
            "execution_checks": _execution_checks(r)}


def recommendation_rank(records, context, *, today=None, policy=None):
    evaluated = [evaluate_recommendation(r, context, today=today, policy=policy) for r in records]
    eligible = [r for r in evaluated if r["eligible"]]
    def common_key(item):
        f = item["ranking_factors"]
        days = f.get("settlement_days")
        # Settlement is applicable to every instrument; an unknown value is
        # reported after known values. Risk and diversification remain neutral
        # when the sources do not provide comparable facts.
        return (f.get("risk_fit") if f.get("risk_fit") is not None else 0,
                (0, days) if _finite(days) else (1, 0),
                0 if f.get("verified_diversification") is True else 1)

    def family(item):
        return "fci" if item["record"].get("instrument_type") == "FCI" else "negotiated"

    queues = {"fci": [], "negotiated": []}
    for item in eligible:
        queues[family(item)].append(item)
    for group, items in queues.items():
        def within_group(item):
            f = item["ranking_factors"]
            metric = f.get("published_fund_fees") if group == "fci" else f.get("observed_spread")
            presence = f.get("observed_market_presence")
            presence_value = presence.get("value") if isinstance(presence, dict) else None
            # Missing FCI expenses remain N/A and are never read as zero;
            # if both are FCI, a known published rate can be compared.
            metric_key = (0, metric) if _finite(metric) else (1, 0)
            presence_key = (0, -presence_value) if _finite(presence_value) else (1, 0)
            return common_key(item), metric_key, presence_key, f.get("canonical_id", "")
        items.sort(key=within_group)
    # Stable merge of the already sorted comparable families. Cross-family
    # ties use only shared facts and canonical identity, so no cyclic comparator.
    ordered = []
    while any(queues.values()):
        heads = [items[0] for items in queues.values() if items]
        head = min(heads, key=lambda item: (common_key(item), item["ranking_factors"].get("canonical_id", "")))
        group = family(head)
        queues[group].pop(0)
        ordered.append(head)
    eligible = ordered
    seen, deduped = set(), []
    for item in eligible:
        underlying = item["record"].get("underlying_id") or item.get("canonical_id")
        if underlying in seen:
            item["eligible"] = False; item["decision"] = "EXCLUIR_CANDIDATO"
            item["rule_ids"].append("R_OVERLAP")
            item["reasons"].append("Se descarta una segunda clase del mismo fondo o subyacente.")
        else:
            seen.add(underlying); deduped.append(item)
    return deduped + [r for r in evaluated if not r["eligible"]]


def recommendation_decide_category(records, context, *, original_id=None, today=None, policy=None):
    ranked = recommendation_rank(records, context, today=today, policy=policy)
    eligible = [x for x in ranked if x["eligible"]]
    winner = eligible[0] if eligible else None
    selected = [winner["record"]] if winner else []
    exclusions = []
    for candidate in eligible[1:]:
        if len(selected) >= 2:
            break
        if candidate["record"].get("underlying_id") != winner["record"].get("underlying_id"):
            next_context = dict(context or {})
            next_context["already_selected"] = list(next_context.get("already_selected") or []) + [winner["record"]]
            checked = evaluate_recommendation(candidate["record"], next_context, today=today, policy=policy)
            if checked["eligible"]:
                selected.append(checked["record"])
            else:
                exclusions.append(checked)
    if winner:
        original = next((x for x in ranked if x.get("canonical_id") == original_id), None)
        decision = "CONSERVAR_CANDIDATO"
        if original_id and original_id != winner.get("canonical_id"):
            decision = "PROPONER_ALTERNATIVA_COMPATIBLE"
            if original and not original["eligible"]:
                cause = (original.get("reasons") or [None])[0] or (
                    "faltan " + ", ".join(original.get("missing_fields") or ["hechos requeridos"]))
                reason = "El original no es elegible: " + cause
            elif original:
                old, new = original["ranking_factors"], winner["ranking_factors"]
                difference = None
                if old.get("settlement_days") is not None and new.get("settlement_days") is not None and old["settlement_days"] != new["settlement_days"]:
                    difference = f"menor plazo de liquidación publicado ({new['settlement_days']} vs {old['settlement_days']} días)"
                elif (original["record"].get("instrument_type") == winner["record"].get("instrument_type") == "FCI"
                      and old.get("published_fund_fees") is not None and new.get("published_fund_fees") is not None
                      and old["published_fund_fees"] != new["published_fund_fees"]):
                    difference = f"menor gasto anual de fondo publicado ({new['published_fund_fees']}% vs {old['published_fund_fees']}%)"
                elif (original["record"].get("instrument_type") in ("LOCAL_SHARE", "CEDEAR")
                      and winner["record"].get("instrument_type") in ("LOCAL_SHARE", "CEDEAR")
                      and old.get("observed_spread") is not None and new.get("observed_spread") is not None
                      and old["observed_spread"] != new["observed_spread"]):
                    difference = f"menor spread observado ({new['observed_spread']:.4g}% vs {old['observed_spread']:.4g}%)"
                else:
                    a, b = old.get("observed_market_presence"), new.get("observed_market_presence")
                    if (isinstance(a, dict) and isinstance(b, dict) and a.get("kind") == b.get("kind")
                            and _finite(a.get("value")) and _finite(b.get("value")) and a["value"] != b["value"]):
                        difference = f"mayor presencia observada en {b['kind']} ({b['value']} vs {a['value']})"
                if difference:
                    reason = f"Se propone la alternativa elegible por {difference}."
                else:
                    reason = "Ambos candidatos son elegibles; los datos no comparables no prueban una mejora de costos y el desempate estable fue la identidad canónica."
            else:
                reason = "El original no está en la cola investigada; se propone la alternativa elegible mejor posicionada y el original queda para auditoría."
        else:
            reason = "Se conserva el instrumento elegible de mejor posición según hechos y factores publicados."
    elif any(x["decision"] == "REQUIERE_REVISION" for x in ranked):
        decision, reason = "REQUIERE_REVISION", "Hay datos contradictorios o inválidos que requieren revisión."
    else:
        decision, reason = "INFORMACION_INSUFICIENTE", "No hay candidato que cumpla todas las comprobaciones de selección con evidencia vigente."
    original = next((x for x in ranked if x.get("canonical_id") == original_id), None)
    return {"category": (context or {}).get("category"), "decision": decision,
            "original_id": original_id, "selected_id": winner.get("canonical_id") if winner else None,
            "selected": selected, "evaluated": ranked,
            "comparison": {"original": original, "alternative": winner, "reason": reason},
            "selection_exclusions": exclusions, "rule_ids": [], "reasons": [reason],
            "policy_version": (policy or {}).get("version", "argentina-4"),
            "expert_review": "pending", "selection_scope": SELECTION_SCOPE}
