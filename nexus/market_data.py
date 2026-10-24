"""Read-only ArgentinaDatos client; independent of financial allocation rules."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from threading import Lock
from time import monotonic
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE_URL = "https://raw.githubusercontent.com/enzonotario/argentinadatos.com/main/datos/v1/finanzas/"
SOURCE = "ArgentinaDatos · publicación pública en GitHub"
FUNDS_PATH = "fci/fondos/index.json"
CACHE_TTL_SECONDS = 900
MAX_DATA_AGE_DAYS = 7  # Quality window for examples, not a macroeconomic rule.
_cache = {}
_cache_lock = Lock()


class MarketDataError(Exception):
    """Expected source failure, safe to present without aborting evaluation."""


def valid_data_date(value, today=None):
    """Return an ISO date only when the source date is valid and recent."""
    today = today or datetime.now(timezone.utc).date()
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if parsed is None or not 0 <= (today - parsed).days <= MAX_DATA_AGE_DAYS:
        return None
    return parsed.isoformat()


class ArgentinaDatosClient:
    def __init__(self, *, timeout=8, opener=urlopen, clock=monotonic):
        self.timeout = timeout
        self.opener = opener
        self.clock = clock

    def get(self, path, *, refresh=False):
        # Only fixed provider paths are used; never accept a URL from API data.
        if not path or ":" in path or ".." in path or path.startswith("/"):
            raise MarketDataError("Ruta de fuente inválida.")
        url = BASE_URL + path.strip("/")
        now = self.clock()
        with _cache_lock:
            cached = _cache.get(url)
            if not refresh and cached and 0 <= now - cached[0] < CACHE_TTL_SECONDS:
                return {**deepcopy(cached[1]), "cache": True}
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "NEXUS-academic-demo/1.0"})
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(32_000_001)
            if len(raw) > 32_000_000:
                raise MarketDataError("La respuesta de la fuente supera el tamaño permitido.")
            payload = json.loads(raw)
            if not isinstance(payload, (dict, list)):
                raise MarketDataError("La fuente devolvió un formato inesperado.")
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise MarketDataError("No pudimos consultar esta fuente. Podés volver a intentar.") from exc
        record = {"datos": payload, "url": url, "fuente": SOURCE,
                  "consultado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cache": False}
        with _cache_lock:
            _cache[url] = (now, deepcopy(record))
        return record

    def fund_catalog(self, *, refresh=False, today=None):
        record = self.get(FUNDS_PATH, refresh=refresh)
        payload = record["datos"]
        if not isinstance(payload, dict) or not isinstance(payload.get("fondos"), list):
            raise MarketDataError("El catálogo de fondos cambió de formato. No podemos verificar los ejemplos.")
        published = payload.get("fechaActualizacion")
        try:
            updated = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if updated.tzinfo is None or not valid_data_date(updated.date().isoformat(), today):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise MarketDataError("La publicación no tiene una fecha reciente y válida. No la usamos como catálogo vigente.") from None
        return {key: value for key, value in record.items() if key != "datos"} | {
            "fondos": payload["fondos"], "fecha_publicacion": published,
            "documentacion": "https://argentinadatos.com/docs/operations/get-finanzas-fci-fondos",
        }
