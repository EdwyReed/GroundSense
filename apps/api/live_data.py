"""Open-Meteo ICON Global data client for the public, non-commercial prototype."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, TypeAlias

import httpx

WeatherDTO: TypeAlias = dict[str, Any]


class LiveDataError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class LiveWeatherClient:
    """Fetch and validate the fixed Open-Meteo ICON Global public data slice."""

    URL = "https://api.open-meteo.com/v1/forecast"
    MODEL = "icon_global"
    VARIABLES = (
        "temperature_2m",
        "precipitation",
        "soil_moisture_0_to_1cm",
        "soil_moisture_1_to_3cm",
        "soil_temperature_0cm",
    )
    RESEARCH_VARIABLES = (
        "et0_fao_evapotranspiration",
        "soil_moisture_3_to_9cm",
        "snow_depth",
        "snowfall",
    )
    UNITS = {
        "temperature_2m": "°C",
        "precipitation": "mm",
        "soil_moisture_0_to_1cm": "m³/m³",
        "soil_moisture_1_to_3cm": "m³/m³",
        "soil_temperature_0cm": "°C",
        "et0_fao_evapotranspiration": "mm",
        "soil_moisture_3_to_9cm": "m³/m³",
        "snow_depth": "m",
        "snowfall": "cm",
    }
    _HEX = re.compile(r"^[0-9a-f]{64}$")

    def __init__(
        self,
        cache_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: float = 300.0,
        cache_max_entries: int = 64,
    ) -> None:
        if timeout_seconds <= 0 or cache_ttl_seconds < 0 or cache_max_entries < 1:
            raise ValueError("Некоректні параметри клієнта живих даних.")
        self.cache_dir = Path(cache_dir)
        self._snapshots = self.cache_dir / "snapshots"
        self._entries = self.cache_dir / "entries"
        self._section_entries = self.cache_dir / "section-entries"
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_max_entries = cache_max_entries

    def snapshot_path(self, hex_digest: str) -> Path:
        if not self._HEX.fullmatch(hex_digest):
            raise ValueError("Digest snapshot має бути SHA-256 у шістнадцятковому форматі.")
        return self._snapshots / f"{hex_digest}.json"

    def forecast(self, latitude: float, longitude: float, assessment_date: str | date | None = None) -> WeatherDTO:
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        now = self._now()
        selected = self._assessment_date(assessment_date, now.date())
        key = hashlib.sha256(f"live-weather-v2|{lat:.8f}|{lon:.8f}|{selected.isoformat()}".encode()).hexdigest()
        cached = self._load_fresh_entry(key, now)
        if cached is not None:
            raw, request_url, retrieved_at = cached
            return self._dto(raw, lat, lon, selected, request_url, retrieved_at, cached=True)

        params = {
            "latitude": self._format_coordinate(lat),
            "longitude": self._format_coordinate(lon),
            "hourly": ",".join((*self.VARIABLES, *self.RESEARCH_VARIABLES)),
            "models": self.MODEL,
            "forecast_days": "7",
            "timezone": "UTC",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds, follow_redirects=False) as client:
                response = client.get(self.URL, params=params, headers={"Accept": "application/json"})
        except httpx.TimeoutException as exc:
            raise LiveDataError(503, "Час очікування Open-Meteo вичерпано.") from exc
        except httpx.HTTPError as exc:
            raise LiveDataError(503, "Open-Meteo тимчасово недоступний.") from exc
        if response.is_error or response.is_redirect:
            raise LiveDataError(502, f"Open-Meteo повернув HTTP {response.status_code}.")
        raw = response.content
        request_url = str(response.request.url)
        dto = self._dto(raw, lat, lon, selected, request_url, now, cached=False)
        digest = dto["source"]["content_sha256"].removeprefix("sha256:")
        self._store(key, raw, digest, request_url, now)
        return dto

    def forecast_for_section(self, latitude: float, longitude: float, assessment_date: str | date | None = None) -> WeatherDTO:
        """Fetch one provider response containing history and forecast data."""
        lat = self._coordinate(latitude, "latitude", -90, 90)
        lon = self._coordinate(longitude, "longitude", -180, 180)
        now = self._now()
        selected = self._assessment_date(assessment_date, now.date())
        key = hashlib.sha256(f"live-weather-section-v10|{lat:.8f}|{lon:.8f}|{selected.isoformat()}".encode()).hexdigest()
        cached = self._load_fresh_entry(key, now, entries=self._section_entries)
        if cached is not None:
            raw, request_url, retrieved_at = cached
            return self._dto(raw, lat, lon, selected, request_url, retrieved_at, cached=True, antecedent=True, max_rows=400)
        params = {"latitude": self._format_coordinate(lat), "longitude": self._format_coordinate(lon), "hourly": ",".join((*self.VARIABLES, *self.RESEARCH_VARIABLES)), "models": self.MODEL, "past_days": "7", "forecast_days": "7", "timezone": "UTC"}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds, follow_redirects=False) as client:
                with client.stream("GET", self.URL, params=params, headers={"Accept": "application/json"}) as response:
                    if response.is_error or response.is_redirect:
                        raise LiveDataError(502, f"Open-Meteo повернув HTTP {response.status_code}.")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes(chunk_size=8192):
                        size += len(chunk)
                        if size > 1024 * 1024:
                            raise LiveDataError(502, "Open-Meteo повернув надто великий погодний ряд.")
                        chunks.append(chunk)
                    raw, request_url = b"".join(chunks), str(response.request.url)
        except LiveDataError:
            raise
        except httpx.TimeoutException as exc:
            raise LiveDataError(503, "Час очікування Open-Meteo вичерпано.") from exc
        except httpx.HTTPError as exc:
            raise LiveDataError(503, "Open-Meteo тимчасово недоступний.") from exc
        dto = self._dto(raw, lat, lon, selected, request_url, now, cached=False, antecedent=True, max_rows=400)
        self._store(key, raw, dto["source"]["content_sha256"].removeprefix("sha256:"), request_url, now, entries=self._section_entries)
        return dto

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock має повертати datetime.")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _assessment_date(self, value: str | date | None, today: date) -> date:
        if value is None:
            selected = today
        elif isinstance(value, datetime):
            raise LiveDataError(422, "assessment_date має бути датою YYYY-MM-DD.")
        elif isinstance(value, date):
            selected = value
        elif isinstance(value, str):
            try:
                selected = date.fromisoformat(value)
            except ValueError as exc:
                raise LiveDataError(422, "assessment_date має бути датою YYYY-MM-DD.") from exc
        else:
            raise LiveDataError(422, "assessment_date має бути датою YYYY-MM-DD.")
        if not today <= selected < today + timedelta(days=7):
            raise LiveDataError(422, "assessment_date поза доступним семиденним горизонтом ICON Global.")
        return selected

    @staticmethod
    def _coordinate(value: Any, field: str, lower: float, upper: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)) or not lower <= float(value) <= upper:
            raise LiveDataError(422, f"{field} має бути скінченним числом у допустимих межах.")
        return float(value)

    @staticmethod
    def _format_coordinate(value: float) -> str:
        return format(value, ".8f").rstrip("0").rstrip(".")

    def _entry_path(self, key: str, entries: Path | None = None) -> Path:
        return (entries or self._entries) / f"{key}.json"

    def _load_fresh_entry(self, key: str, now: datetime, *, entries: Path | None = None) -> tuple[bytes, str, datetime] | None:
        path = self._entry_path(key, entries)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(entry["saved_at"])
            digest = entry["digest"]
            request_url = entry["request_url"]
            if not isinstance(request_url, str) or not self._HEX.fullmatch(digest):
                return None
            saved_at = saved_at.replace(tzinfo=UTC) if saved_at.tzinfo is None else saved_at.astimezone(UTC)
            if not timedelta(0) <= now - saved_at <= timedelta(seconds=self._cache_ttl_seconds):
                return None
            raw = self.snapshot_path(digest).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                return None
            return raw, request_url, saved_at
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _store(self, key: str, raw: bytes, digest: str, request_url: str, now: datetime, *, entries: Path | None = None) -> None:
        entries = entries or self._entries
        self._snapshots.mkdir(parents=True, exist_ok=True)
        entries.mkdir(parents=True, exist_ok=True)
        snapshot = self.snapshot_path(digest)
        if not snapshot.exists():
            self._atomic_write(snapshot, raw)
        entry = {"digest": digest, "request_url": request_url, "saved_at": now.isoformat()}
        self._atomic_write(self._entry_path(key, entries), json.dumps(entry, separators=(",", ":")).encode())
        self._evict_entries(entries)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _evict_entries(self, entries_dir: Path | None = None) -> None:
        entries_dir = entries_dir or self._entries
        entries_with_times = []
        for item in entries_dir.glob('*.json'):
            try:
                entries_with_times.append((item.stat().st_mtime, item))
            except FileNotFoundError:
                continue
        entries = [item for _, item in sorted(entries_with_times, reverse=True)]
        for path in entries[self._cache_max_entries:]:
            try:
                path.unlink()
            except OSError:
                continue
        # Cache indexes may expire; immutable source evidence referenced by workspace
        # audit rows must not be destroyed by cache eviction.

    def _dto(self, raw: bytes, latitude: float, longitude: float, selected: date, request_url: str, now: datetime, *, cached: bool, antecedent: bool = False, max_rows: int | None = None) -> WeatherDTO:
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LiveDataError(502, "Open-Meteo повернув некоректний JSON.") from exc
        if not isinstance(payload, dict) or payload.get("error") is True:
            raise LiveDataError(502, "Open-Meteo не надав погодний ряд.")
        if payload.get('utc_offset_seconds', 0) != 0:
            raise LiveDataError(502, 'Open-Meteo повернув неочікувану часову шкалу.')
        units = payload.get("hourly_units")
        hourly = payload.get("hourly")
        if not isinstance(units, dict) or units.get('time') != 'iso8601' or not isinstance(hourly, dict) or any(units.get(name) != self.UNITS[name] for name in self.VARIABLES):
            raise LiveDataError(502, "Open-Meteo повернув неочікувану схему або одиниці.")
        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise LiveDataError(502, "Open-Meteo не повернув часовий ряд.")
        if max_rows is not None and len(times) > max_rows:
            raise LiveDataError(502, "Open-Meteo повернув надто довгий погодний ряд.")
        values: dict[str, list[Any]] = {}
        for name in self.VARIABLES:
            column = hourly.get(name)
            if not isinstance(column, list) or len(column) != len(times):
                raise LiveDataError(502, "Open-Meteo повернув неповний погодний ряд.")
            values[name] = column
        research_values, rejected_research = self._research_columns(units, hourly, len(times))
        grid_lat = self._provider_number(payload.get("latitude"), "latitude")
        grid_lon = self._provider_number(payload.get("longitude"), "longitude")
        elevation = payload.get("elevation")
        if elevation is not None:
            elevation = self._provider_number(elevation, "elevation")
        series: list[dict[str, Any]] = []
        research_series: list[dict[str, Any]] = []
        missing: set[str] = set()
        research_missing: set[str] = set(rejected_research)
        previous: datetime | None = None
        research_start = datetime.combine(selected, datetime.min.time(), tzinfo=UTC)
        research_end = research_start + timedelta(hours=72)
        antecedent_start = research_start - timedelta(days=7)
        antecedent_series: list[dict[str, Any]] = []
        for index, timestamp in enumerate(times):
            parsed = self._time(timestamp)
            if antecedent and (parsed.minute or parsed.second or parsed.microsecond):
                raise LiveDataError(502, 'Open-Meteo повернув неочікуваний годинний крок.')
            if previous is not None and parsed <= previous:
                raise LiveDataError(502, 'Часовий ряд Open-Meteo не є строго зростаючим.')
            previous = parsed
            if antecedent and antecedent_start <= parsed <= research_start:
                value = values["precipitation"][index]
                antecedent_series.append({"time": parsed.isoformat().replace("+00:00", "Z"), "precipitation": None if value is None else self._provider_number(value, "precipitation"), "precipitation_interval_start": (parsed - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "precipitation_interval_end": parsed.isoformat().replace("+00:00", "Z")})
            if parsed.date() == selected:
                item: dict[str, Any] = {"time": parsed.isoformat().replace("+00:00", "Z")}
                for name in self.VARIABLES:
                    value = values[name][index]
                    if value is None:
                        missing.add(name)
                        item[name] = None
                    else:
                        item[name] = self._provider_number(value, name)
                item["precipitation_interval_start"] = (parsed - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
                item["precipitation_interval_end"] = item["time"]
                series.append(item)
            if research_start <= parsed <= research_end:
                research_item: dict[str, Any] = {"time": parsed.isoformat().replace("+00:00", "Z")}
                for name in self.VARIABLES:
                    value = values[name][index]
                    research_item[name] = None if value is None else self._provider_number(value, name)
                    if value is None:
                        research_missing.add(name)
                for name in self.RESEARCH_VARIABLES:
                    value = research_values[name][index]
                    research_item[name] = value
                    if value is None:
                        research_missing.add(name)
                interval_start = (parsed - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
                research_item["precipitation_interval_start"] = interval_start
                research_item["precipitation_interval_end"] = research_item["time"]
                research_item["et0_fao_evapotranspiration_interval_start"] = interval_start
                research_item["et0_fao_evapotranspiration_interval_end"] = research_item["time"]
                research_series.append(research_item)
        if not series:
            raise LiveDataError(502, "Open-Meteo не повернув ряд для обраної UTC-дати.")
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "mode": "live", "synthetic": False, "assessment_date": selected.isoformat(),
            "requested_point": {"latitude": latitude, "longitude": longitude},
            "grid_point": {"latitude": grid_lat, "longitude": grid_lon, "elevation_m": elevation},
            "source": {
                "id": "open-meteo-icon-global", "provider": "Open-Meteo", "product": "DWD ICON Global via Open-Meteo",
                "model": self.MODEL, "request_url": request_url, "retrieved_at": now.isoformat().replace("+00:00", "Z"),
                "issue_time": None, "license": "CC BY 4.0", "service_usage": "non_commercial_prototype",
                "attribution_url": "https://open-meteo.com/", "content_sha256": f"sha256:{digest}", "cached": cached,
            },
            "units": dict(self.UNITS), "series": series, "research_series": research_series,
            **({"antecedent_series": antecedent_series} if antecedent else {}),
            "qc": {"status": "partial" if missing else "available", "missing_variables": sorted(missing), "is_observation": False, "spatial_support": "model_grid_not_road"},
            "research_qc": {"status": "partial" if research_missing else "available", "missing_variables": sorted(research_missing)},
            "mobility": {"kind": "unavailable", "reason": "Публічний модельний погодний ряд не містить даних про прохідність."},
        }

    @staticmethod
    def _provider_number(value: Any, name: str) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise LiveDataError(502, f"Open-Meteo повернув некоректне числове значення {name}.")
        return float(value)

    def _research_columns(self, units: dict[str, Any], hourly: dict[str, Any], length: int) -> tuple[dict[str, list[float | None]], set[str]]:
        values: dict[str, list[float | None]] = {}
        rejected: set[str] = set()
        for name in self.RESEARCH_VARIABLES:
            column = hourly.get(name)
            if units.get(name) != self.UNITS[name] or not isinstance(column, list) or len(column) != length:
                values[name] = [None] * length
                rejected.add(name)
                continue
            parsed: list[float | None] = []
            try:
                for value in column:
                    parsed.append(None if value is None else self._provider_number(value, name))
            except LiveDataError:
                values[name] = [None] * length
                rejected.add(name)
                continue
            values[name] = parsed
        return values, rejected

    @staticmethod
    def _time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise LiveDataError(502, "Open-Meteo повернув некоректний час.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LiveDataError(502, "Open-Meteo повернув некоректний час.") from exc
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
