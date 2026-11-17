"""Small, cached OpenStreetMap extracts; never road condition or route approval."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from apps.api.remote_sources import RemoteSources


class OSMSources:
    ENDPOINT = "https://overpass-api.de/api/interpreter"
    MAP_ENDPOINT = "https://api.openstreetmap.org/api/0.6/map"
    MAX_BYTES = 128_000
    TAGS = ("highway", "surface", "tracktype", "access", "smoothness", "width", "maxweight", "bridge", "ford", "source", "source:date")

    def __init__(self, cache_dir: Path, *, transport: httpx.BaseTransport | None = None, daily_limit: int = 50):
        if type(daily_limit) is not int or not 1 <= daily_limit <= 50:
            raise ValueError("daily_limit must be between 1 and 50")
        self.cache_dir, self.transport, self.daily_limit = Path(cache_dir), transport, daily_limit
        self._lock = threading.Lock()
        self._cached = lru_cache(maxsize=64)(self._read)

    def read(self, latitude: float, longitude: float, assessment_date: str) -> dict[str, Any]:
        lat = RemoteSources._coordinate(latitude, -90, 90, "latitude")
        lon = RemoteSources._coordinate(longitude, -180, 180, "longitude")
        day = RemoteSources._date(assessment_date)
        # Serialize provider calls, including cold-cache misses. Public Overpass
        # is a small prototype service here, not a production bulk import API.
        with self._lock:
            return deepcopy(self._cached(lat, lon, day.isoformat(), int(time.monotonic() // 600)))

    def _reserve_query(self, *, map_api: bool = False) -> None:
        path = self.cache_dir / "budget.json"
        today = datetime.now(UTC).date().isoformat()
        budget = json.loads(path.read_bytes()) if path.exists() else {"day": today, "count": 0}
        if not isinstance(budget, dict) or type(budget.get("count")) is not int or budget["count"] < 0:
            raise ValueError("invalid local query budget")
        if budget.get("day") != today:
            budget = {"day": today, "count": 0}
        field = "map_count" if map_api else "count"
        count = budget.get(field, 0)
        if type(count) is not int or count < 0:
            raise ValueError("invalid local query budget")
        if count >= (min(4, self.daily_limit) if map_api else self.daily_limit):
            raise ValueError("daily public Overpass query budget exhausted")
        budget[field] = count + 1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        RemoteSources._atomic(path, json.dumps(budget).encode())

    def _fetch(self, method: str, url: str, *, limit: int, headers: dict, **kwargs) -> bytes:
        if url not in {self.ENDPOINT, self.MAP_ENDPOINT}:
            raise ValueError("unapproved OSM endpoint")
        raw = bytearray()
        with httpx.Client(transport=self.transport, timeout=4 if url == self.ENDPOINT else 12, follow_redirects=False) as client:
            with client.stream(method, url, headers=headers, **kwargs) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=8192):
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise ValueError("bounded extract exceeded")
        return bytes(raw)

    @staticmethod
    def _map_payload(raw: bytes) -> dict:
        root = ET.fromstring(raw)
        if root.tag != "osm":
            raise ValueError("not an OSM map response")
        nodes = {node.attrib['id']: {'lat': float(node.attrib['lat']), 'lon': float(node.attrib['lon'])} for node in root.findall('node')}
        elements = []
        for way in root.findall('way'):
            tags = {tag.attrib['k']: tag.attrib['v'] for tag in way.findall('tag')}
            if 'highway' not in tags:
                continue
            elements.append({'type':'way', 'id':int(way.attrib['id']), 'version':int(way.attrib['version']) if 'version' in way.attrib else None, 'timestamp':way.attrib.get('timestamp'), 'tags':tags, 'geometry':[nodes[nd.attrib['ref']] for nd in way.findall('nd') if nd.attrib['ref'] in nodes]})
        return {'elements':elements}

    def _read(self, lat: float, lon: float, day: str, _cache_window: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        retrieved = now.isoformat().replace("+00:00", "Z")
        historical = day < now.date().isoformat()
        date_filter = f'[date:"{day}T23:59:59Z"]' if historical else ""
        query = f'[out:json][timeout:8][maxsize:1048576]{date_filter};way(around:250,{lat:.7f},{lon:.7f})["highway"];out meta geom 30;'
        data: dict[str, Any] = {"radius_m": 250, "limit": 30, "completeness": "unknown", "attribution": "© OpenStreetMap contributors, ODbL 1.0", "requested_date": day, "temporal_scope": "selected_day_snapshot" if historical else "latest_available_snapshot", "production_bulk_import": False}
        digest, observed, ways = None, None, []
        try:
            self._reserve_query()
            headers = {"User-Agent": "GroundSense-research-prototype/0.1 (non-commercial prototype)", "Content-Type": "text/plain", "Accept": "application/json"}
            try:
                raw = self._fetch("POST", self.ENDPOINT, limit=self.MAX_BYTES, headers=headers, content=query.encode())
                payload = json.loads(raw)
                extension, extraction = '.json', 'osm_vector'
            except httpx.HTTPError:
                if historical:
                    raise
                # Main OSM API is a very small prototype-only fallback, not a
                # bulk map backend. Four bounded extracts/day survive restarts.
                self._reserve_query(map_api=True)
                bbox = [max(-180,lon-.001),max(-90,lat-.001),min(180,lon+.001),min(90,lat+.001)]
                raw = self._fetch("GET", self.MAP_ENDPOINT, limit=2_000_000, headers={**headers, 'Accept':'application/xml'}, params={'bbox':','.join(f'{v:.7f}' for v in bbox)})
                payload = self._map_payload(raw)
                data['sample_bbox_wgs84'] = bbox
                extension, extraction = '.osm', 'osm_api_bbox'
            digest = hashlib.sha256(raw).hexdigest()
            raw_dir = self.cache_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            RemoteSources._atomic(raw_dir / (digest + extension), raw)
            if not isinstance(payload, dict) or payload.get("remark") or not isinstance(payload.get("elements"), list):
                raise ValueError("incomplete Overpass response")
            for element in payload["elements"][:30]:
                if not isinstance(element, dict) or element.get("type") != "way" or type(element.get("id")) is not int:
                    continue
                tags = element.get("tags")
                if not isinstance(tags, dict) or not isinstance(tags.get("highway"), str):
                    continue
                points = []
                geometry = element.get("geometry")
                if isinstance(geometry, list) and 2 <= len(geometry) <= 300:
                    for node in geometry:
                        points.append([RemoteSources._coordinate(node.get("lon"), -180, 180, "longitude"), RemoteSources._coordinate(node.get("lat"), -90, 90, "latitude")])
                ways.append({"osm_id": element["id"], "version": element.get("version"), "edited_at": element.get("timestamp"), "tags": {key: str(tags[key])[:256] if key in tags else None for key in self.TAGS}, "geometry": {"type": "LineString", "coordinates": points} if points else None})
            base = payload.get("osm3s", {}).get("timestamp_osm_base")
            if isinstance(base, str):
                base = datetime.fromisoformat(base.replace("Z", "+00:00")).isoformat().replace("+00:00", "Z")
                data["source_database_at"] = base
                observed = None if historical else base
            data.update(mapped_way_count=len(ways), snapshot_cutoff=f"{day}T23:59:59Z" if historical else observed, extraction=extraction)
            status = "available" if ways else "partial"
            note = f"Отримано {len(ways)} нанесених на OSM ділянок у радіусі 250 м; це не підтверджені під’їзди, стан покриття чи повна дорожня мережа."
            if not historical:
                note += " Останній доступний знімок карти, не прогноз її майбутнього стану."
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
            status = "unavailable"
            ways = []
            # Never echo arbitrary HTTP response bodies, URLs or upstream errors.
            reason = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
            note = f"Векторний знімок OSM недоступний ({reason}); перевірте доступність сервісу або денний ліміт прототипу. Відсутність відповіді не означає відсутність дороги."
            data["extraction"] = "none"
        source = {"id": "openstreetmap", "name": "OpenStreetMap / Overpass", "product": "Обмежений векторний знімок OSM", "version": "OSM API 0.6", "status": status, "qc": "partial" if status == "available" else status, "note": note, "retrieved_at": retrieved, "observed_at": observed, "content_sha256": "sha256:" + digest if digest else None, "data": data}
        return {"ways": ways, "source": source}
