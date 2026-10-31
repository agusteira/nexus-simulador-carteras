"""Explicit live integration check. Never imported by the offline test suite.

Run: python scripts/check_instrument_sources.py
Only fixed public sources and curated instrument identities leave this process.
No profile, evaluation, credentials, or local knowledge store is read.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nexus.instrument_knowledge import load_universe
from nexus.instrument_providers import ReferenceProvider
from nexus.market_data import ArgentinaDatosClient, MarketDataError


def check_sources():
    checks = []
    try:
        catalog = ArgentinaDatosClient().fund_catalog(refresh=True)
        checks.append({"provider": "ArgentinaDatos", "status": "ok",
                       "records": len(catalog["fondos"]), "published": catalog["fecha_publicacion"]})
    except MarketDataError as exc:
        checks.append({"provider": "ArgentinaDatos", "status": "source_unavailable", "reason": str(exc)})
    provider = ReferenceProvider(timeout=4)
    for record in load_universe():
        started = monotonic()
        try:
            found = provider.research(record)
            checks.append({"id": record["canonical_id"], "status": found.get("reference_status"),
                           "source": provider.source_key(record),
                           "fields_observed": [e["fields"] for e in found.get("evidence", []) if e.get("kind") == "observed"],
                           "seconds": round(monotonic() - started, 2)})
        except MarketDataError as exc:
            checks.append({"id": record["canonical_id"], "source": provider.source_key(record),
                           "status": "source_unavailable", "reason": str(exc),
                           "seconds": round(monotonic() - started, 2)})
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "limits": {"reference_timeout_seconds": 4, "fci_timeout_seconds": 8,
                       "reference_cache_seconds": 900, "reference_max_bytes": 2000000},
            "checks": checks}


if __name__ == "__main__":
    print(json.dumps(check_sources(), ensure_ascii=False, indent=2))
