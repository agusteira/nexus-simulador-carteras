"""Bounded instrument research layered over the legacy FCI examples."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

from .instrument_knowledge import UNIVERSE_VERSION, KnowledgeStore, load_universe, normalize_fund
from .instrument_providers import MarketDataError, ReferenceProvider
from .instrument_rules import POLICY_VERSION, _evidence, _finite_num, build_educational_selection, decide_category


@dataclass(frozen=True)
class ResearchLimits:
    max_queries: int = 6
    max_seconds: float = 16
    max_results: int = 20

    def __post_init__(self):
        object.__setattr__(self, "max_queries", max(0, int(self.max_queries)))
        object.__setattr__(self, "max_seconds", max(0, float(self.max_seconds)))
        object.__setattr__(self, "max_results", max(0, int(self.max_results)))


def _profile_context(snapshot, result, category, budget, weight, already_selected):
    profile = snapshot.get("perfil") or {}
    return {"category": category, "profile": result.get("perfil_riesgo"),
            "horizon_months": profile.get("horizonte"), "objective": profile.get("objetivo"),
            "budget": budget, "allocation_weight": weight, "tolerance": profile.get("tolerancia"),
            "currency": result.get("moneda", profile.get("moneda")),
            "liquidity_required": profile.get("liquidez"), "allowed_access": profile.get("acceso"),
            "already_selected": list(already_selected)}


def _source_records(catalogs, today, max_results):
    # Keep a bounded pool for each source category. Do not let alphabetical order
    # consume the entire research budget with a single class.
    pools, omitted, originals = {}, {}, {}
    for source in catalogs:
        for fund in source.get("fondos", []):
            try:
                record = normalize_fund(fund, source, today=today)
            except (TypeError, ValueError):
                continue
            category = record.get("category")
            hint = record.get("category_hint")
            applicable = ([category] if category else ([hint] if hint in ("Renta fija inflación", "Renta fija cambiaria", "Renta variable", "Liquidez inmediata")
                          else (["Renta fija inflación", "Renta fija cambiaria"]
                                if str(fund.get("tipoRenta", "")).casefold() in ("renta fija", "fija") else [])))
            for target in applicable:
                pools.setdefault(target, []).append(record)
                originals.setdefault(target, deepcopy(record))
    # Scan every normalized row before applying the per-category investigation cap.
    for target, pool in pools.items():
        pool.sort(key=lambda r: (0 if r.get("education_id") else 1,
                                 0 if r.get("familiar") and r.get("familiarity_basis") else 1,
                                 0 if (r.get("name") or "").casefold().strip().endswith(("clase a", "-a", " a")) else 1,
                                 str(r.get("canonical_id") or "")))
        if len(pool) > max_results:
            omitted[target] = len(pool) - max_results
            unknown = [r for r in pool if not r.get("education_id")]
            known_family = [r for r in pool if r.get("education_id")]
            reserve_unknown = min(4, max_results, len(unknown))
            selected = known_family[:max_results-reserve_unknown] + unknown[:reserve_unknown]
            selected_ids = {r.get("canonical_id") for r in selected}
            selected.extend(r for r in pool if r.get("canonical_id") not in selected_ids)
            selected = selected[:max_results]
            original = originals.get(target)
            if original and all(r.get("canonical_id") != original.get("canonical_id") for r in selected) and selected:
                selected[-1] = original
            pools[target] = selected
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
                         provider=None, store=None, limits=None, clock=monotonic):
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
            store_error = "No se pudo abrir el almacenamiento local de conocimiento."
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
    reserve_equity_sources = 3 if raw_categories.get("Renta variable", 0) > 0 and limits.max_queries >= 6 else 0
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
                fci_ceiling = limits.max_queries - reserve_equity_sources
                reserve_fci = counts_as_query and candidate.get("instrument_type") == "FCI" and query_count >= fci_ceiling
                if (counts_as_query and query_count >= limits.max_queries) or reserve_fci or remaining <= 0:
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
                errors.append("No se pudo guardar o recuperar conocimiento local.")
        return candidate
    def cached_record(candidate):
        if store is None: return None
        try:
            return store.latest(candidate.get("canonical_id"))
        except Exception:
            errors.append("No se pudo recuperar conocimiento local.")
            return None
    curated = {}
    selected_records = []

    category_order = list(raw_categories)
    category_position = {category: index for index, category in enumerate(category_order)}
    category_order.sort(key=lambda c: (c == "Renta variable", category_position[c]))
    for category in category_order:
        weight = raw_categories[category]
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        budget = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0)) * weight / 100
        context = _profile_context(snapshot, result, category, budget, weight, selected_records)
        initial_candidates = list(source_pools.get(category, []))
        def initial_priority(candidate):
            minimum = candidate.get("minimum")
            minimum_backed = _finite_num(minimum) and bool(_evidence(candidate, "minimum", today or datetime.now(timezone.utc).date(), 7 if candidate.get("instrument_type") == "FCI" else 30))
            unaffordable = minimum_backed and _finite_num(budget) and budget < minimum
            observed_class = bool(_evidence(candidate, "category", today or datetime.now(timezone.utc).date(), 30)
                                  and _evidence(candidate, "exposure", today or datetime.now(timezone.utc).date(), 30)
                                  and candidate.get("category") == category)
            hinted_class = candidate.get("category_hint") == category
            class_a = 0 if (candidate.get("name") or "").casefold().strip().endswith(("clase a", "-a", " a")) else 1
            return (1 if unaffordable else 0, 0 if observed_class else (1 if hinted_class else 2),
                    0 if candidate.get("education_id") else 1, class_a, str(candidate.get("canonical_id") or ""))
        initial_candidates.sort(key=initial_priority)
        original_record = source_originals.get(category)
        if limits.max_results > 0 and original_record and all(x.get("canonical_id") != original_record.get("canonical_id") for x in initial_candidates):
            initial_candidates[-1:] = [original_record]
        initial = initial_candidates[:limits.max_results]
        initial = [investigate(record, cached_record(record), force=True) for record in initial]
        for record in initial:
            curated[record.get("canonical_id")] = record
        # FCI evidence often supports identity only; every rule evaluation remains
        # explicit about unverified operational and exposure facts.
        records = list(initial)
        original_id = original_record.get("canonical_id") if original_record else (initial[0].get("canonical_id") if initial else None)
        initial_decision = decide_category(records, context, original_id=original_id,
                                           can_expand=False, today=today)
        # Matching only category and exposure prevents unrelated substitutions.
        wanted = {x.get("canonical_id") for x in records}
        extras = [deepcopy(x) for x in universe if x.get("canonical_id") not in wanted
                  and x.get("category") == category]
        if context.get("currency") == "ARS":
            source_rank = {"CEDEAR:SPY:BYMA": 0, "CEDEAR:MELI:BYMA": 1, "LOCAL_SHARE:YPFD:BYMA": 2,
                           "ETF:SPY:NYSE_ARCA": 3, "ADR:YPF:NYSE": 4, "FOREIGN_SHARE:MELI:NASDAQ": 5}
        elif context.get("currency") == "USD":
            source_rank = {"ETF:SPY:NYSE_ARCA": 0, "FOREIGN_SHARE:MELI:NASDAQ": 1, "ADR:YPF:NYSE": 2,
                           "CEDEAR:SPY:BYMA": 3, "CEDEAR:MELI:BYMA": 4, "LOCAL_SHARE:YPFD:BYMA": 5}
        else:
            source_rank = {"ETF:SPY:NYSE_ARCA": 0, "CEDEAR:SPY:BYMA": 1, "CEDEAR:MELI:BYMA": 2,
                           "FOREIGN_SHARE:MELI:NASDAQ": 3, "LOCAL_SHARE:YPFD:BYMA": 4, "ADR:YPF:NYSE": 5}
        extras.sort(key=lambda r: (source_rank.get(r.get("canonical_id"), 9),
                                  str(r.get("canonical_id") or "")))
        expand_needed = initial_decision["decision"] in ("INFORMACION_INSUFICIENTE", "AMPLIAR_BUSQUEDA")
        may_query = not allow_provider or (query_count < limits.max_queries and clock() - started < limits.max_seconds)
        if expand_needed and extras and may_query:
            # Reserve at most four result slots for distinct curated identities.
            reserve = min(4, len(extras), max(0, limits.max_results - (1 if records else 0)))
            capacity = max(1 if records else 0, limits.max_results - reserve)
            if len(records) > capacity:
                omitted[category] = omitted.get(category, 0) + len(records) - capacity
                records = records[:capacity]
                if original_id and all(item.get("canonical_id") != original_id for item in records):
                    original_record = next((item for item in initial if item.get("canonical_id") == original_id), original_record)
                    if records: records[-1] = original_record
                    elif capacity > 0: records.append(original_record)
            extras = extras[:max(0, limits.max_results - len(records))]
            if extras:
                events.append({"event": "AMPLIAR_BUSQUEDA", "category": category,
                               "reason": initial_decision["reasons"][0]})
            for candidate in extras:
                candidate = investigate(candidate, cached_record(candidate))
                records.append(candidate)
                curated[candidate.get("canonical_id")] = candidate
                if len(records) >= limits.max_results:
                    break
        decision = decide_category(records, context, original_id=original_id,
                                   can_expand=False,
                                   today=today)
        decision["educational_selection"] = build_educational_selection(records, context, today=today)
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
    return {"execution_id": exec_id, "policy_version": POLICY_VERSION,
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
