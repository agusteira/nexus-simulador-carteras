"""Deterministic, educational screening rules for instrument candidates.

These rules check evidence and operational compatibility; they do not establish
financial suitability or certify an instrument.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlparse

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "instrument_policy.json"
POLICY_VERSION = "educational-2"
_REQUIRED = ("canonical_id", "instrument_type", "market", "category", "exposure",
             "quotation_currency", "subscription_currency", "economic_currency",
             "minimum", "costs", "settlement_days", "liquidity", "access")
_TRADED = {"LOCAL_SHARE", "FOREIGN_SHARE", "ADR", "CEDEAR", "ETF", "CRYPTO", "CRYPTO_FUND"}
_TYPES = {"FCI", "LOCAL_SHARE", "FOREIGN_SHARE", "ADR", "CEDEAR", "ETF", "CRYPTO", "CRYPTO_FUND"}
_CATEGORY_EXPOSURE = {"Renta variable": "equity", "Renta fija inflación": "inflation",
                      "Renta fija cambiaria": "fx", "Liquidez inmediata": "money_market"}
_IDENTITY_FIELDS = {"canonical_id", "instrument_type", "market", "ticker", "stable_id", "underlying_id", "name", "description", "category", "exposure", "educational_role"}


def load_policy():
    return deepcopy(json.loads(POLICY_PATH.read_text(encoding="utf-8")))


def _finite_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _evidence(record, field, today, max_age_days=30):
    """Return fresh observed evidence entries backing this exact field."""
    matches = []
    for ev in record.get("evidence") or []:
        if not isinstance(ev, dict) or ev.get("kind") != "observed":
            continue
        fields = ev.get("fields")
        if not isinstance(fields, dict) or field not in fields or fields[field] != record.get(field):
            continue
        try:
            observed = datetime.fromisoformat(ev.get("observed_at", "").replace("Z", "+00:00"))
            if observed.tzinfo is None or observed.date() > today:
                continue
            expiry_dt = datetime.fromisoformat(ev.get("expires_at", "").replace("Z", "+00:00"))
            if expiry_dt.tzinfo is None or expiry_dt < observed: continue
            expiry = expiry_dt.date()
            data_date = ev.get("data_date")
            if data_date is None:
                if field not in _IDENTITY_FIELDS or (today - observed.date()).days > max_age_days: continue
            else:
                if not isinstance(data_date, str): continue
                data_date = date.fromisoformat(data_date[:10])
                if data_date > today or (today - data_date).days > max_age_days: continue
            parsed_url = urlparse(ev.get("url", ""))
            if expiry < today or not ev.get("source") or parsed_url.scheme != "https" or not parsed_url.netloc:
                continue
            matches.append(ev)
        except (ValueError, TypeError, AttributeError):
            continue
    return matches


def _has_conflicting_evidence(record, field, today, max_age_days):
    for ev in record.get("evidence") or []:
        fields = ev.get("fields") if isinstance(ev, dict) else None
        if not isinstance(fields, dict) or field not in fields or fields[field] == record.get(field):
            continue
        probe = deepcopy(record)
        probe[field] = fields[field]
        if _evidence({**probe, "evidence": [ev]}, field, today, max_age_days):
            return True
    return False


def _provenance(record, field, today, max_age_days):
    return [{"source": ev.get("source"), "url": ev.get("url"), "observed_at": ev.get("observed_at"),
             "data_date": ev.get("data_date"), "version": ev.get("version")}
            for ev in _evidence(record, field, today, max_age_days)]


def _concentration(record, context, field, today, max_age_days):
    value = record.get(field)
    role = record.get("issuer_role")
    if field == "issuer" and record.get("instrument_type") == "FCI" and role not in ("economic_issuer", "issuer"):
        value = None
    if field == "country" and record.get("country_role") != "economic_exposure":
        value = None
    own_evidence = _provenance(record, field, today, max_age_days) if value not in (None, "", "unknown") else []
    if field == "issuer" and record.get("instrument_type") == "FCI":
        own_evidence = own_evidence + _provenance(record, "issuer_role", today, max_age_days) if own_evidence else []
        if not _provenance(record, "issuer_role", today, max_age_days): own_evidence = []
    if field == "country":
        own_evidence = own_evidence + _provenance(record, "country_role", today, max_age_days) if own_evidence else []
        if not _provenance(record, "country_role", today, max_age_days): own_evidence = []
    if not own_evidence:
        return {"value": value if value not in ("unknown", "") else None, "total_weight_percent": None,
                "status": "unknown", "provenance": []}
    weight = context.get("allocation_weight")
    if not _finite_num(weight) or weight < 0:
        return {"value": value, "total_weight_percent": None, "status": "unknown",
                "provenance": own_evidence}
    total, provenance = weight, list(own_evidence)
    for selected in context.get("already_selected", []):
        selected_value = selected.get(field)
        if field == "issuer" and selected.get("instrument_type") == "FCI" and selected.get("issuer_role") not in ("economic_issuer", "issuer"):
            selected_value = None
        if field == "country" and selected.get("country_role") != "economic_exposure": selected_value = None
        if selected_value is None or not _finite_num(selected.get("allocation_weight")):
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        selected_prov = _provenance(selected, field, today, max_age_days)
        if not selected_prov:
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        if field == "country" and not _provenance(selected, "country_role", today, max_age_days):
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        if field == "issuer" and selected.get("instrument_type") == "FCI" and not _provenance(selected, "issuer_role", today, max_age_days):
            return {"value": value, "total_weight_percent": None, "status": "unknown", "provenance": provenance}
        if selected_value != value:
            continue
        total += selected["allocation_weight"]
        provenance.extend(selected_prov)
    return {"value": value, "total_weight_percent": total, "status": "known", "provenance": provenance}


def _education_source_quality(record, today):
    """Rank primary mandate evidence above a source's broad class label."""
    evidence = _evidence(record, "category", today, 30)
    exposure_evidence = _evidence(record, "exposure", today, 30)
    primary_urls = []
    for ev in evidence:
        fields = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
        source_type = ev.get("source_type", fields.get("source_type"))
        scope = ev.get("scope", fields.get("scope"))
        shared_source = any(other.get("url") == ev.get("url") and other.get("source") == ev.get("source")
                            for other in exposure_evidence)
        if not shared_source: continue
        if source_type in ("issuer", "depositary", "exchange"):
            label = "issuer_mandate" if source_type == "issuer" and scope == "mandate" else source_type
            primary_urls.append((label, ev))
    if primary_urls:
        return 0, primary_urls[0][0], primary_urls[0][1]
    return 1, "catalog_classification", evidence[0] if evidence else None


