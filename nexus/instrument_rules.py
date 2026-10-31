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
POLICY_VERSION = "argentina-4"
STRICT_EXECUTION_SCOPE = "STRICT_EXECUTION"
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


def _eval(record, context, today, policy):
    r = deepcopy(record) if isinstance(record, dict) else {}
    reasons, rules, missing = [], [], []
    def add(rule, reason):
        if rule not in rules: rules.append(rule)
        reasons.append(reason)
    contradiction = bool(r.get("contradictions")) or r.get("validation_status") == "review"
    if r.get("contradictions") or r.get("validation_status") == "review":
        add("R_CONTRADICCION", "Las fuentes muestran datos distintos para este instrumento; hay que revisar cuál es correcto.")
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
            add("R_CONTRADICCION", "Las fuentes actuales no coinciden en un dato de la ficha; hay que revisarlo.")
    if itype == "FCI" and r.get("exposure_basis") == "mandate":
        missing.append("actual_exposure_or_holdings")
        add("R_EXPOSICION_SOLO_MANDATO", "La fuente informa el objetivo del fondo, pero no qué activos tiene actualmente.")
    if itype in _TRADED:
        for field in ("lot_size", "unit_price"):
            if r.get(field) is None: missing.append(field)
            elif not _evidence(r, field, today, 1): missing.append(field + "_evidence")
            if _has_conflicting_evidence(r, field, today, 1):
                contradiction = True
                add("R_CONTRADICCION", "Las fuentes actuales no coinciden en un dato de la ficha; hay que revisarlo.")
    # A market quote needs fresh dated pricing; FCI has no quoted unit price.
    if itype in _TRADED and r.get("unit_price") is not None:
        dated = False
        for ev in _evidence(r, "unit_price", today, 1): dated = True
        if not dated: missing.append("unit_price_freshness")
    # Known bad numeric data is review-worthy, not silently treated as absent.
    for field in ("minimum", "costs", "settlement_days", "lot_size", "unit_price"):
        v = r.get(field)
        if v is not None and (not _finite_num(v) or v < 0 or (field in ("lot_size", "unit_price") and v == 0)):
            add("R_DATO_NUMERICO_INVALIDO", "La fuente contiene un valor numérico inválido; hace falta revisarlo.")
    if r.get("exposure") == "bitcoin" or itype in ("CRYPTO", "CRYPTO_FUND"):
        add("R_CRYPTO_POLICY", "Este instrumento tiene exposición a criptoactivos, que el simulador no evalúa.")
    category = context.get("category")
    if category and r.get("category") and category != r.get("category"):
        add("R_CATEGORIA_INCOMPATIBLE", "La categoría informada no coincide con la asignación elegida.")
    if r.get("category") in _CATEGORY_EXPOSURE and r.get("exposure") not in ("unknown", None, _CATEGORY_EXPOSURE[r["category"]]):
        add("R_CATEGORY_EXPOSURE_CONTRADICTION", "La categoría y la exposición informadas no coinciden; hace falta revisar la ficha.")
    currency = context.get("currency")
    if r.get("quotation_currency") and r.get("subscription_currency") and r["quotation_currency"] != r["subscription_currency"]:
        add("R_MONEDA_INCOMPATIBLE", "La moneda de cotización y la de suscripción son distintas.")
    if currency and currency != "unknown" and r.get("quotation_currency") not in (None, "unknown") and r.get("subscription_currency") not in (None, "unknown") and (r.get("quotation_currency") != currency or r.get("subscription_currency") != currency):
        add("R_MONEDA_INCOMPATIBLE", "La moneda del instrumento no coincide con la moneda del escenario.")
    budget = context.get("budget")
    if _finite_num(budget):
        minimum = r.get("minimum") if _finite_num(r.get("minimum")) else 0
        unit_total = r["lot_size"] * r["unit_price"] if _finite_num(r.get("lot_size")) and _finite_num(r.get("unit_price")) else 0
        if budget < max(minimum, unit_total):
            add("R_PRESUPUESTO_MINIMO", "El presupuesto no alcanza el mínimo o el monto necesario para una unidad, según los datos disponibles.")
        elif _finite_num(r.get("costs")) and budget < max(minimum, unit_total) + r["costs"]:
            add("R_PRESUPUESTO_MINIMO", "El presupuesto no alcanza el mínimo más los costos informados.")
    allowed = context.get("allowed_access")
    if r.get("access") in ("local", "international") and isinstance(allowed, list) and r["access"] not in allowed:
        add("R_ACCESO_INCOMPATIBLE", "El acceso elegido no permite operar este instrumento.")
    if r.get("access") in (None, "unknown") or not isinstance(allowed, list) or not allowed:
        missing.append("access_authorization")
    profile, horizon, objective = context.get("profile"), context.get("horizon_months"), context.get("objective")
    is_equity = r.get("exposure") == "equity" or r.get("category") == "Renta variable"
    if is_equity and profile == "CONSERVADOR": add("R_PERFIL_EQUITY", "El simulador no incluye acciones para el perfil conservador.")
    allocation_weight = context.get("allocation_weight")
    if is_equity and not _finite_num(allocation_weight): missing.append("context.allocation_weight")
    if is_equity and _finite_num(horizon) and _finite_num(allocation_weight):
        caps = policy.get("equity_caps", {}).get("horizon_months", {})
        limit = caps.get("under_12", 0) if horizon < 12 else (caps.get("12_to_35", 20) if horizon < 36 else None)
        if limit is not None and allocation_weight > limit:
            add("R_HORIZONTE_EQUITY", f"La asignación supera el límite de {limit}% en acciones para este plazo.")
    if is_equity and objective == "Preservacion" and _finite_num(allocation_weight):
        limit = policy.get("equity_caps", {}).get("objectives", {}).get("Preservacion", 10)
        if allocation_weight > limit:
            add("R_OBJETIVO_PRESERVACION", f"La asignación supera el límite de {limit}% en acciones para el objetivo de preservación.")
    if context.get("tolerance") == 0 and is_equity: add("R_TOLERANCIA_EQUITY", "La tolerancia declarada no permite incluir acciones en esta asignación.")
    cash = r.get("category") == "Liquidez inmediata"
    requires_immediate = cash or (_finite_num(context.get("liquidity_required")) and context["liquidity_required"] >= policy.get("liquidity_required_immediate_at_or_above", 50))
    if requires_immediate:
        if _finite_num(r.get("settlement_days")) and r["settlement_days"] > 0:
            add("R_LIQUIDEZ_INMEDIATA", "Esta asignación requiere rescatar el dinero el mismo día, pero la fuente informa otro plazo.")
        elif r.get("settlement_days") is None: missing.append("settlement_days")
        if r.get("liquidity") not in (None, "unknown", "immediate"):
            add("R_LIQUIDEZ_INMEDIATA", "La liquidez informada no permite retirar el dinero de inmediato.")
        elif r.get("liquidity") != "immediate" or not _evidence(r, "liquidity", today, max_age): missing.append("liquidity_immediate_evidence")
    if _finite_num(horizon) and _finite_num(r.get("settlement_days")) and r["settlement_days"] > horizon * 30:
        add("R_PLAZO_LIQUIDACION", "El plazo informado para retirar el dinero supera el horizonte de la simulación.")
    for existing in context.get("already_selected", []):
        current_underlying = r.get("underlying_id")
        existing_underlying = existing.get("underlying_id") or existing.get("canonical_id")
        if current_underlying and existing_underlying == current_underlying and _evidence(r, "underlying_id", today, max_age) and _evidence(existing, "underlying_id", today, max_age):
            add("R_OVERLAP", "Este instrumento comparte un activo subyacente identificado con otra posición."); break
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
            add(rule, f"La concentración conocida por {label} supera el límite del simulador.")
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
        add("R_CATEGORY_EXPOSURE_CONTRADICTION", "La categoría y la exposición informadas no coinciden; hace falta revisar la ficha.")
    if itype in _TYPES and itype != "FCI" and not r.get("ticker"): missing.append("ticker")
    if missing: add("R_EVIDENCIA_INSUFICIENTE", "Faltan datos publicados y vigentes para comprobar si este instrumento encaja con el escenario.")
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
    """Compatibility projection: references are exactly strict rule selections."""
    decision = decide_category(records, context, today=today, policy=policy)
    selected = deepcopy(decision["selected"])
    return {"status": "SELECTED_BY_RULES" if selected else "NO_SELECTION",
            "cards": selected, "policy_version": (policy or load_policy()).get("version", POLICY_VERSION),
            "expert_review": "pending"}


