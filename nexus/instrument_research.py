"""Bounded instrument research layered over the legacy FCI examples."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

from .instrument_knowledge import UNIVERSE_VERSION, KnowledgeStore, load_universe, normalize_fund
from .instrument_providers import MarketDataError, ReferenceProvider
from .instrument_rules import POLICY_VERSION, _evidence, _finite_num, decide_category, rank_candidates


@dataclass(frozen=True)
class ResearchLimits:
    max_queries: int = 12
    max_seconds: float = 24
    max_results: int = 12

    def __post_init__(self):
        object.__setattr__(self, "max_queries", max(0, int(self.max_queries)))
        object.__setattr__(self, "max_seconds", max(0, float(self.max_seconds)))
        object.__setattr__(self, "max_results", max(0, int(self.max_results)))


def _profile_context(snapshot, result, category, budget, weight, already_selected,
                    selection_scope="ARGENTINA_SIN_BROKER"):
    profile = snapshot.get("perfil") or {}
    objective = profile.get("objetivo")
    if objective == "Renta periodica":
        objective = "Renta"
    return {"selection_scope": "instrument_recommendation" if selection_scope == "ARGENTINA_SIN_BROKER" else selection_scope,
            "category": category, "profile": result.get("perfil_riesgo"),
            "horizon_months": profile.get("horizonte"), "objective": objective,
            "budget": budget, "allocation_weight": weight, "tolerance": profile.get("tolerancia"),
            "currency": result.get("moneda", profile.get("moneda")),
            "liquidity_required": profile.get("liquidez"), "allowed_access": profile.get("acceso"),
            "already_selected": list(already_selected)}


def _source_records(catalogs, today, max_results):
    pools, omitted, originals = {}, {}, {}
    for source in catalogs:
        candidates = []
        for record in source.get("normalized_records", []) if isinstance(source, dict) else []:
            canonical_id = record.get("canonical_id") if isinstance(record, dict) else None
            if isinstance(canonical_id, str) and canonical_id.strip() == canonical_id and ":" in canonical_id:
                candidates.append((deepcopy(record), None))
        for fund in source.get("fondos", []) if isinstance(source, dict) else []:
            try:
                record = normalize_fund(fund, source, today=today)
            except (TypeError, ValueError):
                continue
            candidates.append((record, fund.get("tipoRenta")))
        for record, legacy_type in candidates:
            category = record.get("category")
            hint = record.get("category_hint")
            hints = record.get("category_hints") if isinstance(record.get("category_hints"), list) else []
            mandate_fixed_hints = [x for x in hints if x in ("Renta fija inflación", "Renta fija cambiaria")]
            if (category in ("Renta fija inflación", "Renta fija cambiaria")
                    and record.get("instrument_type") == "FCI"
                    and record.get("exposure_basis") == "mandate"
                    and len(set(mandate_fixed_hints)) > 1):
                applicable = list(dict.fromkeys([category] + mandate_fixed_hints))
            elif category:
                applicable = [category]
            elif hint in ("Renta fija inflación", "Renta fija cambiaria", "Renta variable", "Liquidez inmediata"):
                applicable = [hint]
            elif hints:
                applicable = [x for x in hints if x in ("Renta fija inflación", "Renta fija cambiaria", "Renta variable", "Liquidez inmediata")]
            elif record.get("instrument_type") == "FCI" and str(legacy_type or "").casefold() in ("renta fija", "fija"):
                # The legacy catalog's broad fixed-income class can enter either
                # fixed-income comparison; this is a source hint, not evidence.
                applicable = ["Renta fija inflación", "Renta fija cambiaria"]
            else:
                applicable = []
            for target in applicable:
                pools.setdefault(target, []).append(record)
                originals.setdefault(target, deepcopy(record))
    for target, pool in pools.items():
        omitted[target] = max(0, len(pool) - max_results)
    return pools, omitted, originals


def _fresh_cached(record, today=None):
    if record.get("validation_status") == "review":
        return True
    reference_day = today or datetime.now(timezone.utc).date()
    now = datetime.combine(reference_day, datetime.max.time(), timezone.utc)
    has_observed = False
    for evidence in record.get("evidence", []):
        if evidence.get("kind") == "observed": has_observed = True
        expiry = evidence.get("expires_at")
        if not expiry:
            continue
        try:
            if datetime.fromisoformat(expiry.replace("Z", "+00:00")) >= datetime.combine(reference_day, datetime.min.time(), timezone.utc):
                if has_observed: return True
        except (ValueError, TypeError):
            continue
    return False


def _merge_fresh_record(fresh, cached, *, preserve_review=False):
    """Prefer refreshed facts from their source, retain complementary facts."""
    merged = deepcopy(fresh)
    new_evidence = list(fresh.get("evidence") or [])
    fresh_sources = {e.get("source") for e in new_evidence}
    old_evidence = [e for e in cached.get("evidence", []) if e.get("source") not in fresh_sources]
    merged["evidence"] = old_evidence + new_evidence
    contradictions = list(cached.get("contradictions") or []) + list(fresh.get("contradictions") or [])
    for key, old_value in cached.items():
        if key in ("evidence", "knowledge_version", "contradictions", "validation_status"):
            continue
        new_value = merged.get(key)
        if new_value is None and old_value is not None:
            merged[key] = deepcopy(old_value)
        elif new_value is not None and old_value is not None and new_value != old_value:
            old_sources = {e.get("source") for e in cached.get("evidence", [])
                           if key in (e.get("fields") or {}) and e["fields"][key] == old_value}
            new_sources = {e.get("source") for e in new_evidence
                           if key in (e.get("fields") or {}) and e["fields"][key] == new_value}
            if old_sources and not old_sources.isdisjoint(new_sources):
                # The same source refreshed its fact; current observation wins.
                continue
            if old_sources and new_sources:
                note = f"Fuentes discrepan en {key}: {old_value} / {new_value}."
                if note not in contradictions:
                    contradictions.append(note)
    merged["contradictions"] = contradictions
    if preserve_review or cached.get("validation_status") == "review":
        merged["validation_status"] = "review"
    return merged


def _keep_reviewed_record(fresh, cached):
    """Record a later observation without silently changing a user-reviewed fact."""
    result = deepcopy(cached)
    evidence = list(result.get("evidence") or [])
    known = {(e.get("source"), e.get("data_date"), e.get("version")) for e in evidence}
    evidence.extend(e for e in fresh.get("evidence", [])
                    if (e.get("source"), e.get("data_date"), e.get("version")) not in known)
    result["evidence"] = evidence
    result["validation_status"] = "review"
    return result


def research_instruments(result, snapshot, catalogs, *, refresh=False, today=None,
                         provider=None, store=None, limits=None, clock=monotonic,
                         selection_scope="ARGENTINA_SIN_BROKER"):
    """Research supplied candidates and a small curated universe without profile leakage."""
    started = clock()
    limits = limits or ResearchLimits()
    allow_provider = provider is not False
    provider = ReferenceProvider() if provider is None else provider
    store_error = None
    if store is None:
        try:
            store = KnowledgeStore()
        except Exception:
            store_error = "No se pudieron recuperar los datos de investigación guardados anteriormente."
            store = None
    universe = load_universe()
    source_pools, omitted, source_originals = _source_records(catalogs, today, limits.max_results)
    categories, events, errors, versions = [], [], [], {}
    if store_error:
        errors.append(store_error)
    query_count = 0
    initial_query_count = 0
    query_sources = set()
    failed_sources = set()
    raw_categories = result.get("cartera_porcentual", {})
    invalid_weight_categories = {
        category for category, weight in raw_categories.items()
        if not _finite_num(weight) or weight < 0 or weight > 100
    }
    valid_positive_weights = [weight for weight in raw_categories.values()
                              if _finite_num(weight) and 0 < weight <= 100]
    if sum(valid_positive_weights) > 100.000001:
        invalid_weight_categories.update(category for category, weight in raw_categories.items()
                                         if _finite_num(weight) and weight > 0)
    for category in invalid_weight_categories:
        categories.append({
            "schema_version": 4, "selection_scope": selection_scope, "category": category,
            "decision": "REQUIERE_REVISION", "eligible": False,
            "selected_id": None, "selected": [], "evaluated": [],
            "rule_ids": ["R_ASIGNACION_INVALIDA"],
            "reasons": ["El porcentaje asignado debe ser numérico, no negativo, no superar 100% y el total de categorías no exceder 100%."],
            "missing_fields": [], "comparison": {"original": None, "alternative": None},
            "policy_version": POLICY_VERSION, "expert_review": "pending",
            "educational_selection": {"status": "NO_SELECTION", "cards": []},
        })
    def investigate(candidate, cached=None, force=False):
        nonlocal query_count, initial_query_count
        candidate = deepcopy(candidate)
        if cached and cached.get("validation_status") == "review":
            candidate = _keep_reviewed_record(candidate, cached)
        elif cached and not force and not refresh and _fresh_cached(cached, today):
            candidate = deepcopy(cached)
        else:
            if cached and _fresh_cached(cached, today): candidate = _merge_fresh_record(candidate, cached)
        if not cached or cached.get("validation_status") != "review":
            if not allow_provider:
                candidate["reference_status"] = "not_checked"
            elif hasattr(provider, "supports") and not provider.supports(candidate):
                candidate["reference_status"] = "unsupported"
            else:
                source_key = provider.source_key(candidate) if hasattr(provider, "source_key") else None
                counts_as_query = source_key not in query_sources if source_key else True
                remaining = min(4, max(0, limits.max_seconds - (clock() - started)))
                if (counts_as_query and query_count >= limits.max_queries) or remaining <= 0:
                    candidate["reference_status"] = "not_checked"
                elif source_key and source_key in failed_sources:
                    candidate["reference_status"] = "source_unavailable"
                else:
                    try:
                        candidate = provider.research(candidate, refresh=(refresh if counts_as_query else False),
                                                      today=today, timeout=remaining)
                        if counts_as_query:
                            query_count += 1
                            if force: initial_query_count += 1
                            if source_key: query_sources.add(source_key)
                    except MarketDataError as exc:
                        candidate["reference_status"] = "source_unavailable"
                        errors.append(f"{candidate.get('name') or candidate.get('canonical_id')}: {exc}")
                        if counts_as_query:
                            query_count += 1
                            if force: initial_query_count += 1
                            if source_key:
                                query_sources.add(source_key)
                                failed_sources.add(source_key)
                    except Exception:
                        candidate["reference_status"] = "source_unavailable"
                        errors.append(f"{candidate.get('name') or candidate.get('canonical_id')}: no se pudo procesar la fuente de referencia.")
                        if counts_as_query:
                            query_count += 1
                            if force: initial_query_count += 1
                            if source_key:
                                query_sources.add(source_key)
                                failed_sources.add(source_key)
                if cached and _fresh_cached(cached, today) and cached.get("validation_status") != "review":
                    candidate = _merge_fresh_record(candidate, cached)
        if store is not None:
            try:
                candidate = store.save(candidate)
            except Exception:
                errors.append("No se pudieron guardar o recuperar los datos de investigación anteriores.")
        return candidate
    def cached_record(candidate):
        if store is None: return None
        try:
            return store.latest(candidate.get("canonical_id"))
        except Exception:
            errors.append("No se pudieron recuperar los datos de investigación anteriores.")
            return None
    curated = {}
    selected_records = []

    category_order = [category for category in raw_categories if category not in invalid_weight_categories]
    category_position = {category: index for index, category in enumerate(category_order)}
    category_order.sort(key=lambda c: (c == "Renta variable", category_position[c]))
    def candidate_priority(candidate, context, evaluated=None, eligible_order=None):
        if evaluated is None:
            evaluated = rank_candidates([candidate], context, today=today)[0]
        record = evaluated["record"]
        strict_state = evaluated["decision"]
        if evaluated["eligible"] and eligible_order is not None:
            return (0, eligible_order.get(record.get("canonical_id"), 10**12),
                    str(record.get("canonical_id") or ""))
        # Excluded and contradictory records remain auditable, but should not
        # consume scarce source queries while potentially eligible records exist.
        state_rank = 0 if evaluated["eligible"] else (1 if strict_state == "INFORMACION_INSUFICIENTE" else 2)
        missing = len(evaluated["missing_fields"])
        quote_matches = (record.get("quotation_currency") == context.get("currency")
                         and bool(_evidence(record, "quotation_currency", today or datetime.now(timezone.utc).date(), 30)))
        subscription_matches = (record.get("subscription_currency") == context.get("currency")
                                and bool(_evidence(record, "subscription_currency", today or datetime.now(timezone.utc).date(), 30)))
        currency_match = quote_matches if context.get("selection_scope") == "instrument_recommendation" else quote_matches and subscription_matches
        category_match = (record.get("category") == context.get("category")
                          and bool(_evidence(record, "category", today or datetime.now(timezone.utc).date(), 30))
                          and bool(_evidence(record, "exposure", today or datetime.now(timezone.utc).date(), 30)))
        factors = evaluated["ranking_factors"]
        observed = factors.get("published_fund_fees", factors.get("costos"))
        settlement = factors.get("settlement_days", factors.get("operacion"))
        if not _finite_num(observed): observed = 10**12
        if not _finite_num(settlement): settlement = 10**12
        return (state_rank, missing, 0 if category_match else 1, 0 if currency_match else 1,
                settlement, observed, str(record.get("canonical_id") or ""))

    # Prepare the complete input pool first, then spend source requests in
    # category rounds. Collapse alternate classes of the same fund before
    # requesting detail so one issuer cannot consume the entire query budget.
    query_queues = {}
    preinvestigated = {}
    for category in category_order:
        weight = raw_categories[category]
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        budget = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0)) * weight / 100
        context = _profile_context(snapshot, result, category, budget, weight, [], selection_scope)
        candidates = list(source_pools.get(category, []))
        ranked = rank_candidates(candidates, context, today=today)
        by_id = {item.get("canonical_id"): item for item in ranked}
        eligible_order = {item.get("canonical_id"): index for index, item in
                          enumerate(item for item in ranked if item.get("eligible"))}
        candidates.sort(key=lambda row: candidate_priority(
            row, context, by_id.get(row.get("canonical_id")), eligible_order))
        grouped, seen_underlyings = [], set()
        for row in candidates:
            key = row.get("underlying_id") or row.get("canonical_id")
            if key in seen_underlyings:
                continue
            seen_underlyings.add(key)
            grouped.append(row)
        query_queues[category] = grouped[:limits.max_results]
    max_queue = max((len(queue) for queue in query_queues.values()), default=0)
    for round_index in range(max_queue):
        for category in category_order:
            queue = query_queues.get(category, [])
            if round_index >= len(queue):
                continue
            candidate = queue[round_index]
            source_key = provider.source_key(candidate) if allow_provider and hasattr(provider, "source_key") else None
            shared_source = bool(source_key and source_key in query_sources)
            if clock() - started >= limits.max_seconds:
                continue
            if query_count >= limits.max_queries and not shared_source:
                continue
            investigated = investigate(candidate, cached_record(candidate), force=True)
            preinvestigated[(category, investigated.get("canonical_id"))] = investigated
            curated[investigated.get("canonical_id")] = investigated

    # If a source pool did not yield a sufficiently evidenced candidate, queue
    # curated discovery candidates for a second fair round across categories.
    expansion_queues = {}
    for category in category_order:
        weight = raw_categories[category]
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        budget = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0)) * weight / 100
        context = _profile_context(snapshot, result, category, budget, weight, [], selection_scope)
        initial = [preinvestigated.get((category, row.get("canonical_id")), row)
                   for row in query_queues.get(category, [])]
        original_record = source_originals.get(category)
        original_id = original_record.get("canonical_id") if original_record else None
        evaluated_initial = decide_category(initial, context, original_id=original_id,
                                             can_expand=False, today=today)
        if evaluated_initial["decision"] != "INFORMACION_INSUFICIENTE":
            continue
        wanted = {row.get("canonical_id") for row in initial}
        extras = [deepcopy(row) for row in universe
                  if row.get("canonical_id") not in wanted and row.get("category") == category]
        ranked_extras = rank_candidates(extras, context, today=today)
        by_id = {item.get("canonical_id"): item for item in ranked_extras}
        eligible_order = {item.get("canonical_id"): index for index, item in
                          enumerate(item for item in ranked_extras if item.get("eligible"))}
        extras.sort(key=lambda row: candidate_priority(
            row, context, by_id.get(row.get("canonical_id")), eligible_order))
        expansion_queues[category] = extras[:max(0, limits.max_results - len(initial))]
    expanded = {}
    max_expansion = max((len(queue) for queue in expansion_queues.values()), default=0)
    for round_index in range(max_expansion):
        for category in category_order:
            queue = expansion_queues.get(category, [])
            if round_index >= len(queue):
                continue
            candidate = queue[round_index]
            source_key = provider.source_key(candidate) if allow_provider and hasattr(provider, "source_key") else None
            shared_source = bool(source_key and source_key in query_sources)
            if clock() - started >= limits.max_seconds:
                continue
            if query_count >= limits.max_queries and not shared_source:
                continue
            investigated = investigate(candidate, cached_record(candidate))
            expanded[(category, investigated.get("canonical_id"))] = investigated
            curated[investigated.get("canonical_id")] = investigated

    for category in category_order:
        weight = raw_categories[category]
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        budget = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0)) * weight / 100
        context = _profile_context(snapshot, result, category, budget, weight, selected_records, selection_scope)
        initial_candidates = list(query_queues.get(category, source_pools.get(category, [])))
        initial_ranked = rank_candidates(initial_candidates, context, today=today)
        initial_evaluations = {item.get("canonical_id"): item for item in initial_ranked}
        initial_eligible_order = {item.get("canonical_id"): index for index, item in
                                  enumerate(item for item in initial_ranked if item.get("eligible"))}
        initial_candidates.sort(key=lambda candidate: candidate_priority(
            candidate, context, initial_evaluations.get(candidate.get("canonical_id")), initial_eligible_order))
        original_record = source_originals.get(category)
        initial = initial_candidates[:limits.max_results]
        initial = [preinvestigated.get((category, record.get("canonical_id")))
                   or investigate(record, cached_record(record), force=True) for record in initial]
        for record in initial:
            curated[record.get("canonical_id")] = record
        # FCI evidence often supports identity only; every rule evaluation remains
        # explicit about unverified operational and exposure facts.
        records = list(initial)
        original_id = original_record.get("canonical_id") if original_record else None
        initial_decision = decide_category(records, context, original_id=original_id,
                                           can_expand=False, today=today)
        if original_id and original_record and all(x.get("canonical_id") != original_id for x in records):
            initial_decision["comparison"]["original"] = rank_candidates([original_record], context, today=today)[0]
        initial_decision["original_id"] = original_id
        # Curated records are discovery leads only; they enter after an
        # insufficient comparison and undergo the same evaluator as source rows.
        expand_needed = initial_decision["decision"] in ("INFORMACION_INSUFICIENTE", "AMPLIAR_BUSQUEDA")
        extras = [candidate for (extra_category, _), candidate in expanded.items()
                  if extra_category == category]
        if expand_needed and extras:
            events.append({"event": "AMPLIAR_BUSQUEDA", "category": category,
                           "reason": initial_decision["reasons"][0]})
            records.extend(extras[:max(0, limits.max_results - len(records))])
        decision = decide_category(records, context, original_id=original_id,
                                   can_expand=False,
                                   today=today)
        if original_id and original_record and all(x.get("canonical_id") != original_id for x in records):
            decision["comparison"]["original"] = rank_candidates([original_record], context, today=today)[0]
        decision["schema_version"] = 4
        decision["selection_scope"] = selection_scope
        decision["educational_selection"] = {"status": "SELECTED_BY_RULES" if decision["selected"] else "NO_SELECTION",
                                              "cards": deepcopy(decision["selected"])}
        categories.append(decision)
        decision["initial_evaluation"] = initial_decision
        # Two cards are alternative illustrations of the same category amount.
        # Only its first choice participates in hypothetical concentration checks.
        if decision.get("selected"):
            selected_records.append({**decision["selected"][0], "allocation_weight": weight})
        versions.update({r.get("canonical_id"): r.get("knowledge_version", 0) for r in records if r.get("canonical_id")})

    try:
        from .instruments import execution_id
        exec_id = execution_id(result, snapshot)
    except ImportError:
        exec_id = None
    return {"schema_version": 4, "scope": selection_scope, "selection_scope": selection_scope,
            "execution_id": exec_id, "policy_version": POLICY_VERSION,
            "universe_version": UNIVERSE_VERSION, "knowledge_versions": versions,
            "expert_review": "pending", "inputs": deepcopy(snapshot), "categories": categories,
            "educational_universe": [
                {**deepcopy(item), **deepcopy(curated.get(item.get("canonical_id"), {})),
                 "availability": _availability(curated.get(item.get("canonical_id")))}
                for item in universe
            ],
            "search": {"limits": {"max_queries": limits.max_queries, "max_seconds": limits.max_seconds,
                                   "max_results": limits.max_results},
                       "queries": query_count, "initial_source_queries": initial_query_count,
                       "elapsed_seconds": max(0, clock()-started),
                       "truncated": query_count >= limits.max_queries or clock()-started >= limits.max_seconds or bool(omitted),
                       "omitted_source_candidates": omitted,
                       "events": events, "errors": errors},
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _availability(record):
    if not record:
        return "curated_reference_not_checked"
    return {"identity_observed": "identity_confirmed", "source_unavailable": "source_unavailable",
            "unsupported": "reference_unsupported", "not_checked": "curated_reference_not_checked"}.get(
                record.get("reference_status"), "curated_reference_not_checked")