def _eval(record, context, today, policy):
    r = deepcopy(record) if isinstance(record, dict) else {}
    reasons, rules, missing = [], [], []
    def add(rule, reason):
        if rule not in rules: rules.append(rule)
        reasons.append(reason)
    contradiction = bool(r.get("contradictions")) or r.get("validation_status") == "review"
    if r.get("contradictions") or r.get("validation_status") == "review":
        add("R_CONTRADICCION", "Hay datos contradictorios que requieren revisión.")
    if r.get("validation_status") == "expired": missing.append("validation_status_freshness")
    itype = r.get("instrument_type")
    if itype not in _TYPES: missing.append("instrument_type")
    max_age = policy.get("evidence_max_age_days", {}).get("fci" if itype == "FCI" else "identity", 7 if itype == "FCI" else 30)
    for field in _REQUIRED:
        field_age = 30 if field in _IDENTITY_FIELDS else max_age
        if r.get(field) is None or r.get(field) == "" or r.get(field) == "unknown": missing.append(field)
        elif not _evidence(r, field, today, field_age): missing.append(field + "_evidence")
        if _has_conflicting_evidence(r, field, today, field_age):
            contradiction = True
            add("R_CONTRADICCION", f"Fuentes observadas discrepan sobre {field}.")
    if itype == "FCI" and r.get("exposure_basis") == "mandate":
        missing.append("actual_exposure_or_holdings")
        add("R_EXPOSICION_SOLO_MANDATO", "La fuente confirma el mandato declarado, pero no la exposición actual de la cartera.")
    if itype in _TRADED:
        for field in ("lot_size", "unit_price"):
            if r.get(field) is None: missing.append(field)
            elif not _evidence(r, field, today, 1): missing.append(field + "_evidence")
            if _has_conflicting_evidence(r, field, today, 1):
                contradiction = True
                add("R_CONTRADICCION", f"Fuentes observadas discrepan sobre {field}.")
    # A market quote needs fresh dated pricing; FCI has no quoted unit price.
    if itype in _TRADED and r.get("unit_price") is not None:
        dated = False
        for ev in _evidence(r, "unit_price", today, 1): dated = True
        if not dated: missing.append("unit_price_freshness")
    # Known bad numeric data is review-worthy, not silently treated as absent.
    for field in ("minimum", "costs", "settlement_days", "lot_size", "unit_price"):
        v = r.get(field)
        if v is not None and (not _finite_num(v) or v < 0 or (field in ("lot_size", "unit_price") and v == 0)):
            add("R_DATO_NUMERICO_INVALIDO", f"El campo {field} tiene un valor inválido.")
    if r.get("exposure") == "bitcoin" or itype in ("CRYPTO", "CRYPTO_FUND"):
        add("R_CRYPTO_POLICY", "La política educativa excluye criptoactivos y vehículos con exposición a Bitcoin.")
    category = context.get("category")
    if category and r.get("category") and category != r.get("category"):
        add("R_CATEGORIA_INCOMPATIBLE", "La categoría del instrumento no coincide con la asignación.")
    if r.get("category") in _CATEGORY_EXPOSURE and r.get("exposure") not in ("unknown", None, _CATEGORY_EXPOSURE[r["category"]]):
        add("R_CATEGORY_EXPOSURE_CONTRADICTION", "La categoría y exposición declaradas no corresponden.")
    currency = context.get("currency")
    if r.get("quotation_currency") and r.get("subscription_currency") and r["quotation_currency"] != r["subscription_currency"]:
        add("R_MONEDA_INCOMPATIBLE", "La moneda de cotización y suscripción no coincide.")
    if currency and currency != "unknown" and r.get("quotation_currency") not in (None, "unknown") and r.get("subscription_currency") not in (None, "unknown") and (r.get("quotation_currency") != currency or r.get("subscription_currency") != currency):
        add("R_MONEDA_INCOMPATIBLE", "La moneda del instrumento no coincide con la moneda solicitada.")
    budget = context.get("budget")
    if _finite_num(budget):
        minimum = r.get("minimum") if _finite_num(r.get("minimum")) else 0
        unit_total = r["lot_size"] * r["unit_price"] if _finite_num(r.get("lot_size")) and _finite_num(r.get("unit_price")) else 0
        if budget < max(minimum, unit_total):
            add("R_PRESUPUESTO_MINIMO", "El presupuesto es inferior al mínimo operativo conocido.")
        elif _finite_num(r.get("costs")) and budget < max(minimum, unit_total) + r["costs"]:
            add("R_PRESUPUESTO_MINIMO", "El presupuesto es inferior al mínimo operativo más costos conocidos.")
    allowed = context.get("allowed_access")
    if r.get("access") in ("local", "international") and isinstance(allowed, list) and r["access"] not in allowed:
        add("R_ACCESO_INCOMPATIBLE", "El acceso requerido no está habilitado para este instrumento.")
    if r.get("access") in (None, "unknown") or not isinstance(allowed, list) or not allowed:
        missing.append("access_authorization")
    profile, horizon, objective = context.get("profile"), context.get("horizon_months"), context.get("objective")
    is_equity = r.get("exposure") == "equity" or r.get("category") == "Renta variable"
    if is_equity and profile == "CONSERVADOR": add("R_PERFIL_EQUITY", "La política no admite renta variable para perfil conservador.")
    allocation_weight = context.get("allocation_weight")
    if is_equity and not _finite_num(allocation_weight): missing.append("context.allocation_weight")
    if is_equity and _finite_num(horizon) and _finite_num(allocation_weight):
        caps = policy.get("equity_caps", {}).get("horizon_months", {})
        limit = caps.get("under_12", 0) if horizon < 12 else (caps.get("12_to_35", 20) if horizon < 36 else None)
        if limit is not None and allocation_weight > limit:
            add("R_HORIZONTE_EQUITY", f"La asignación de renta variable supera el tope educativo de {limit}% para este horizonte.")
    if is_equity and objective == "Preservacion" and _finite_num(allocation_weight):
        limit = policy.get("equity_caps", {}).get("objectives", {}).get("Preservacion", 10)
        if allocation_weight > limit:
            add("R_OBJETIVO_PRESERVACION", f"La asignación de renta variable supera el tope educativo de {limit}% para preservación.")
    if context.get("tolerance") == 0 and is_equity: add("R_TOLERANCIA_EQUITY", "La tolerancia declarada no admite renta variable.")
    cash = r.get("category") == "Liquidez inmediata"
    requires_immediate = cash or (_finite_num(context.get("liquidity_required")) and context["liquidity_required"] >= policy.get("liquidity_required_immediate_at_or_above", 50))
    if requires_immediate:
        if _finite_num(r.get("settlement_days")) and r["settlement_days"] > 0:
            add("R_LIQUIDEZ_INMEDIATA", "La asignación exige liquidación inmediata y el plazo es mayor que cero.")
        elif r.get("settlement_days") is None: missing.append("settlement_days")
        if r.get("liquidity") not in (None, "unknown", "immediate"):
            add("R_LIQUIDEZ_INMEDIATA", "La liquidez declarada no es inmediata.")
        elif r.get("liquidity") != "immediate" or not _evidence(r, "liquidity", today, max_age): missing.append("liquidity_immediate_evidence")
    if _finite_num(horizon) and _finite_num(r.get("settlement_days")) and r["settlement_days"] > horizon * 30:
        add("R_PLAZO_LIQUIDACION", "El plazo de liquidación excede el horizonte indicado.")
    for existing in context.get("already_selected", []):
        current_underlying = r.get("underlying_id")
        existing_underlying = existing.get("underlying_id") or existing.get("canonical_id")
        if current_underlying and existing_underlying == current_underlying and _evidence(r, "underlying_id", today, max_age) and _evidence(existing, "underlying_id", today, max_age):
            add("R_OVERLAP", "El instrumento se solapa con una posición ya seleccionada."); break
        r_holdings = r.get("holdings") or []
        e_holdings = existing.get("holdings") or []
        overlaps = set(r_holdings) & set(e_holdings) if _evidence(r, "holdings", today, max_age) and _evidence(existing, "holdings", today, max_age) else set()
        if overlaps: add("R_OVERLAP", "Las posiciones comparten activos subyacentes identificados."); break
    concentration_checks = {field: _concentration(r, context, field, today, max_age)
                            for field in ("issuer", "sector", "country", "underlying_id")}
    for field, rule, label in (("issuer", "R_CONCENTRACION_EMISOR", "emisor"),
                               ("sector", "R_CONCENTRACION_SECTOR", "sector"),
                               ("country", "R_CONCENTRACION_PAIS", "país")):
        limit = policy.get("concentration_limits_percent", {}).get(field)
        check = concentration_checks[field]
        if limit is not None and check["status"] == "known" and check["total_weight_percent"] > limit:
            add(rule, f"La concentración conocida por {label} supera el umbral educativo.")
    if category not in _CATEGORY_EXPOSURE: missing.append("context.category")
    if profile not in ("CONSERVADOR", "MODERADO", "AGRESIVO"): missing.append("context.profile")
    if not _finite_num(horizon) or horizon <= 0: missing.append("context.horizon_months")
    if objective not in ("Preservacion", "Crecimiento", "Renta"): missing.append("context.objective")
    if not _finite_num(budget) or budget < 0: missing.append("context.budget")
    if is_equity and not _finite_num(allocation_weight): missing.append("context.allocation_weight")
    if not isinstance(currency, str) or not currency or currency == "unknown": missing.append("context.currency")
    if not _finite_num(context.get("tolerance")) or not 0 <= context["tolerance"] <= 100: missing.append("context.tolerance")
    if not _finite_num(context.get("liquidity_required")) or not 0 <= context["liquidity_required"] <= 100: missing.append("context.liquidity_required")
    # Essential facts: category/exposure/currencies/prices must be explicitly evidenced.
    if r.get("category") not in _CATEGORY_EXPOSURE or r.get("exposure") in (None, "unknown"): missing.append("category_or_exposure")
    elif r.get("exposure") != _CATEGORY_EXPOSURE[r["category"]]:
        contradiction = True
        add("R_CATEGORY_EXPOSURE_CONTRADICTION", "La exposición no corresponde a la categoría declarada.")
    if itype in _TYPES and itype != "FCI" and not r.get("ticker"): missing.append("ticker")
    if missing: add("R_EVIDENCIA_INSUFICIENTE", "Faltan datos o evidencia vigente para evaluar compatibilidad.")
    exclude_ids = {"R_CRYPTO_POLICY", "R_CATEGORIA_INCOMPATIBLE", "R_MONEDA_INCOMPATIBLE", "R_PRESUPUESTO_MINIMO", "R_ACCESO_INCOMPATIBLE", "R_PERFIL_EQUITY", "R_HORIZONTE_EQUITY", "R_OBJETIVO_PRESERVACION", "R_TOLERANCIA_EQUITY", "R_LIQUIDEZ_INMEDIATA", "R_PLAZO_LIQUIDACION", "R_OVERLAP", "R_CONCENTRACION_EMISOR", "R_CONCENTRACION_SECTOR", "R_CONCENTRACION_PAIS"}
    if contradiction or "R_DATO_NUMERICO_INVALIDO" in rules: decision = "REQUIERE_REVISION"
    elif any(x in exclude_ids for x in rules): decision = "EXCLUIR_CANDIDATO"
    elif missing: decision = "INFORMACION_INSUFICIENTE"
    else: decision = "CONSERVAR_CANDIDATO"
    eligible = decision == "CONSERVAR_CANDIDATO"
    verified_holdings = _evidence(r, "holdings", today, max_age)
    distinct_holdings = {x for x in (r.get("holdings") or []) if isinstance(x, str) and x}
    diversified = bool(verified_holdings and len(distinct_holdings) >= 2)
    factors = {"riesgo": 0 if not is_equity else 1, "operacion": r.get("settlement_days") if _finite_num(r.get("settlement_days")) else 999999,
               "diversificacion": 0 if diversified else 1, "costos": r.get("costs") if _finite_num(r.get("costs")) else 999999,
               "familiaridad": 0 if r.get("familiar") is True and r.get("familiarity_basis") else 1,
               "diversificacion_conocida": diversified,
               "concentracion_desconocida": any(v["status"] != "known" for v in concentration_checks.values()),
               "sector_conocido": concentration_checks["sector"]["status"] == "known",
               "pais_conocido": concentration_checks["country"]["status"] == "known"}
    return {"canonical_id": r.get("canonical_id"), "name": r.get("name"), "decision": decision, "eligible": eligible,
            "rule_ids": rules, "reasons": reasons, "missing_fields": sorted(set(missing)), "ranking_factors": factors,
            "policy_version": policy.get("version", POLICY_VERSION), "expert_review": "pending", "record": r,
            "concentration_checks": concentration_checks}


