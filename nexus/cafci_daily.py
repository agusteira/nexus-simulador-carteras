"""Bounded in-memory reader for CAFCI's official daily XLSX report."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import PurePosixPath
import math
import re
from threading import Lock
from time import monotonic
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .market_data import MarketDataError


DAILY_URL = "https://api.pub.cafci.org.ar/pb_get"
CONSULT_URL = "https://estadisticas.cafci.org.ar/consulta-avanzada"
SOURCE = "CAFCI · Planilla Diaria"
CACHE_TTL_SECONDS = 900
MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_ROWS = 12000
MAX_CELLS = 600000
MAX_DAILY_AGE_DAYS = 7
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS = {"m": _MAIN_NS}
_cache = {}
_cache_lock = Lock()


class _SafeDailyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if not (parsed.scheme == "https" and parsed.hostname == "api.pub.cafci.org.ar"
                and parsed.port in (None, 443) and parsed.path == "/pb_get"
                and not parsed.query and not parsed.fragment):
            raise MarketDataError("CAFCI intentó redirigir la planilla fuera de su ruta pública permitida.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_DAILY_OPENER = build_opener(_SafeDailyRedirect())


def _column(ref):
    match = re.match(r"([A-Z]+)", ref or "")
    return match.group(1) if match else None


def _header_key(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip().replace("\u00a0", "")
    if not raw or raw in {"-", "—"}:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        parsed = float(raw)
    except (ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _date(value):
    if not value:
        return None
    raw = str(value).strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    serial = _number(raw)
    if serial is not None and serial >= 0:
        try:
            return date(1899, 12, 30) + timedelta(days=int(serial))
        except (OverflowError, ValueError):
            return None
    return None


def _class_code(value):
    raw = str(value or "").strip()
    if raw.isdigit():
        return int(raw)
    numeric = _number(raw)
    if numeric is not None and numeric >= 0 and numeric.is_integer():
        return int(numeric)
    return None


def _shared_strings(archive):
    try:
        data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    _reject_entities(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise MarketDataError("La planilla diaria de CAFCI contiene XML de texto inválido.") from exc
    return ["".join(node.itertext()) for node in root.findall("m:si", _NS)]


def _reject_entities(data):
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)", data, flags=re.I):
        raise MarketDataError("La planilla diaria de CAFCI contiene declaraciones XML no permitidas.")


def _cell_value(cell, shared):
    kind = cell.attrib.get("t")
    value = cell.find("m:v", _NS)
    if kind == "inlineStr":
        inline = cell.find("m:is", _NS)
        return "".join(inline.itertext()) if inline is not None else ""
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            return ""
    return value.text


def _read_sheet(sheet, shared, today):
    _reject_entities(sheet)
    rows, cells = 0, 0
    header = {}
    observations = {}
    current_row, row_values = None, {}
    try:
        iterator = ET.iterparse(BytesIO(sheet), events=("start", "end"))
        for event, node in iterator:
            if event == "start" and node.tag == f"{{{_MAIN_NS}}}row":
                rows += 1
                if rows > MAX_ROWS:
                    raise MarketDataError("La planilla diaria de CAFCI supera el límite de filas.")
                current_row = int(node.attrib.get("r", rows))
                row_values = {}
            elif event == "end" and node.tag == f"{{{_MAIN_NS}}}c":
                cells += 1
                if cells > MAX_CELLS:
                    raise MarketDataError("La planilla diaria de CAFCI supera el límite de celdas.")
                col = _column(node.attrib.get("r"))
                if col:
                    row_values[col] = _cell_value(node, shared)
                node.clear()
            elif event == "end" and node.tag == f"{{{_MAIN_NS}}}row":
                if current_row == 8:
                    header = row_values
                elif current_row and current_row >= 12:
                    class_id = _class_code(row_values.get("U"))
                    if class_id is not None:
                        parsed_date = _date(row_values.get("E"))
                        qualified_raw = str(row_values.get("AU", "")).strip().casefold()
                        qualified = True if qualified_raw in {"si", "sí", "s", "yes"} else (
                            False if qualified_raw in {"n", "no"} else None)
                        row = {
                            "cafci_class_id": class_id,
                            "daily_date": parsed_date,
                            "nav_per_thousand": _number(row_values.get("F")),
                            "fund_aum": _number(row_values.get("O")),
                            "market_share": _number(row_values.get("Q")),
                            "qualified_only": qualified,
                            "calificacion": str(row_values.get("T", "")).strip() or None,
                        }
                        if parsed_date is not None and parsed_date <= today and (today - parsed_date).days <= MAX_DAILY_AGE_DAYS:
                            previous = observations.get(class_id)
                            if previous is None or parsed_date > previous["daily_date"]:
                                observations[class_id] = row
                node.clear()
                current_row = None
    except MarketDataError:
        raise
    except (ET.ParseError, ValueError, OverflowError) as exc:
        raise MarketDataError("La planilla diaria de CAFCI contiene datos XML inválidos.") from exc
    expected = {"E": "fecha", "F": "valor (mil cuotapartes)", "O": "patrimonio",
                "Q": "market share", "T": "calificacion", "U": "codigo cafci", "AU": "calificado"}
    if any(_header_key(header.get(column)) != label for column, label in expected.items()):
        raise MarketDataError("La planilla diaria de CAFCI no contiene los encabezados esperados.")
    return observations


def parse_daily_xlsx(body, *, today=None):
    """Return the latest valid, recent observation for each exact CAFCI class ID."""
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_COMPRESSED_BYTES:
        raise MarketDataError("La planilla diaria de CAFCI supera el tamaño comprimido permitido.")
    try:
        archive = zipfile.ZipFile(BytesIO(body))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise MarketDataError("La planilla diaria de CAFCI no es un XLSX válido.") from exc
    today = today or datetime.now(timezone.utc).date()
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise MarketDataError("La planilla diaria de CAFCI supera el límite de archivos internos.")
        total = 0
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise MarketDataError("La planilla diaria de CAFCI contiene una ruta interna inválida.")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise MarketDataError("La planilla diaria de CAFCI supera el tamaño descomprimido permitido.")
        if "xl/worksheets/sheet1.xml" not in archive.namelist():
            raise MarketDataError("La planilla diaria de CAFCI no contiene la hoja esperada.")
        try:
            shared = _shared_strings(archive)
            sheet = archive.read("xl/worksheets/sheet1.xml")
        except (zipfile.BadZipFile, KeyError, RuntimeError, OSError, EOFError, zlib.error) as exc:
            raise MarketDataError("La planilla diaria de CAFCI contiene archivos XLSX inválidos.") from exc
    return _read_sheet(sheet, shared, today)


class CAFCIDailyClient:
    def __init__(self, timeout=8, opener=urlopen, clock=monotonic):
        self.timeout, self.opener, self.clock = timeout, opener, clock

    def class_observations(self, refresh=False, today=None):
        now_mono = self.clock()
        with _cache_lock:
            cached = _cache.get(DAILY_URL)
            if not refresh and cached and 0 <= now_mono - cached[0] < CACHE_TTL_SECONDS:
                observations, observed_at = cached[1], cached[2]
                cache_hit = True
            else:
                observations = observed_at = None
                cache_hit = False
        if observations is None:
            request = Request(DAILY_URL, headers={
                "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "User-Agent": "Mozilla/5.0", "Referer": CONSULT_URL,
                "Origin": "https://estadisticas.cafci.org.ar",
            })
            try:
                call = _DAILY_OPENER.open if self.opener is urlopen else self.opener
                with call(request, timeout=self.timeout) as response:
                    final_url = response.geturl() if hasattr(response, "geturl") else DAILY_URL
                    parsed = urlparse(final_url)
                    if (parsed.scheme != "https" or parsed.hostname != "api.pub.cafci.org.ar"
                            or parsed.port not in (None, 443) or parsed.path != "/pb_get"
                            or parsed.query or parsed.fragment):
                        raise MarketDataError("La planilla diaria de CAFCI terminó fuera de su ruta pública permitida.")
                    body = response.read(MAX_COMPRESSED_BYTES + 1)
            except MarketDataError:
                raise
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                raise MarketDataError("No pudimos consultar la planilla diaria de CAFCI.") from exc
            if len(body) > MAX_COMPRESSED_BYTES:
                raise MarketDataError("La planilla diaria de CAFCI supera el tamaño comprimido permitido.")
            observations = parse_daily_xlsx(body, today=today)
            observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with _cache_lock:
                _cache[DAILY_URL] = (now_mono, observations, observed_at)
        today_date = today or datetime.now(timezone.utc).date()
        observations = {key: row for key, row in observations.items()
                        if row["daily_date"] <= today_date and (today_date - row["daily_date"]).days <= MAX_DAILY_AGE_DAYS}
        return {"observations": observations, "source": SOURCE, "url": DAILY_URL,
                "observed_at": observed_at, "cache": cache_hit}
