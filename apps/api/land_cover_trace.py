"""Bounded native EPSG:4326 WorldCover cell tracing along a LineString."""
from __future__ import annotations

import math
from heapq import merge
from collections import OrderedDict
from typing import Any

from apps.api.route_planner import RoutePlanner
from apps.api.static_sources import StaticSources


class LandCoverTrace:
    MAX_TILE_ATTEMPTS = 6
    MAX_CELL_SPANS = 8192
    MAX_WINDOWS = 128
    MAX_WINDOW_PIXELS = 32

    def read(self, adapter: StaticSources, coordinates: list[list[float]], retrieved_at: str, sample_points: list[dict[str, float]] | None = None) -> dict[str, Any]:
        lengths = [RoutePlanner._distance_m(self._point(a), self._point(b)) for a, b in zip(coordinates, coordinates[1:])]
        distance = sum(lengths)
        atoms: list[dict[str, Any]] = []
        grouped: OrderedDict[str, list[int]] = OrderedDict()
        seen = 0.0
        for start, end, length in zip(coordinates, coordinates[1:], lengths):
            if length <= 0:
                continue
            for a, b in self._tile_chunks(start, end):
                midpoint = self._interpolate(start, end, (a + b) / 2)
                try:
                    url = adapter._urls_for_point(midpoint[1], midpoint[0]).get("worldcover")
                except Exception:
                    url = None
                atom = {"start": self._interpolate(start, end, a), "end": self._interpolate(start, end, b),
                        "start_m": seen + length * a, "end_m": seen + length * b, "url": url}
                atoms.append(atom)
                if isinstance(url, str) and url:
                    grouped.setdefault(url, []).append(len(atoms) - 1)
            seen += length
        for index, point in enumerate(sample_points or []):
            coordinate = [point['longitude'], point['latitude']]
            url = adapter._urls_for_point(coordinate[1], coordinate[0]).get('worldcover')
            atoms.append({'start': coordinate, 'end': coordinate, 'start_m': 0.0, 'end_m': 0.0, 'url': url, 'point_index': index})
            if isinstance(url, str) and url:
                grouped.setdefault(url, []).append(len(atoms) - 1)
        failures: list[str] = []
        attempts = 0
        for url, indexes in grouped.items():
            if attempts >= self.MAX_TILE_ATTEMPTS:
                failures.append("tile budget")
                break
            attempts += 1
            try:
                self._classify_url(url, atoms, failures)
            except Exception:
                failures.append("raster read")
        for atom in atoms:
            atom.setdefault("class_code", None)
        segments = self._merge(atoms, distance)
        known = sum(segment["end_m"] - segment["start_m"] for segment in segments if segment["class_code"] is not None)
        unknown = max(0.0, distance - known)
        evidence = [atom["evidence"] for atom in atoms if atom.get("evidence")]
        digest = adapter._store_evidence("esa-worldcover", {"worldcover": list(grouped)[:self.MAX_TILE_ATTEMPTS]}, evidence, retrieved_at) if evidence else None
        status = "available" if known and unknown <= 1e-6 and not failures else ("partial" if known else "unavailable")
        native = evidence[0] if evidence else {}
        source = adapter._source("esa-worldcover", "ESA", "ESA WorldCover 2021 v200", status,
                                 None if status == "available" else "Частина клітин WorldCover недоступна.", retrieved_at, digest,
                                 {"resolution_m": 10, "static_reference_year": 2021, "native_crs": "EPSG:4326",
                                  "native_sample_scope": "intersected raster cells and explicit profile point pixels", "scale_factor": native.get("scale_factor"), "offset": native.get("offset"),
                                  "nodata": native.get("nodata"), "transform": native.get("transform"), "window_limit": [self.MAX_WINDOW_PIXELS, self.MAX_WINDOW_PIXELS]})
        source["extraction_scope"] = "intersected_raster_cells"
        return {"status": status, "evidence_scope": "intersected_raster_cells", "coverage": "centerline_only",
                "reference_year": 2021, "resolution_m": 10, "distance_m": distance, "known_m": known,
                "unknown_m": unknown, "cell_count": sum(1 for atom in atoms if "row" in atom and "point_index" not in atom), "tile_attempts": attempts, "segments": segments,
                "_point_values": [next((atom.get('class_code') for atom in atoms if atom.get('point_index') == index), None) for index in range(len(sample_points or []))],
                "sources": [source], "warnings_uk": ["Лише лінія · не коридор.", "WorldCover — статичне покриття за 2021 рік.", "Класи води й водно-болотних угідь не встановлюють поточне затоплення або допуск транспорту."]}

    def _classify_url(self, url: str, atoms: list[dict[str, Any]], failures: list[str]) -> None:
        import numpy as np
        import rasterio
        from rasterio.windows import Window
        env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.vrt",
               "CPL_VSIL_CURL_CACHE_SIZE": str(2 * 1024 * 1024), "GDAL_HTTP_MAX_RETRY": "0", "GDAL_HTTP_TIMEOUT": "15"}
        with rasterio.Env(**env), rasterio.open(url) as dataset:
            transform = dataset.transform
            if dataset.crs is None or dataset.crs.to_string().upper() != "EPSG:4326" or not all(math.isfinite(value) for value in transform[:6]) or transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
                failures.append("unsupported raster")
                return
            scale = self._finite(dataset.scales[0] if dataset.scales else 1.0)
            offset = self._finite(dataset.offsets[0] if dataset.offsets else 0.0)
            if scale is None or offset is None:
                failures.append("invalid scale")
                return
            selected = [(index, atom) for index, atom in enumerate(atoms) if atom.get("url") == url and "row" not in atom]
            remaining = self.MAX_CELL_SPANS - sum(1 for atom in atoms if "row" in atom)
            replacement = {}
            for index, atom in selected:
                if 'point_index' in atom:
                    if remaining > 0:
                        row, col = dataset.index(*atom['start'])
                        replacement[index] = [{**atom, 'row': row, 'col': col}]
                        remaining -= 1
                    else:
                        replacement[index] = [{**atom, 'class_code': None}]
                    continue
                fragments = []
                for row in self._split_cells(atom, index, dataset.width, dataset.height, transform):
                    if remaining <= 0:
                        failures.append("cell budget")
                        fragments.append({**atom, "start": row["start"], "start_m": row["start_m"], "class_code": None})
                        break
                    fragments.append(row)
                    remaining -= 1
                replacement[index] = fragments
            rebuilt: list[dict[str, Any]] = []
            for original_index, atom in enumerate(atoms):
                if original_index not in replacement:
                    rebuilt.append(atom)
                else:
                    rebuilt.extend(replacement[original_index] or [atom])
            atoms[:] = rebuilt
            # The indexes have moved; identify this tile's fragments by URL.
            cells = [atom for atom in atoms if atom.get("url") == url and "row" in atom and 0 <= atom["row"] < dataset.height and 0 <= atom["col"] < dataset.width]
            blocks: OrderedDict[tuple[int, int], list[dict[str, Any]]] = OrderedDict()
            for atom in cells:
                blocks.setdefault((atom["row"] // self.MAX_WINDOW_PIXELS, atom["col"] // self.MAX_WINDOW_PIXELS), []).append(atom)
            used_windows = sum(1 for atom in atoms if atom.get("window_read"))
            for block_number, ((block_row, block_col), rows) in enumerate(blocks.items()):
                if block_number + used_windows >= self.MAX_WINDOWS:
                    failures.append("window budget")
                    break
                row0, col0 = block_row * self.MAX_WINDOW_PIXELS, block_col * self.MAX_WINDOW_PIXELS
                window = Window(col0, row0, min(self.MAX_WINDOW_PIXELS, dataset.width - col0), min(self.MAX_WINDOW_PIXELS, dataset.height - row0))
                raw = dataset.read(1, window=window, masked=True)
                rows[0]["window_read"] = True
                mask = np.ma.getmaskarray(raw)
                for atom in rows:
                    value = raw.data[atom["row"] - row0, atom["col"] - col0]
                    code = None
                    if not bool(mask[atom["row"] - row0, atom["col"] - col0]) and math.isfinite(float(value)):
                        scaled = float(value) * scale + offset
                        if math.isfinite(scaled) and scaled.is_integer() and int(scaled) in StaticSources.WORLD_COVER_LABELS:
                            code = int(scaled)
                    atom["class_code"] = code
                    atom["evidence"] = {"url": url, "crs": "EPSG:4326", "scale_factor": scale, "offset": offset,
                                        "raw_value": None if bool(mask[atom["row"] - row0, atom["col"] - col0]) else self._json_number(float(value)), "value": code,
                                        "start_m": atom["start_m"], "end_m": atom["end_m"], "start_wgs84": atom["start"], "end_wgs84": atom["end"],
                                        "nodata": self._json_number(dataset.nodata), "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f], "sample": {"row": atom["row"], "column": atom["col"], "window": {"width": int(window.width), "height": int(window.height)}}}

    def _split_cells(self, atom: dict[str, Any], atom_index: int, width: int, height: int, transform):
        x0, y0 = atom["start"]; x1, y1 = atom["end"]
        col0, row0 = (x0 - transform.c) / transform.a, (y0 - transform.f) / transform.e
        col1, row1 = (x1 - transform.c) / transform.a, (y1 - transform.f) / transform.e
        # Merge lazy ordered crossings so a tiny/invalid native pixel size cannot
        # allocate an unbounded boundary set before the caller enforces its cap.
        def crossings(start, end):
            if end == start:
                return
            low, high = math.floor(min(start, end)) + 1, math.floor(max(start, end)) + 1
            boundaries = range(low, high) if end > start else range(high - 1, low - 1, -1)
            for boundary in boundaries:
                t = (boundary - start) / (end - start)
                if 0 < t < 1:
                    yield t
        a = 0.0
        for b in merge(crossings(col0, col1), crossings(row0, row1), [1.0]):
            if b <= a:
                continue
            mid = (a + b) / 2
            row, col = math.floor(row0 + (row1 - row0) * mid), math.floor(col0 + (col1 - col0) * mid)
            item = {**atom, "atom_index": atom_index, "start": self._interpolate(atom["start"], atom["end"], a), "end": self._interpolate(atom["start"], atom["end"], b),
                    "start_m": atom["start_m"] + (atom["end_m"] - atom["start_m"]) * a, "end_m": atom["start_m"] + (atom["end_m"] - atom["start_m"]) * b,
                    "row": row, "col": col}
            if not (0 <= row < height and 0 <= col < width):
                item["class_code"] = None
            yield item
            a = b

    @staticmethod
    def _tile_chunks(start: list[float], end: list[float]):
        values = {0.0, 1.0}
        for axis in (0, 1):
            delta = end[axis] - start[axis]
            if delta:
                for boundary in range(math.floor(min(start[axis], end[axis]) / 3) * 3 + 3, math.ceil(max(start[axis], end[axis]) / 3) * 3, 3):
                    t = (boundary - start[axis]) / delta
                    if 0 < t < 1: values.add(t)
        ordered = sorted(values)
        return zip(ordered, ordered[1:])

    def _merge(self, atoms: list[dict[str, Any]], distance: float) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for atom in atoms:
            if atom["end_m"] <= atom["start_m"]:
                continue
            code = atom.get("class_code")
            geometry = [atom["start"], atom["end"]]
            if output and output[-1]["class_code"] == code and math.isclose(output[-1]["end_m"], atom["start_m"], abs_tol=1e-6):
                output[-1]["end_m"] = atom["end_m"]
                output[-1]["geometry"]["coordinates"].append(atom["end"])
            else:
                output.append({"start_m": atom["start_m"], "end_m": atom["end_m"], "class_code": code,
                               "label": StaticSources.WORLD_COVER_LABELS.get(code) if code is not None else None,
                               "geometry": {"type": "LineString", "coordinates": geometry}})
        return output

    @staticmethod
    def _point(value): return {"longitude": value[0], "latitude": value[1]}
    @staticmethod
    def _interpolate(a, b, t): return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    @staticmethod
    def _finite(value):
        try: value = float(value)
        except (TypeError, ValueError): return None
        return value if math.isfinite(value) else None
    @staticmethod
    def _json_number(value):
        return value if value is None or (isinstance(value, (int, float)) and math.isfinite(value)) else str(value)
