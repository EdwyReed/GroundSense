"""Network-free HWSD v2 reference soil type reads for one selected point."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import threading
import zipfile
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from apps.api.hwsd_sources import HWSDSources


class SoilTypeSource:
    """Adapt verified native HWSD cache assets without invoking archive downloads."""

    TTL_SECONDS = 300
    MAX_CACHE_ENTRIES = 64
    _CODE = re.compile(r"^[A-Za-z0-9]{1,16}$")

    def __init__(self, cache_dir: Path, *, adapter_lookup: Callable[[], Any], monotonic_clock=monotonic) -> None:
        self.cache_dir = Path(cache_dir)
        self.adapter_lookup = adapter_lookup
        self.monotonic_clock = monotonic_clock
        self._cache: OrderedDict[tuple[int, float, float], tuple[float, Any, tuple[dict[str, Any], dict[str, Any]]]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def read_point(self, latitude: float, longitude: float) -> tuple[dict[str, Any], dict[str, Any]]:
        latitude = self._coordinate(latitude, -90, 90)
        longitude = self._coordinate(longitude, -180, 180)
        # The two admitted contexts share one bounded offline reader. Hold the
        # lock through a cold read so identical points cannot duplicate native I/O.
        with self._cache_lock:
            adapter = self.adapter_lookup()
            key = (id(adapter), latitude, longitude)
            now_monotonic = self.monotonic_clock()
            cached = self._cache.get(key)
            if cached and cached[1] is adapter and now_monotonic - cached[0] <= self.TTL_SECONDS:
                self._cache.move_to_end(key)
                return deepcopy(cached[2])
            self._cache.pop(key, None)
            result = self._read(adapter, latitude, longitude)
            if result[0]["status"] == "available":
                # Keep the adapter alive: an integer id alone can be recycled.
                self._cache[key] = (now_monotonic, adapter, deepcopy(result))
                self._cache.move_to_end(key)
                while len(self._cache) > self.MAX_CACHE_ENTRIES:
                    self._cache.popitem(last=False)
            return deepcopy(result)

    def _read(self, adapter: Any, latitude: float, longitude: float) -> tuple[dict[str, Any], dict[str, Any]]:
        retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        blank = self._dto(latitude, longitude)
        try:
            if not isinstance(adapter, HWSDSources):
                raise RuntimeError("native HWSD adapter is unavailable")
            raster_digest, db_digest, mdb_digest = self._cached_archives(adapter)
            sampled = adapter._sample_raster(adapter.raw_dir / "HWSD2_RASTER.zip", latitude, longitude)
            if sampled is None:
                return blank, self._source("unavailable", retrieved_at, None, {"commercial_reuse": "not_established"})
            map_unit, raster = sampled
            if not self._native_raster(raster) or not isinstance(map_unit, int) or map_unit <= 0:
                return blank, self._source("unavailable", retrieved_at, None, {"commercial_reuse": "not_established"})
            state = {"status": "cached", "content_sha256": f"sha256:{db_digest}", "members": [{"name": "HWSD2.mdb"}]}
            attributes, state = adapter._attributes(map_unit, state)
            soil = self._dto(latitude, longitude, map_unit=map_unit, status="partial")
            soil["resolution_arc_seconds"] = 30
            if attributes is None or state.get("status") != "available":
                return soil, self._source("partial", retrieved_at, None, self._provenance(raster_digest, db_digest, mdb_digest))
            row = self._single_row(attributes, map_unit)
            code = self._value(row, "WRB4")
            share = self._share(self._value(row, "SHARE"))
            if code is None or share is None:
                return soil, self._source("partial", retrieved_at, None, self._provenance(raster_digest, db_digest, mdb_digest))
            name = self._wrb_name(adapter, code)
            if name is None:
                return soil, self._source("partial", retrieved_at, None, self._provenance(raster_digest, db_digest, mdb_digest))
            soil.update(status="available", wrb_code=code, wrb_name=name, share_percent=share, resolution_arc_seconds=30)
            evidence = {"requested_point": soil["requested_point"], "cell": {"row": raster["row"], "column": raster["column"], "map_unit_id": map_unit}, "wrb": {"code": code, "name": name}, "share_percent": share, "raster_zip_sha256": raster_digest, "db_zip_sha256": db_digest, "mdb_sha256": mdb_digest}
            digest = self._save_evidence(evidence)
            return soil, self._source("available", retrieved_at, digest, self._provenance(raster_digest, db_digest, mdb_digest))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile):
            return blank, self._source("unavailable", retrieved_at, None, {"commercial_reuse": "not_established"})

    @staticmethod
    def _dto(latitude: float, longitude: float, *, map_unit: int | None = None, status: str = "unavailable") -> dict[str, Any]:
        return {"status": status, "basis": "hwsd_v2_smu_dominant_soil", "requested_point": {"latitude": latitude, "longitude": longitude}, "map_unit_id": map_unit, "wrb_code": None, "wrb_name": None, "share_percent": None, "resolution_arc_seconds": None, "temporal_scope": "static_reference", "classification_system": "WRB 2022", "spatial_scope": "soil_mapping_unit"}

    @classmethod
    def _cached_archives(cls, adapter: HWSDSources) -> tuple[str, str, str]:
        raster = cls._verified_file(adapter.raw_dir / "HWSD2_RASTER.zip", adapter._MAX_RASTER_BYTES)
        database = cls._verified_file(adapter.raw_dir / "HWSD2_DB.zip", adapter._MAX_DB_BYTES)
        with zipfile.ZipFile(adapter.raw_dir / "HWSD2_DB.zip") as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or Path(members[0].filename).name != "HWSD2.mdb" or members[0].file_size > adapter._MAX_MDB_BYTES:
                raise ValueError("invalid cached DB archive")
            zipped_mdb = cls._digest_stream(archive.open(members[0]))
        mdb = cls._digest_file(adapter.raw_dir / "HWSD2.mdb", adapter._MAX_MDB_BYTES)
        if mdb != zipped_mdb:
            raise ValueError("cached MDB does not match cached DB archive")
        return raster, database, mdb

    @classmethod
    def _verified_file(cls, path: Path, maximum: int) -> str:
        digest = cls._digest_file(path, maximum)
        sidecar = path.with_name(path.name + ".sha256")
        if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != digest:
            raise ValueError("cached archive digest mismatch")
        return digest

    @staticmethod
    def _digest_stream(stream: Any) -> str:
        hasher = hashlib.sha256()
        with stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _digest_file(path: Path, maximum: int) -> str:
        if not path.is_file() or path.stat().st_size > maximum:
            raise ValueError("cached asset unavailable or exceeds cap")
        with path.open("rb") as stream:
            return SoilTypeSource._digest_stream(stream)

    @staticmethod
    def _native_raster(metadata: dict[str, Any]) -> bool:
        return metadata.get("crs") in {"OGC:CRS84", "EPSG:4326"} and metadata.get("width") == 43_200 and metadata.get("height") == 21_600 and metadata.get("resolution_arc_seconds") == 30

    @classmethod
    def _single_row(cls, attributes: dict[str, Any], map_unit: int) -> dict[str, str]:
        rows = attributes.get("rows")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError("expected exactly one matching map-unit row")
        row = rows[0]
        identity = cls._value(row, "HWSD2_SMU_ID")
        if identity != str(map_unit):
            raise ValueError("mismatched map-unit row")
        return row

    @staticmethod
    def _value(row: dict[str, Any], name: str) -> str | None:
        value = next((item for key, item in row.items() if key.lower() == name.lower()), None)
        return value if isinstance(value, str) else None

    @classmethod
    def _share(cls, value: str | None) -> float | None:
        try:
            result = float(value) if value is not None else float("nan")
        except ValueError:
            return None
        return result if math.isfinite(result) and 0 < result <= 100 else None

    def _wrb_name(self, adapter: HWSDSources, code: str) -> str | None:
        if not self._CODE.fullmatch(code):
            return None
        tools = adapter._mdb_tools()
        mdb = adapter.raw_dir / "HWSD2.mdb"
        output = adapter._run_mdb(tools["mdb-sql"], "-d", "|", "-P", "-F", str(mdb), input_text=f"SELECT * FROM [D_WRB4] WHERE [CODE] = '{code}';\n")
        lines = [line for line in output.splitlines() if line]
        if len(lines) != 2:
            return None
        headers, values = lines[0].split("|"), lines[1].split("|")
        if len(headers) != len(values):
            return None
        row = dict(zip(headers, values, strict=True))
        literal = self._value(row, "CODE")
        name = self._value(row, "VALUE")
        return name if literal == code and name and len(name) <= 128 else None

    def _save_evidence(self, evidence: dict[str, Any]) -> str:
        payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.cache_dir / "soil-type-evidence" / f"{digest}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{digest}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    @staticmethod
    def _provenance(raster: str, database: str, mdb: str) -> dict[str, Any]:
        return {"raster_zip_sha256": f"sha256:{raster}", "db_zip_sha256": f"sha256:{database}", "mdb_sha256": f"sha256:{mdb}", "commercial_reuse": "not_established"}

    @staticmethod
    def _source(status: str, retrieved_at: str, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": "hwsd-v2", "product": "Harmonized World Soil Database v2.0", "status": status, "qc": status, "retrieved_at": retrieved_at, "observed_at": None, "content_sha256": f"sha256:{digest}" if digest else None, "data": data}

    @staticmethod
    def _coordinate(value: Any, lower: float, upper: float) -> float:
        if type(value) not in (int, float) or not math.isfinite(float(value)) or not lower <= float(value) <= upper:
            raise ValueError("coordinates must be finite WGS84 values")
        return float(value)