def evaluate_candidate(record, context, *, today=None, policy=None):
    context = context or {}
    if context.get("selection_scope") == "instrument_recommendation":
        from .instrument_recommendations import evaluate_recommendation
        return evaluate_recommendation(record, context, today=today, policy=policy or load_policy())
    return _eval(record, context, today or datetime.now(timezone.utc).date(), policy or load_policy())


def rank_candidates(records, context, *, today=None, policy=None):
    policy = policy or load_policy()
    if (context or {}).get("selection_scope") == "instrument_recommendation":
        from .instrument_recommendations import recommendation_rank
        return recommendation_rank(records, context or {}, today=today, policy=policy)
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
            item["reasons"].append("Se deja fuera porque el mismo activo subyacente ya aparece en una opción anterior.")
    return deduplicated + [x for x in decisions if not x["eligible"]]


def decide_category(records, context, *, original_id=None, can_expand=False, today=None, policy=None):
    policy = policy or load_policy()
    if (context or {}).get("selection_scope") == "instrument_recommendation":
        from .instrument_recommendations import recommendation_decide_category
        return recommendation_decide_category(records, context or {}, original_id=original_id, today=today, policy=policy)
    ranked = rank_candidates(records, context, today=today, policy=policy)
    eligible = [x for x in ranked if x["eligible"]]
    original = next((x for x in ranked if x.get("canonical_id") == original_id), None)
    winner = eligible[0] if eligible else None
    if winner and original_id and winner["canonical_id"] != original_id:
        old_factors = original.get("ranking_factors", {}) if original else {}
        new_factors = winner["ranking_factors"]
        changed = [k for k in ("riesgo", "operacion", "diversificacion", "costos", "familiaridad") if new_factors.get(k) != old_factors.get(k)]
        if changed:
            labels = {"riesgo": "clasificación usada por las reglas", "operacion": "plazo informado",
                      "diversificacion": "composición conocida", "costos": "costos informados",
                      "familiaridad": "reconocimiento registrado"}
            detail = f"El orden prioriza {labels[changed[0]]} ({new_factors.get(changed[0])} frente a {old_factors.get(changed[0])})."
        else:
            detail = "No se observó una diferencia clara en los factores comparados."
        decision, ids, reason = "PROPONER_ALTERNATIVA_COMPATIBLE", ["R_ALTERNATIVA_COMPATIBLE"], f"La opción propuesta pasó los controles de esta evaluación. {detail} El orden no indica mayor rentabilidad."
    elif winner: decision, ids, reason = "CONSERVAR_CANDIDATO", ["R_ELEGIBLE_EDUCATIVO"], "La opción pasó los controles con los datos publicados disponibles."
    elif can_expand: decision, ids, reason = "AMPLIAR_BUSQUEDA", ["R_SIN_CANDIDATO_AMPLIAR"], "Ninguna opción pasó los controles todavía. Ampliá la búsqueda o aportá más datos publicados."
    elif any(x["decision"] == "REQUIERE_REVISION" for x in ranked): decision, ids, reason = "REQUIERE_REVISION", [], "Hay datos de la fuente que no coinciden o son inválidos; hace falta revisarlos."
    else: decision, ids, reason = "INFORMACION_INSUFICIENTE", [], "No hay datos publicados y vigentes suficientes para comprobar los requisitos de las opciones revisadas."
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
