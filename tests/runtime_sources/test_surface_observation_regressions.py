"""Wire/native regressions reproduced by parent against actual provider behavior."""
from datetime import UTC, datetime

import httpx
import numpy as np
import rasterio
from rasterio.transform import from_origin

from apps.api.surface_observation import SurfaceObservation


URL = 'https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/32/V/NM/2026/10/scene/SCL.tif'
NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def scene():
    return {'id': 'scene', 'collection': 'sentinel-2-l2a', 'properties': {'datetime': '2026-10-25T10:00:00Z'},
            'assets': {'scl': {'href': URL, 'raster:bands': [{'scale': 1, 'offset': 0}]}}}


def test_earth_search_sort_uses_properties_datetime_not_unmapped_root_field(tmp_path, monkeypatch):
    import json
    def respond(request):
        body = json.loads(request.content)
        # Actual Earth Search returns400 for root datetime; captured in parent native probe.
        if body['sortby'] != [{'field': 'properties.datetime', 'direction': 'desc'}]:
            return httpx.Response(400, json={'description': 'No mapping found for [datetime] in order to sort on'})
        return httpx.Response(200, json={'features': [scene()]})
    adapter = SurfaceObservation(tmp_path, transport=httpx.MockTransport(respond), clock=lambda: NOW)
    monkeypatch.setattr(adapter, '_sample_scl', lambda *_: {'raw_class': 8, 'resolution_m': 20})
    observation, _ = adapter.read_point(59.985, 10.734, '2026-10-26')
    assert observation['scl_class'] == 8 and observation['condition'] == 'cloud'


def test_stac_nodata_is_not_presented_as_valid_water_when_native_mask_is_absent(tmp_path, monkeypatch):
    native = tmp_path / 'metadata-nodata.tif'
    with rasterio.open(native, 'w', driver='GTiff', height=1, width=1, count=1, dtype='uint8',
                       crs='EPSG:4326', transform=from_origin(10, 60.2, .1, .1)) as dataset:
        dataset.write(np.array([[6]], dtype='uint8'), 1)
    original = rasterio.open
    monkeypatch.setattr(rasterio, 'open', lambda *_args, **_kwargs: original(native))
    item = scene()
    item['assets']['scl']['raster:bands'][0]['nodata'] = 6
    adapter = SurfaceObservation(tmp_path / 'cache', transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'features': [item]})), clock=lambda: NOW)
    observation, _ = adapter.read_point(60.15, 10.05, '2026-10-26')
    assert observation['scl_class'] is None and observation['condition'] == 'unknown'