def build_educational_selection(records, context, *, today=None, policy=None):
    """Return researched class references, explicitly separate from eligibility.

    Identity and classification must be observed. Unknown operational facts may
    be disclosed on an educational card but can never establish financial fit.
    """
    policy = policy or load_policy()
    today = today or datetime.now(timezone.utc).date()
    context = context or {}
    cards, excluded = [], []
    currency = context.get("currency")
    broad_underlyings = {r.get("underlying_id") for r in records if isinstance(r, dict)
                         and r.get("educational_role") == "index_basket" and r.get("underlying_id")
                         and _evidence(r, "educational_role", today, 30) and _evidence(r, "underlying_id", today, 30)}
    for raw in records:
        record = deepcopy(raw) if isinstance(raw, dict) else {}
        strict = _eval(record, context, today, policy)
        cid = record.get("canonical_id")
        def reject(rule, reason):
            excluded.append({"canonical_id": cid, "name": record.get("name"), "decision": strict["decision"],
                             "education_id": record.get("education_id"), "familiar": record.get("familiar"),
                             "familiarity_basis": record.get("familiarity_basis"),
                             "educational_description": record.get("educational_description"),
                             "rule_ids": list(dict.fromkeys(strict["rule_ids"] + [rule])), "reasons": strict["reasons"] + [reason]})
        if record.get("validation_status") in ("review", "expired") or record.get("contradictions"):
            reject("R_REFERENCIA_REVISION", "La referencia está vencida o requiere revisión; no se muestra como referencia verificada.")
            continue
        if record.get("instrument_type") in ("CRYPTO", "CRYPTO_FUND") or record.get("exposure") == "bitcoin":
            reject("R_CRYPTO_POLICY", "La política educativa no asigna referencias con exposición cripto o Bitcoin.")
            continue
        if record.get("category") != context.get("category") and record.get("category") in _CATEGORY_EXPOSURE and _evidence(record, "category", today, 30):
            reject("R_CATEGORIA_INCOMPATIBLE", "La clasificación observada corresponde a otra categoría de la cartera.")
            continue
        classification_ok = (record.get("category") == context.get("category")
                             and record.get("exposure") == _CATEGORY_EXPOSURE.get(context.get("category"))
                             and bool(_evidence(record, "category", today, 30))
                             and bool(_evidence(record, "exposure", today, 30)))
        # A display name may be a curated label; stable identity is established
        # by observed canonical ID, type and market, not the presentation text.
        identity_fields = ("canonical_id", "instrument_type", "market")
        identity_ok = all(record.get(field) not in (None, "") and _evidence(record, field, today, 30) for field in identity_fields)
        if not identity_ok or not classification_ok:
            if record.get("reference_status") == "source_unavailable":
                detail = "La fuente educativa no respondió; la categoría o exposición observada no pudo confirmarse."
            elif record.get("reference_status") == "unsupported":
                detail = "No hay una fuente educativa aprobada para confirmar esta categoría o exposición."
            else:
                detail = record.get("category_hint") or record.get("exposure_hint") or "La fuente no confirmó identidad y categoría/exposición del instrumento."
            reject("R_REFERENCIA_CLASE_NO_VERIFICADA", f"No se muestra como referencia verificada: {detail} Una etiqueta curada por sí sola no verifica la clase.")
            continue
        # Currency exclusions only use values backed by current observed facts.
        quote_known = bool(record.get("quotation_currency") and record.get("quotation_currency") != "unknown"
                           and _evidence(record, "quotation_currency", today, 30))
        sub_known = bool(record.get("subscription_currency") and record.get("subscription_currency") != "unknown"
                         and _evidence(record, "subscription_currency", today, 30))
        known_currency = quote_known and sub_known
        if quote_known and sub_known and record["quotation_currency"] != record["subscription_currency"]:
            reject("R_MONEDA_INCOMPATIBLE", "La fuente observó monedas de cotización y suscripción distintas.")
            continue
        if currency not in (None, "", "unknown") and ((quote_known and record["quotation_currency"] != currency)
                                                        or (sub_known and record["subscription_currency"] != currency)):
            reject("R_MONEDA_INCOMPATIBLE", "La moneda observada no coincide con la moneda solicitada.")
            continue
        # Exclude a hard budget contradiction only when the lower bound is evidenced.
        budget, minimum = context.get("budget"), record.get("minimum")
        known_minimum = _finite_num(minimum) and bool(_evidence(record, "minimum", today, 7 if record.get("instrument_type") == "FCI" else 30))
        known_lot = (_finite_num(record.get("lot_size")) and _finite_num(record.get("unit_price"))
                     and bool(_evidence(record, "lot_size", today, 1)) and bool(_evidence(record, "unit_price", today, 1)))
        lower_bound = minimum if known_minimum else 0
        if known_lot: lower_bound = max(lower_bound, record["lot_size"] * record["unit_price"])
        known_costs = (_finite_num(record.get("costs")) and bool(_evidence(record, "costs", today, 30)))
        if known_costs and lower_bound > 0: lower_bound += record["costs"]
        if _finite_num(budget) and lower_bound > 0 and budget < lower_bound:
            reject("R_PRESUPUESTO_MINIMO", "El presupuesto conocido no alcanza el mínimo operativo publicado.")
            continue
        allowed = context.get("allowed_access")
        if (record.get("access") in ("local", "international") and isinstance(allowed, list)
                and record["access"] not in allowed and _evidence(record, "access", today, 30)):
            reject("R_ACCESO_INCOMPATIBLE", "El acceso observado no está habilitado para esta búsqueda.")
            continue
        immediate_required = (context.get("category") == "Liquidez inmediata"
                              or (_finite_num(context.get("liquidity_required")) and context["liquidity_required"] >= policy.get("liquidity_required_immediate_at_or_above", 50)))
        if immediate_required:
            settlement_known = _finite_num(record.get("settlement_days")) and bool(_evidence(record, "settlement_days", today, 30))
            liquidity_known = bool(record.get("liquidity") and _evidence(record, "liquidity", today, 30))
            if settlement_known and record["settlement_days"] > 0:
                reject("R_LIQUIDEZ_INMEDIATA", "La fuente observó un plazo mayor que cero días.")
                continue
            if liquidity_known and record["liquidity"] not in ("immediate", "unknown"):
                reject("R_LIQUIDEZ_INMEDIATA", "La fuente observó liquidez que no es inmediata.")
                continue
        if any(rule in strict["rule_ids"] for rule in ("R_PERFIL_EQUITY", "R_HORIZONTE_EQUITY", "R_OBJETIVO_PRESERVACION", "R_TOLERANCIA_EQUITY")):
            reject(next(rule for rule in strict["rule_ids"] if rule.startswith(("R_PERFIL_EQUITY", "R_HORIZONTE_EQUITY", "R_OBJETIVO_PRESERVACION", "R_TOLERANCIA_EQUITY"))),
                   "La exposición no cabe en el límite educativo de esta cartera.")
            continue
        missing = sorted(set(strict["missing_fields"]) - {x for x in strict["missing_fields"] if x.startswith("context.") or x in ("category_evidence", "exposure_evidence", "category_or_exposure")})
        if not known_currency: missing = sorted(set(missing + ["quotation_currency", "subscription_currency", "economic_currency"]))
        if currency in (None, "", "unknown"): missing = sorted(set(missing + ["context.currency"]))
        operation_fields = {"minimum", "costs", "lot_size", "unit_price", "settlement_days", "liquidity", "access", "economic_currency", "actual_exposure_or_holdings"}
        pending = any(field in missing or any(field + "_" in x for x in missing) for field in operation_fields)
        currency_status = "match" if known_currency and currency == record.get("quotation_currency") else ("unknown" if not known_currency or currency in (None, "", "unknown") else "not_applicable")
        source_quality, source_type, mandate_evidence = _education_source_quality(record, today)
        if not strict["eligible"] and source_quality != 0:
            if record.get("reference_status") == "source_unavailable":
                reason = "La fuente primaria no respondió. El catálogo aporta una clase amplia, pero no una explicación o composición contrastada."
            else:
                reason = "El catálogo aporta clase y moneda, pero no una explicación o composición contrastada."
            reject("R_REFERENCIA_EXPEDIENTE_BASICO", reason)
            continue
        mandate_only = record.get("instrument_type") == "FCI" and record.get("exposure_basis") == "mandate"
        if mandate_only:
            reason = (f"Referencia educativa de {record.get('category')}: el emisor describe el mandato, pero la exposición actual de la cartera no está verificada. "
                      "No es una selección financiera.")
        elif source_quality == 0:
            reason = (f"Referencia educativa de {record.get('category')}: una fuente primaria ({source_type}) verificó identidad y clasificación. "
                      "No es una selección financiera; los datos operativos pendientes deben verificarse.")
        else:
            reason = (f"Referencia educativa de {record.get('category')}: el catálogo verificó una clasificación amplia. "
                      "No es una selección financiera; los datos operativos pendientes deben verificarse.")
        card = deepcopy(record)
        card.update({"reason": reason, "missing_fields": missing,
                     "operational_status": "operación pendiente" if pending else "datos operativos observados; elegibilidad no validada",
                     "currency_status": currency_status,
                     "reference_source_type": source_type,
                     "reference_source_quality": source_type if source_quality == 0 else "catalog_classification",
                     "exposure_status": "mandate_only" if mandate_only else "classification_observed",
                     "evidence": [ev for ev in record.get("evidence", []) if ev.get("kind") == "observed"]})
        # Currency certainty and observed operational coverage precede familiarity.
        verified_operational = sum(bool(_evidence(record, field, today, 30)) for field in
                                   ("minimum", "costs", "settlement_days", "liquidity", "access", "economic_currency"))
        normalized_name = (record.get("name") or "").casefold().strip()
        class_a = 0 if normalized_name.endswith(("clase a", "-a", " a")) else 1
        familiarity = 0 if record.get("familiar") is True and record.get("familiarity_basis") else 1
        route_priority = 9
        kind, ticker = record.get("instrument_type"), (record.get("ticker") or "").upper()
        if currency == "ARS":
            route_priority = {("CEDEAR", "SPY"): 0, ("CEDEAR", "MELI"): 1, ("LOCAL_SHARE", "YPFD"): 2,
                              ("ADR", "YPF"): 4, ("FOREIGN_SHARE", "MELI"): 5}.get((kind, ticker), 3 if kind == "CEDEAR" else 9)
        elif currency == "USD":
            route_priority = {("ETF", "SPY"): 0, ("FOREIGN_SHARE", "MELI"): 1, ("ADR", "YPF"): 2}.get((kind, ticker), 5)
        else:
            route_priority = {("ETF", "SPY"): 0, ("CEDEAR", "SPY"): 1, ("FOREIGN_SHARE", "MELI"): 2,
                              ("CEDEAR", "MELI"): 3, ("LOCAL_SHARE", "YPFD"): 4, ("ADR", "YPF"): 5}.get((kind, ticker), 9)
        broad_index = (0 if record.get("educational_role") == "index_basket" and _evidence(record, "educational_role", today, 30)
                       else (0 if record.get("underlying_id") in broad_underlyings and _evidence(record, "underlying_id", today, 30) else 1))
        cards.append((0 if strict["eligible"] else 1, source_quality, route_priority, broad_index,
                      0 if currency_status == "match" else 1, -verified_operational, class_a, familiarity, str(cid or ""), card))
    cards.sort(key=lambda item: item[:-1])
    selected_cards, seen_classes = [], set()
    for item in cards:
        card = item[9]
        class_key = card.get("education_id") or card.get("underlying_id") or card.get("canonical_id")
        if class_key in seen_classes: continue
        seen_classes.add(class_key)
        card["description"] = card.get("description") or card.get("educational_description") or (card.get("explanation") or {}).get("text")
        selected_cards.append(card)
        if len(selected_cards) == 2: break
    reasons = (["Se muestran referencias educativas verificadas por identidad y clasificación; no equivalen a una recomendación financiera."]
               if selected_cards else ["No hay una referencia con identidad y categoría/exposición observadas suficientes."])
    return {"status": "REFERENCIA_EDUCATIVA" if selected_cards else "SIN_REFERENCIA_VERIFICADA",
            "cards": selected_cards, "excluded": excluded, "rule_ids": [], "reasons": reasons,
            "policy_version": policy.get("version", POLICY_VERSION), "expert_review": "pending"}


