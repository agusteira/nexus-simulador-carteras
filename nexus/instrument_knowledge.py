"""Normalized instrument facts and append-only local knowledge history."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from .matrices import CATEGORIAS, directorio_datos

UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "config" / "instrument_universe.json"
_ID = re.compile(r"^[A-Z0-9][A-Z0-9:_./-]{1,127}$")
_FIELDS = ("canonical_id", "instrument_type", "ticker", "market", "stable_id", "underlying_id", "name", "category", "exposure", "quotation_currency", "subscription_currency", "economic_currency", "minimum", "lot_size", "unit_price", "costs", "settlement_days", "liquidity", "access", "issuer", "sector", "country", "holdings", "description", "risks", "familiar", "familiarity_basis", "market_metric", "validation_status", "contradictions", "missing_fields", "evidence")


def load_universe():
    data = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    global UNIVERSE_VERSION
    UNIVERSE_VERSION = data["version"]
    return deepcopy(data["instruments"])


UNIVERSE_VERSION = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))["version"]


def _iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _valid_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _currency(value):
    if not isinstance(value, str):
        return None
    text = " ".join("".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower().split())
    return {"ars": "ARS", "peso": "ARS", "pesos": "ARS", "peso argentino": "ARS", "pesos argentinos": "ARS",
            "$": "ARS", "usd": "USD", "us$": "USD", "dolar": "USD", "dolares": "USD",
            "dolar estadounidense": "USD", "dolares estadounidenses": "USD"}.get(text)


def _normalized_type(value):
    if not isinstance(value, str):
        return None
    text = " ".join("".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).lower().split())
    return {"renta variable": "variable", "mercado de dinero": "money_market", "mercado dinero": "money_market",
            "money market": "money_market", "renta fija": "fixed"}.get(text)


def normalize_fund(fund, source, today=None):
    """Normalize only explicit FCI source fields; names/horizons never imply facts."""
    if not isinstance(fund, dict):
        raise TypeError("fund debe ser un diccionario")
    if not isinstance(source, dict):
        raise TypeError("source debe incluir fuente y url")
    fund_id, class_id = fund.get("fondoId"), fund.get("claseId")
    if fund_id in (None, "") or class_id in (None, ""):
        raise ValueError("El fondo requiere fondoId y claseId para una identidad estable.")
    today = today or datetime.now(timezone.utc).date()
    data_date = _iso_date(fund.get("fecha"))
    observed = source.get("consultado_en") or source.get("observed_at")
    try:
        if observed:
            parsed_observed = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
            observed = parsed_observed.isoformat(timespec="seconds") if parsed_observed.tzinfo else None
    except ValueError:
        observed = None
    expires = None
    if data_date:
        expires = datetime.combine(date.fromisoformat(data_date) + timedelta(days=7), time.max, timezone.utc).isoformat(timespec="seconds")
    source_type = _normalized_type(fund.get("tipoRenta"))
    cat = "Renta variable" if source_type == "variable" else ("Liquidez inmediata" if source_type == "money_market" else None)
    exposure = "equity" if source_type == "variable" else ("money_market" if source_type == "money_market" else "unknown")
    currency = _currency(fund.get("moneda"))
    subcurrency = _currency(fund.get("monedaInversion"))
    minimum = fund.get("inversionMinima") if _valid_num(fund.get("inversionMinima")) else None
    settlement = fund.get("plazoLiquidacionDias") if _valid_num(fund.get("plazoLiquidacionDias")) else None
    raw = {k: fund[k] for k in ("nombre", "tipoRenta", "moneda", "monedaInversion", "inversionMinima", "plazoLiquidacionDias", "administradora", "horizonte", "benchmark", "fecha") if k in fund}
    raw = {k: (repr(v) if isinstance(v, float) and not math.isfinite(v) else v) for k, v in raw.items()}
    backed = {"canonical_id": f"AR:FCI:{fund_id}:{class_id}", "instrument_type": "FCI", "market": "AR:FCI", "underlying_id": f"AR:FCI:{fund_id}"}
    if isinstance(fund.get("nombre"), str): backed["name"] = fund["nombre"]
    if source_type: backed["instrument_type"] = "FCI"
    if "tipoRenta" in fund:
        backed["category"] = cat
        backed["exposure"] = exposure
    if currency: backed["quotation_currency"] = currency
    if subcurrency: backed["subscription_currency"] = subcurrency
    if minimum is not None: backed["minimum"] = minimum
    if settlement is not None: backed["settlement_days"] = settlement
    if isinstance(fund.get("administradora"), str): backed["issuer"] = fund["administradora"]
    evidence = [{"source": source.get("fuente", source.get("source", "unknown")), "url": source.get("url"), "fields": backed,
                 "raw_source_fields": raw, "observed_at": observed, "data_date": data_date, "expires_at": expires, "kind": "observed", "version": str(source.get("version", "1"))}] if raw else []
    invalid = [key for key in ("inversionMinima", "plazoLiquidacionDias") if key in fund and fund[key] is not None and not _valid_num(fund[key])]
    name = fund.get("nombre") if isinstance(fund.get("nombre"), str) else None
    return {"canonical_id": f"AR:FCI:{fund_id}:{class_id}", "instrument_type": "FCI", "ticker": None, "market": "AR:FCI",
            "stable_id": None, "underlying_id": f"AR:FCI:{fund_id}", "name": name, "category": cat, "exposure": exposure,
            "quotation_currency": currency, "subscription_currency": subcurrency, "economic_currency": None,
            "minimum": minimum, "lot_size": None, "unit_price": None, "costs": None, "settlement_days": settlement,
            "liquidity": "unknown", "access": "unknown", "issuer": fund.get("administradora"), "issuer_role": "fund_manager", "sector": None, "country": "AR",
            "holdings": None, "description": None, "risks": [], "familiar": False, "familiarity_basis": None, "market_metric": None,
            "explanation": {"kind": "educational_template", "version": "fci-1",
                "text": "Un fondo común reúne aportes de distintas personas y los administra en una cartera. La clasificación publicada describe una clase amplia; su composición concreta todavía no está verificada.",
                "facts_used": ["instrument_type", "category"]},
            "validation_status": ("review" if invalid or not observed else "observed") if data_date and 0 <= (today - date.fromisoformat(data_date)).days <= 7 else "expired",
            "contradictions": [f"Valor fuente inválido: {key}" for key in invalid], "missing_fields": [x for x in ("quotation_currency" if currency is None else None, "subscription_currency" if subcurrency is None else None, "minimum" if minimum is None else None, "settlement_days" if settlement is None else None, "lot_size", "unit_price", "costs", "economic_currency", "holdings", "liquidity", "access") if x], "evidence": evidence}


def _canonical(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("canonical_id inválido")
    return value


class KnowledgeStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else directorio_datos() / "instrument_knowledge.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.execute("CREATE TABLE IF NOT EXISTS revisions (canonical_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(canonical_id, version))")
            db.execute("CREATE TABLE IF NOT EXISTS feedback (event_id INTEGER PRIMARY KEY AUTOINCREMENT, canonical_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, execution_id TEXT, created_at TEXT NOT NULL)")
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _decode(row):
        return json.loads(row["payload"])

    def save(self, record, *, status=None, _force_revision=False):
        if not isinstance(record, dict):
            raise TypeError("record debe ser un diccionario")
        item = deepcopy(record)
        cid = _canonical(item.get("canonical_id"))
        item.setdefault("validation_status", "proposal")
        if status is not None:
            item["validation_status"] = status
        item.setdefault("evidence", [])
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version,payload FROM revisions WHERE canonical_id=? ORDER BY version DESC LIMIT 1", (cid,)).fetchone()
            if row:
                prior = json.loads(row["payload"])
                # Revisions are immutable metadata, excluded from equality comparison.
                prior_cmp = {k:v for k,v in prior.items() if k != "knowledge_version"}
                item_cmp = {k:v for k,v in item.items() if k != "knowledge_version"}
                if prior_cmp == item_cmp and not _force_revision:
                    db.execute("COMMIT")
                    return deepcopy(prior)
                version = row["version"] + 1
            else:
                version = 1
            item["knowledge_version"] = version
            item["canonical_id"] = cid
            db.execute("INSERT INTO revisions VALUES (?,?,?)", (cid, version, json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False)))
            db.execute("COMMIT")
            return deepcopy(item)
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def latest(self, canonical_id, *, now=None):
        cid = _canonical(canonical_id)
        db = self._connect()
        try:
            row = db.execute("SELECT payload FROM revisions WHERE canonical_id=? ORDER BY version DESC LIMIT 1", (cid,)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        item = json.loads(row["payload"])
        now = now or datetime.now(timezone.utc)
        expired = False
        for e in item.get("evidence", []):
            expiry = e.get("expires_at")
            if not expiry:
                continue
            try:
                parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                comparison_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                expired = expired or parsed <= comparison_now
            except (ValueError, AttributeError, TypeError):
                expired = True
        if expired and item.get("validation_status") != "review":
            item["validation_status"] = "expired"
        return deepcopy(item)

    def history(self, canonical_id):
        cid = _canonical(canonical_id)
        db = self._connect()
        try:
            rows = db.execute("SELECT payload FROM revisions WHERE canonical_id=? ORDER BY version", (cid,)).fetchall()
        finally:
            db.close()
        return [deepcopy(json.loads(r["payload"])) for r in rows]

    def restore(self, canonical_id, version):
        hist = self.history(canonical_id)
        target = next((r for r in hist if r.get("knowledge_version") == version), None)
        if target is None:
            raise KeyError(f"No existe la versión {version} para {canonical_id}")
        target.pop("knowledge_version", None)
        return self.save(target, _force_revision=True)

    def feedback(self, canonical_id, kind, text="", *, execution_id=None):
        cid = _canonical(canonical_id)
        if kind not in ("understood", "known", "correction"):
            raise ValueError("kind debe ser understood, known o correction")
        text = str(text)
        if len(text) > 4000:
            raise ValueError("feedback text supera 4000 caracteres")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("INSERT INTO feedback(canonical_id,kind,text,execution_id,created_at) VALUES(?,?,?,?,?)", (cid, kind, text, execution_id, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            event_id = cur.lastrowid
            if kind == "correction":
                row = db.execute("SELECT payload FROM revisions WHERE canonical_id=? ORDER BY version DESC LIMIT 1", (cid,)).fetchone()
                if row:
                    item = json.loads(row["payload"])
                    item.pop("knowledge_version", None)
                    item["validation_status"] = "review"
                    item.setdefault("contradictions", []).append(str(text))
                    prior_version = db.execute("SELECT MAX(version) v FROM revisions WHERE canonical_id=?", (cid,)).fetchone()["v"]
                    item["knowledge_version"] = prior_version + 1
                    db.execute("INSERT INTO revisions VALUES (?,?,?)", (cid, item["knowledge_version"], json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False)))
            db.execute("COMMIT")
            return event_id
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()
