"""Bounded local point reads of the official FAO/IIASA HWSD v2 archives."""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx


class HWSDSources:
    """Read HWSD v2 map-unit pixels without expanding the global BIL archive.

    The archives are public downloads, but this adapter deliberately makes no claim
    that their dataset-specific commercial reuse rights have been established.
    """

    RASTER_ZIP_URL = "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/HWSD/HWSD2_RASTER.zip"
    DB_ZIP_URL = "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/HWSD/HWSD2_DB.zip"
    SOURCE_KEYS = ("id", "name", "product", "version", "status", "qc", "note", "retrieved_at", "observed_at", "content_sha256", "data")
    _MAX_RASTER_BYTES = 30 * 1024 * 1024
    _MAX_DB_BYTES = 15 * 1024 * 1024
    _MAX_MDB_BYTES = 128 * 1024 * 1024
    _PARSER_TIMEOUT_SECONDS = 10
    _PARSER_OUTPUT_BYTES = 128 * 1024
    _ROW_CAP = 16

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.cache_dir = Path(cache_dir)
        self.raw_dir = self.cache_dir / "raw"
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self._archive_lock = threading.Lock()

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        lat = self._coordinate(latitude, -90, 90, "latitude")
        lon = self._coordinate(longitude, -180, 180, "longitude")
        selected = self._date(assessment_date)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        context, source = self._read(lat, lon, selected, now)
        return deepcopy({"context": {"hwsd_v2": context}, "sources": [source]})

    def _read(self, latitude: float, longitude: float, selected: date, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
        blank = {"map_unit_id": None, "attributes": None, "reference": "HWSD v2.0 static natural-soil map units; not a road or mobility observation."}
        try:
            raster_path, raster_digest = self._archive("HWSD2_RASTER.zip", self.RASTER_ZIP_URL, self._MAX_RASTER_BYTES)
            sampled = self._sample_raster(raster_path, latitude, longitude)
            db_state = self._database_state()
            if sampled is None:
                return blank, self._source("unavailable", "unavailable", "Точка поза покриттям або має NoData в офіційному HWSD v2 raster; синтетичний map-unit не підставлено. Дані описують природний ґрунт, не дорогу чи мобільність; комерційні права на датасет не встановлені.", now, raster_digest, {"selected_date": selected.isoformat(), "extraction": "rasterio_vsizip_bil_point", "database": db_state})
            map_unit, metadata = sampled
            attributes, db_state = self._attributes(map_unit, db_state)
            status = "available" if attributes is not None else "partial"
            qc = "available" if attributes is not None else "partial"
            context = {**blank, "map_unit_id": map_unit, "attributes": attributes, "raster": metadata}
            note = "Зчитано фактичну картографічну одиницю з офіційного HWSD v2 BIL без розгортання глобального растра. Це статичний природно-ґрунтовий контекст, не характеристика дороги чи твердження про мобільність. Комерційні права на датасет не встановлені."
            if attributes is None:
                note += " Атрибути MDB не отримані: " + str(db_state.get("note", "потрібен доступний parser"))
            return context, self._source(status, qc, note, now, raster_digest, {"selected_date": selected.isoformat(), "extraction": "rasterio_vsizip_bil_point", "point": context, "database": db_state})
        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
            return blank, self._source("unavailable", "unavailable", f"Точкове читання HWSD v2 не виконано: {type(exc).__name__}. Дані не замінено іншим ґрунтовим продуктом; комерційні права на датасет не встановлені.", now, None, {"selected_date": selected.isoformat(), "extraction": "none", "database": {"status": "not_attempted"}})

    def _archive(self, filename: str, url: str, maximum: int) -> tuple[Path, str]:
        with self._archive_lock:
            return self._archive_locked(filename,url,maximum)

    def _archive_locked(self, filename: str, url: str, maximum: int) -> tuple[Path, str]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / filename
        digest_path = self.raw_dir / f"{filename}.sha256"
        if path.is_file() and digest_path.is_file():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest_path.read_text(encoding="ascii").strip() == actual:
                return path, actual
        with httpx.Client(transport=self.transport, timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Accept": "application/zip"}) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length is not None and (not length.isdigit() or int(length) > maximum):
                    raise ValueError("archive exceeds bounded download size")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError("archive exceeds bounded download size")
                    chunks.append(chunk)
        payload = b"".join(chunks)
        digest = hashlib.sha256(payload).hexdigest()
        temporary = path.with_name(f'.{path.name}.{time.time_ns()}.tmp')
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        digest_path.write_text(digest, encoding="ascii")
        return path, digest

    def _sample_raster(self, archive: Path, latitude: float, longitude: float) -> tuple[int, dict[str, Any]] | None:
        import rasterio
        from rasterio.transform import rowcol
        from rasterio.windows import Window
        import zipfile

        with zipfile.ZipFile(archive) as bundle:
            bil_names = [name for name in bundle.namelist() if name.lower().endswith(".bil")]
        if len(bil_names) != 1:
            raise ValueError("expected one BIL in raster archive")
        vsi_path = f"/vsizip/{archive.resolve()}/{bil_names[0]}"
        with rasterio.open(vsi_path) as dataset:
            row, col = rowcol(dataset.transform, longitude, latitude)
            pixel_width = abs(float(dataset.transform.a))
            pixel_height = abs(float(dataset.transform.e))
            crs = dataset.crs.to_string() if dataset.crs else None
            native_grid = (
                crs in {"OGC:CRS84", "EPSG:4326"}
                and dataset.width == 43_200
                and dataset.height == 21_600
                and dataset.transform.a > 0 and dataset.transform.e < 0
                and dataset.transform.b == 0 and dataset.transform.d == 0
                and math.isclose(pixel_width, 1 / 120, abs_tol=1e-10)
                and math.isclose(pixel_height, 1 / 120, abs_tol=1e-10)
            )
            metadata = {"dtype": dataset.dtypes[0], "crs": crs, "nodata": dataset.nodata, "width": dataset.width, "height": dataset.height, "driver": dataset.driver, "row": int(row), "column": int(col), "pixel_width_degrees": pixel_width, "pixel_height_degrees": pixel_height, "resolution_arc_seconds": 30 if native_grid else None}
            if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                return None
            value = dataset.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
            if bool(getattr(value, "mask", False)):
                return None
            return int(value), metadata

    def _database_state(self) -> dict[str, Any]:
        # Availability is assessed lazily so map-unit-only reads remain useful.
        try:
            path, digest = self._archive("HWSD2_DB.zip", self.DB_ZIP_URL, self._MAX_DB_BYTES)
            with zipfile.ZipFile(path) as archive:
                members = [{"name": item.filename, "compressed_bytes": item.compress_size, "uncompressed_bytes": item.file_size} for item in archive.infolist()]
            return {"status": "cached", "content_sha256": f"sha256:{digest}", "members": members}
        except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
            return {"status": "unavailable", "note": f"MDB archive unavailable: {type(exc).__name__}"}

    def _attributes(self, map_unit: int, state: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if state.get("status") != "cached":
            return None, state
        try:
            with self._archive_lock:
                mdb = self._extract_mdb_locked()
            tools = self._mdb_tools()
            tables = self._run_mdb(tools["mdb-tables"], "-1", str(mdb)).splitlines()
            table = next((item.strip() for item in tables if item.strip().lower() == "hwsd2_smu"), None)
            if table is None:
                raise RuntimeError("HWSD2_SMU table was not found")
            schema = self._run_mdb(tools["mdb-schema"], "-T", table, str(mdb), "postgres")
            columns = re.findall(r'"([^"\r\n]+)"\s+(?:SERIAL|INTEGER|REAL|VARCHAR)', schema, flags=re.IGNORECASE)
            map_column = next((column for column in columns if column.lower() == "hwsd2_smu_id"), None)
            if map_column is None:
                raise RuntimeError("HWSD2_SMU identifier column was not found")
            query = f"SELECT * FROM [{table}] WHERE [{map_column}] = {map_unit};\n"
            output = self._run_mdb(tools["mdb-sql"], "-d", "|", "-P", "-F", str(mdb), input_text=query)
            lines = [line for line in output.splitlines() if line]
            if len(lines) < 2:
                raise RuntimeError("map unit returned no rows")
            headers = lines[0].split("|")
            returned_map_column = next((header for header in headers if header.lower() == map_column.lower()), None)
            if returned_map_column is None:
                raise RuntimeError("parser output omitted map-unit column")
            rows = [dict(zip(headers, line.split("|"), strict=True)) for line in lines[1:self._ROW_CAP + 1]]
            if not rows or any(row.get(returned_map_column) != str(map_unit) for row in rows):
                raise RuntimeError("parser returned unmatched map-unit row")
            state = dict(state)
            state.update({"status": "available", "parser": "mdbtools", "table": table, "map_unit_column": map_column, "row_count": len(rows), "row_cap": self._ROW_CAP})
            return {"rows": rows}, state
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, zipfile.BadZipFile) as exc:
            state = dict(state)
            state.update({"status": "unavailable", "note": f"MDB attribute parser failed: {type(exc).__name__}; rows were not substituted."})
            return None, state

    def _extract_mdb_locked(self) -> Path:
        archive = self.raw_dir / "HWSD2_DB.zip"
        destination = self.raw_dir / "HWSD2.mdb"
        with zipfile.ZipFile(archive) as bundle:
            members = [item for item in bundle.infolist() if not item.is_dir()]
            if len(members) != 1 or Path(members[0].filename).name != "HWSD2.mdb" or members[0].file_size > self._MAX_MDB_BYTES:
                raise ValueError("expected one bounded HWSD2.mdb member")
            expected_digest = hashlib.sha256()
            with bundle.open(members[0]) as source:
                while chunk := source.read(1024 * 1024):
                    expected_digest.update(chunk)
            if destination.is_file() and destination.stat().st_size == members[0].file_size:
                actual_digest = hashlib.sha256()
                with destination.open("rb") as existing:
                    while chunk := existing.read(1024 * 1024):
                        actual_digest.update(chunk)
                if actual_digest.digest() == expected_digest.digest():
                    return destination
            temporary = destination.with_name(f".{destination.name}.{time.time_ns()}.tmp")
            try:
                with bundle.open(members[0]) as source, temporary.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                if temporary.stat().st_size != members[0].file_size:
                    raise ValueError("MDB extraction size mismatch")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        return destination

    @staticmethod
    def _run_mdb(executable: Path, *arguments: str, input_text: str | None = None) -> str:
        environment = os.environ.copy()
        library_dir = executable.parent.parent / "lib" / "x86_64-linux-gnu"
        if library_dir.is_dir():
            environment["LD_LIBRARY_PATH"] = str(library_dir) + (":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
        completed = subprocess.run([str(executable), *arguments], input=input_text, text=True, capture_output=True, timeout=HWSDSources._PARSER_TIMEOUT_SECONDS, env=environment, check=True)
        if max(len(completed.stdout.encode()), len(completed.stderr.encode())) > HWSDSources._PARSER_OUTPUT_BYTES:
            raise RuntimeError("MDB parser output exceeded cap")
        return completed.stdout

    @staticmethod
    def _mdb_tools() -> dict[str, Path]:
        root = Path(__file__).resolve().parents[2] / ".venv" / "runtime" / "mdbtools" / "usr" / "bin"
        tools: dict[str, Path] = {}
        for name in ("mdb-tables", "mdb-schema", "mdb-sql"):
            candidate = root / name
            located = candidate if candidate.is_file() else (Path(found) if (found := shutil.which(name)) else None)
            if located is None:
                raise RuntimeError("mdbtools parser is unavailable")
            tools[name] = located
        return tools

    @classmethod
    def _source(cls, status: str, qc: str, note: str, retrieved_at: str, digest: str | None, data: dict[str, Any]) -> dict[str, Any]:
        result = {"id": "hwsd-v2", "name": "FAO / IIASA", "product": "Harmonized World Soil Database", "version": "v2.0", "status": status, "qc": qc, "note": note, "retrieved_at": retrieved_at, "observed_at": None, "content_sha256": f"sha256:{digest}" if digest else None, "data": {**data,'temporal_scope':'static_reference','commercial_reuse':'not_established'}}
        assert tuple(result) == cls.SOURCE_KEYS
        return result

    @staticmethod
    def _finite(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(float(value))

    @classmethod
    def _coordinate(cls, value: Any, lower: float, upper: float, name: str) -> float:
        if not cls._finite(value) or not lower <= float(value) <= upper:
            raise ValueError(f"{name} must be finite and within WGS84 bounds")
        return float(value)

    @staticmethod
    def _date(value: str) -> date:
        if not isinstance(value, str):
            raise ValueError("assessment_date must be YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("assessment_date must be YYYY-MM-DD") from exc
