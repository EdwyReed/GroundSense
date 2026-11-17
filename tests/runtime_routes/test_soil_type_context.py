from __future__ import annotations

import json
import threading

from apps.api.route_context import RouteContext
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import StaticDouble, VALID, WeatherDouble, planner
from tests.runtime_routes.test_route_context_latency import complete_evidence
from tests.runtime_routes.test_surface_observation_context import SurfaceDouble


def selected(index=0):
    return {'plan_id': 'a' * 32, 'route_id': 'transect-1', 'section_index': index}


class SoilDouble:
    def __init__(self):
        self.calls = []

    def read_point(self, latitude, longitude):
        self.calls.append((latitude, longitude, threading.get_ident()))
        return ({'status': 'available', 'basis': 'hwsd_v2_smu_dominant_soil',
                 'requested_point': {'latitude': latitude, 'longitude': longitude},
                 'map_unit_id': 10124, 'wrb_code': 'PZal', 'wrb_name': 'Albic Podzols', 'share_percent': 70,
                 'resolution_arc_seconds': 30, 'temporal_scope': 'static_reference',
                 'classification_system': 'WRB 2022', 'spatial_scope': 'soil_mapping_unit'},
                {'id': 'hwsd-v2', 'product': 'Harmonized World Soil Database v2.0', 'status': 'available',
                 'qc': 'available', 'retrieved_at': '2026-10-26T00:00:00Z', 'observed_at': None,
                 'content_sha256': 'sha256:' + 'a' * 64, 'data': {'commercial_reuse': 'not_established'}})


class Evidence:
    def read(self, *_):
        return complete_evidence()


def test_offroad_soil_type_uses_exact_server_point_and_existing_canopy_lane():
    soil, canopy_threads = SoilDouble(), []

    class Canopy:
        def read_point(self, *_):
            canopy_threads.append(threading.get_ident())
            return {'percent': 73}, {'id': 'clms-tree-cover-density', 'status': 'available'}

    context = RouteContext(soil_type_source=soil, canopy_source=Canopy(), terrain_evidence_factory=lambda _: Evidence(), surface_observation=SurfaceDouble())
    result = context.build(TerrainPlanner().plan(VALID), selected(2), StaticDouble(), WeatherDouble())
    point = result['sections'][2]['point']
    assert soil.calls == [(point['latitude'], point['longitude'], canopy_threads[0])]
    assert result['soil_type']['requested_point'] == point
    assert result['soil_type']['wrb_name'] == 'Albic Podzols'
    assert result['soil_type']['share_percent'] == 70
    assert 'assessment_date' not in result['soil_type']
    assert context.PROVIDER_MAX_WORKERS == 4
    assert not any(thread.name.startswith('groundsense-section') for thread in threading.enumerate())
    source = next(source for source in result['sources'] if source['id'] == 'hwsd-v2')
    assert source['extraction_scope'] == 'soil_mapping_unit'
    assert source['observed_at'] is None
    assert result['ground_composition']['composition'] == {'sand': 50.0, 'silt': 30.0, 'clay': 17.4}
    json.dumps(result, allow_nan=False)


def test_road_context_never_reads_or_advertises_the_soil_type_adapter():
    soil = SoilDouble()
    result = RouteContext(soil_type_source=soil).build(planner().plan(VALID), {**selected(), 'route_id': 'route-1'}, StaticDouble(), WeatherDouble())
    assert soil.calls == []
    assert 'soil_type' not in result
    assert all(source['id'] != 'hwsd-v2' for source in result['sources'])


def test_soil_failure_keeps_other_evidence_and_never_exposes_process_details():
    class BrokenSoil:
        def read_point(self, *_):
            raise RuntimeError('private native parser path')

    context = RouteContext(soil_type_source=BrokenSoil(), terrain_evidence_factory=lambda _: Evidence())
    result = context.build(TerrainPlanner().plan(VALID), selected(), StaticDouble(), WeatherDouble())
    assert result['soil_type']['status'] == 'unavailable'
    assert result['soil_type']['wrb_code'] is None
    assert result['soil_type']['wrb_name'] is None
    assert result['soil_type']['requested_point'] == result['sections'][0]['point']
    assert result['weather']['assessment_date'] == VALID['trip_date']
    assert result['ground_composition']['composition']['sand'] == 50
    assert 'private native parser path' not in json.dumps(result)


def test_canopy_failure_does_not_skip_independent_static_soil_classification():
    class BrokenCanopy:
        def read_point(self, *_):
            raise RuntimeError('canopy unavailable')

    soil = SoilDouble()
    context = RouteContext(soil_type_source=soil, canopy_source=BrokenCanopy(), terrain_evidence_factory=lambda _: Evidence())
    result = context.build(TerrainPlanner().plan(VALID), selected(), StaticDouble(), WeatherDouble())
    assert len(soil.calls) == 1
    assert result['soil_type']['status'] == 'available'
    assert result['canopy_cover']['percent'] is None


def test_unconfigured_soil_source_does_not_change_legacy_context_fields():
    result = RouteContext(terrain_evidence_factory=lambda _: Evidence()).build(TerrainPlanner().plan(VALID), selected(), StaticDouble(), WeatherDouble())
    assert 'soil_type' not in result
    assert all(source['id'] != 'hwsd-v2' for source in result['sources'])


def test_production_factory_uses_live_adapter_lookup_without_reading_sources(tmp_path, monkeypatch):
    from apps.api.main import create_app
    from apps.api.soil_type import SoilTypeSource
    monkeypatch.setenv('GROUNDSENSE_DATABASE_URL', f'sqlite:///{tmp_path}/factory.db')
    monkeypatch.setenv('GROUNDSENSE_DATA_DIR', str(tmp_path / 'data'))
    app = create_app()
    source = app.state.route_context._soil_type_source
    assert isinstance(source, SoilTypeSource)
    assert source.adapter_lookup() is app.state.extra_sources['hwsd']
    replacement = object()
    app.state.extra_sources['hwsd'] = replacement
    assert source.adapter_lookup() is replacement
    del app.state.extra_sources['hwsd']
    assert source.adapter_lookup() is None
    assert source.read_point(59.98, 10.73)[0]['status'] == 'unavailable'
