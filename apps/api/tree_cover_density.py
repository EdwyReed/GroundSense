"""Selective canopy-cover read using the existing native TCD parser."""
from datetime import UTC, datetime
import httpx

from apps.api.context_sources import ContextSources


class TreeCoverDensity(ContextSources):
    MAX_BYTES = 65_536

    def read_point(self, latitude: float, longitude: float):
        latitude = self._coordinate(latitude, "latitude", -90, 90)
        longitude = self._coordinate(longitude, "longitude", -180, 180)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return self._tree_cover_density(latitude, longitude, now)

    def _request(self, url: str, params: dict[str, str] | None = None) -> bytes:
        if url != self.TCD_IDENTIFY_URL:
            raise ValueError("unapproved tree-cover endpoint")
        body = bytearray()
        with httpx.Client(transport=self.transport, timeout=min(self.timeout_seconds, 8), follow_redirects=False) as client:
            with client.stream("GET", url, params=params, headers={"Accept": "application/json"}) as response:
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("unexpected tree-cover redirect")
                for chunk in response.iter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > self.MAX_BYTES:
                        raise ValueError("tree-cover response exceeds limit")
                    body.extend(chunk)
        return bytes(body)
