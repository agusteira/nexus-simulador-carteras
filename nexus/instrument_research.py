"""Bounded instrument research layered over the legacy FCI examples."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

from .instrument_knowledge import UNIVERSE_VERSION, KnowledgeStore, load_universe, normalize_fund
from .instrument_providers import MarketDataError, ReferenceProvider
from .instrument_rules import POLICY_VERSION, decide_category


@dataclass(frozen=True)
class ResearchLimits:
    max_queries: int = 4
    max_seconds: float = 12
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
    pools, omitted = {}, {}
    for source in catalogs:
        for fund in source.get("fondos", []):
            try:
                record = normalize_fund(fund, source, today=today)
            except (TypeError, ValueError):
                continue
            category = record.get("category")
            applicable = [category] if category else (["Renta fija inflación", "Renta fija cambiaria"]
                if str(fund.get("tipoRenta", "")).casefold() == "renta fija" else [])
            for target in applicable:
                pool = pools.setdefault(target, [])
                if len(pool) < max_results:
                    pool.append(record)
                else:
                    omitted[target] = omitted.get(target, 0) + 1
    return pools, omitted


def _fresh_cached(record, today=None):
    if record.get("validation_status") == "review":
        return True
    now = datetime.now(timezone.utc)
    for evidence in record.get("evidence", []):
        expiry = evidence.get("expires_at")
        if not expiry:
            continue
        try:
            if datetime.fromisoformat(expiry.replace("Z", "+00:00")) > now:
                return True
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
    source_pools, omitted = _source_records(catalogs, today, limits.max_results)
    categories, events, errors, versions = [], [], [], {}
    if store_error:
        errors.append(store_error)
    query_count = 0
    query_sources = set()
    failed_sources = set()
    raw_categories = result.get("cartera_porcentual", {})
    curated = {}
    selected_records = []

    for category, weight in raw_categories.items():
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            continue
        budget = result.get("capital", (snapshot.get("perfil") or {}).get("capital", 0)) * weight / 100
        context = _profile_context(snapshot, result, category, budget, weight, selected_records)
        initial = source_pools.get(category, [])[:limits.max_results]
        for index, record in enumerate(initial):
            if store is not None:
                try:
                    cached = store.latest(record["canonical_id"])
                    if cached and cached.get("validation_status") == "review":
                        record = _keep_reviewed_record(record, cached)
                        record = store.save(record)
                    elif cached and _fresh_cached(cached):
                        record = _merge_fresh_record(record, cached)
                        record = store.save(record)
                    else:
                        record = store.save(record)
                except Exception:
                    errors.append("No se pudo guardar o recuperar conocimiento local.")
            initial[index] = record
        # FCI evidence often supports identity only; every rule evaluation remains
        # explicit about unverified operational and exposure facts.
        records = list(initial)
        original_id = initial[0].get("canonical_id") if initial else None
        initial_decision = decide_category(records, context, original_id=original_id,
                                           can_expand=False, today=today)
        # Matching only category and exposure prevents unrelated substitutions.
        wanted = {x.get("canonical_id") for x in records}
        extras = [deepcopy(x) for x in universe if x.get("canonical_id") not in wanted
                  and x.get("category") == category]
        expand_needed = initial_decision["decision"] in ("INFORMACION_INSUFICIENTE", "AMPLIAR_BUSQUEDA")
        may_query = not allow_provider or (query_count < limits.max_queries and clock() - started < limits.max_seconds)
        if expand_needed and extras and may_query:
            # Reserve at most four result slots for distinct curated identities.
            reserve = min(4, len(extras), max(0, limits.max_results - (1 if records else 0)))
            capacity = max(1 if records else 0, limits.max_results - reserve)
            if len(records) > capacity:
                omitted[category] = omitted.get(category, 0) + len(records) - capacity
                records = records[:capacity]
                original_id = records[0].get("canonical_id") if records else None
            extras = extras[:max(0, limits.max_results - len(records))]
            if extras:
                events.append({"event": "AMPLIAR_BUSQUEDA", "category": category,
                               "reason": initial_decision["reasons"][0]})
            for candidate in extras:
                cached = None
                try:
                    cached = store.latest(candidate["canonical_id"]) if store is not None else None
                except Exception:
                    errors.append("No se pudo recuperar conocimiento local.")
                if cached and cached.get("validation_status") == "review":
                    candidate = _keep_reviewed_record(candidate, cached)
                elif cached and not refresh and _fresh_cached(cached):
                    candidate = cached
                else:
                    elapsed = clock() - started
                    remaining = min(4, max(0, limits.max_seconds - elapsed))
                    if not allow_provider:
                        candidate["reference_status"] = "not_checked"
                    elif hasattr(provider, "supports") and not provider.supports(candidate):
                        candidate["reference_status"] = "unsupported"
                    else:
                        source_key = provider.source_key(candidate) if hasattr(provider, "source_key") else None
                        counts_as_query = source_key not in query_sources if source_key else True
                        if (counts_as_query and query_count >= limits.max_queries) or remaining <= 0:
                            break
                        if source_key and source_key in failed_sources:
                            candidate["reference_status"] = "source_unavailable"
                        else:
                            try:
                                candidate = provider.research(candidate, refresh=(refresh if counts_as_query else False), today=today, timeout=remaining)
                                if counts_as_query:
                                    query_count += 1
                                    if source_key:
                                        query_sources.add(source_key)
                            except MarketDataError as exc:
                                candidate["reference_status"] = "source_unavailable"
                                if counts_as_query:
                                    query_count += 1
                                    if source_key:
                                        query_sources.add(source_key)
                                        failed_sources.add(source_key)
                                errors.append(f"{candidate.get('name') or candidate.get('canonical_id')}: {exc}")
                            except Exception as exc:
                                candidate["reference_status"] = "source_unavailable"
                                if counts_as_query:
                                    query_count += 1
                                    if source_key:
                                        query_sources.add(source_key)
                                        failed_sources.add(source_key)
                                errors.append(f"{candidate.get('name') or candidate.get('canonical_id')}: no se pudo procesar la fuente de referencia.")
                    if cached and _fresh_cached(cached) and cached.get("validation_status") != "review":
                        candidate = _merge_fresh_record(candidate, cached)
                    if store is not None:
                        try:
                            candidate = store.save(candidate)
                        except Exception:
                            errors.append("No se pudo guardar conocimiento local.")
                records.append(candidate)
                curated[candidate.get("canonical_id")] = candidate
                if len(records) >= limits.max_results:
                    break
        decision = decide_category(records, context, original_id=original_id,
                                   can_expand=False,
                                   today=today)
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
                       "queries": query_count, "initial_source_queries": 1,
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