def evaluate_candidate(record, context, *, today=None, policy=None):
    return _eval(record, context or {}, today or datetime.now(timezone.utc).date(), policy or load_policy())


def rank_candidates(records, context, *, today=None, policy=None):
    policy = policy or load_policy()
    decisions = [_eval(x, context or {}, today or datetime.now(timezone.utc).date(), policy) for x in records]
    eligible = [x for x in decisions if x["eligible"]]
    eligible.sort(key=lambda x: (x["ranking_factors"]["riesgo"], x["ranking_factors"]["operacion"], x["ranking_factors"]["diversificacion"], x["ranking_factors"]["costos"], x["ranking_factors"]["familiaridad"], str(x.get("canonical_id") or "")))
    deduplicated, seen = [], set()
    for item in eligible:
        key = item["record"].get("underlying_id") or item.get("canonical_id")
        if key not in seen:
            deduplicated.append(item); seen.add(key)
        else:
            item["eligible"] = False
            item["decision"] = "EXCLUIR_CANDIDATO"
            if "R_OVERLAP" not in item["rule_ids"]: item["rule_ids"].append("R_OVERLAP")
            item["reasons"].append("Se descarta por duplicar un subyacente ya representado en el orden elegible.")
    return deduplicated + [x for x in decisions if not x["eligible"]]


def decide_category(records, context, *, original_id=None, can_expand=False, today=None, policy=None):
    policy = policy or load_policy()
    ranked = rank_candidates(records, context, today=today, policy=policy)
    eligible = [x for x in ranked if x["eligible"]]
    original = next((x for x in ranked if x.get("canonical_id") == original_id), None)
    winner = eligible[0] if eligible else None
    if winner and original_id and winner["canonical_id"] != original_id:
        old_factors = original.get("ranking_factors", {}) if original else {}
        new_factors = winner["ranking_factors"]
        changed = [k for k in ("riesgo", "operacion", "diversificacion", "costos", "familiaridad") if new_factors.get(k) != old_factors.get(k)]
        detail = f"Mejora {changed[0]} ({old_factors.get(changed[0])} → {new_factors.get(changed[0])})." if changed else "El candidato original no es elegible."
        decision, ids, reason = "PROPONER_ALTERNATIVA_COMPATIBLE", ["R_ALTERNATIVA_COMPATIBLE"], f"Se propone {winner.get('name') or winner.get('canonical_id')}: {detail}"
    elif winner: decision, ids, reason = "CONSERVAR_CANDIDATO", ["R_ELEGIBLE_EDUCATIVO"], "Candidato elegible bajo reglas educativas; no constituye validación financiera."
    elif can_expand: decision, ids, reason = "AMPLIAR_BUSQUEDA", ["R_SIN_CANDIDATO_AMPLIAR"], "No hay candidatos elegibles; ampliar la búsqueda y aportar evidencia."
    elif any(x["decision"] == "REQUIERE_REVISION" for x in ranked): decision, ids, reason = "REQUIERE_REVISION", [], "Los candidatos presentan contradicciones o valores inválidos."
    else: decision, ids, reason = "INFORMACION_INSUFICIENTE", [], "No hay información suficiente para seleccionar un candidato."
    selected = [winner["record"]] if winner else []
    selection_exclusions = []
    if winner:
        for next_item in eligible[1:]:
            next_context = dict(context or {})
            next_context["already_selected"] = list(next_context.get("already_selected", [])) + [winner["record"]]
            checked = _eval(next_item["record"], next_context, today or datetime.now(timezone.utc).date(), policy)
            if checked["eligible"]:
                selected.append(checked["record"])
                break
            selection_exclusions.append(checked)
    return {"category": (context or {}).get("category"), "decision": decision, "original_id": original_id,
            "selected_id": winner.get("canonical_id") if winner else None, "selected": selected, "evaluated": ranked,
            "comparison": {"original": original, "alternative": winner, "reason": reason}, "selection_exclusions": selection_exclusions, "rule_ids": ids,
            "reasons": [reason], "policy_version": policy.get("version", POLICY_VERSION), "expert_review": "pending"}
