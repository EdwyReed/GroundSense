"""Terrain sections are evidence/geometry-dependent, not equal thirds."""
import numpy as np
import pytest

from apps.api.route_context import RouteContext
from apps.api.terrain_grid import TerrainGridSource
from apps.api.terrain_path_planner import TerrainPathPlanner
from tests.runtime_routes.test_terrain_grid import A, B, LocalSources
from tests.runtime_routes.test_route_context import WeatherDouble

REQUEST = {'origin': A, 'destination': B, 'trip_date': '2026-10-27', 'vehicle': {'kind': 'truck_6x6', 'gross_mass_t': 20}}


@pytest.mark.parametrize('codes', [[30], [30, 10], [20, 60], [30, 10, 90, 40, 20]])
def test_section_count_follows_native_cover_changes_not_thirds(tmp_path, codes):
    cover = np.full((64, 64), codes[0], dtype='uint8')
    for columns, code in zip(np.array_split(np.arange(24, 37), len(codes)), codes):
        cover[:, columns] = code
    cover[:, 37:] = codes[-1]
    planner = TerrainPathPlanner(TerrainGridSource(LocalSources(tmp_path, cover), padding_m=30))
    plan = planner.plan(REQUEST)
    route = plan['routes'][0]
    spans = route['section_spans']
    assert len(spans) == len(codes)
    assert spans[0]['from_m'] == 0
    assert spans[-1]['to_m'] == pytest.approx(route['distance_m'])
    assert [span['land_cover_classes'] for span in spans] == [[code] for code in codes]
    assert all(span['dsm_trends'] == ['level'] for span in spans)
    assert all(left['to_m'] == right['from_m'] for left, right in zip(spans, spans[1:]))
    assert all(span['to_m'] > span['from_m'] for span in spans)


def test_context_and_chainage_use_the_same_stored_dynamic_boundaries(tmp_path):
    cover = np.full((64, 64), 30, dtype='uint8')
    for columns, code in zip(np.array_split(np.arange(24, 37), 5), [30, 10, 90, 40, 20]):
        cover[:, columns] = code
    cover[:, 37:] = 20
    sources = LocalSources(tmp_path, cover)
    plan = TerrainPathPlanner(TerrainGridSource(sources, padding_m=30)).plan(REQUEST)
    route = plan['routes'][0]
    final = route['section_spans'][-1]
    context = RouteContext()
    selected = context.validate({'plan_id': 'a' * 32, 'route_id': route['id'], 'section_index': 4,
                                 'sample_chainage_m': (final['from_m'] + final['to_m']) / 2})
    resolved, _ = context.resolve_selection(plan, selected)
    assert resolved['sample_point']
    response = context.build(plan, selected, sources, WeatherDouble())
    assert response['section_index'] == 4
    assert len(response['sections']) == 5
    assert response['sample_selection']['point'] == resolved['sample_point']
    sections = context._sections(route['geometry'], route['section_spans'])
    assert len(sections) == 5
    assert sections[-1]['index'] == 4
    assert sections[-1]['geometry']['coordinates'][-1] == route['geometry']['coordinates'][-1]
    assert all(left['geometry']['coordinates'][-1] == right['geometry']['coordinates'][0] for left, right in zip(sections, sections[1:]))
    with pytest.raises(ValueError):
        context.resolve_selection(plan, {**selected, 'section_index': 0})
    with pytest.raises(ValueError):
        context.resolve_selection(plan, {'route_id': route['id'], 'section_index': 5})


@pytest.mark.parametrize('reverse, trend', [(False, 'up'), (True, 'down')])
def test_same_cover_splits_for_dsm_change_and_follows_travel_direction(tmp_path, reverse, trend):
    heights = np.broadcast_to((150 + np.maximum(36 - np.arange(64), 0) * 5)[:, None], (64, 64)).astype('float32')
    sources = LocalSources(tmp_path, heights=heights)
    request = {**REQUEST, 'origin': B, 'destination': A} if reverse else REQUEST
    route = TerrainPathPlanner(TerrainGridSource(sources, padding_m=30)).plan(request)['routes'][0]
    spans = route['section_spans']
    assert len(spans) > 1
    assert all(span['land_cover_classes'] == [30] for span in spans)
    trends = {value for span in spans for value in span['dsm_trends']}
    assert 'level' in trends
    assert any(value.endswith(trend) for value in trends)
    assert not any(value.endswith('down' if trend == 'up' else 'up') for value in trends)


def test_display_budget_preserves_short_wetlands_and_complete_geometry(tmp_path):
    cover = np.full((64, 64), 30, dtype='uint8')
    cover[:, 1::2] = 90
    sources = LocalSources(tmp_path, cover)
    request = {**REQUEST, 'origin': {'longitude': 10.00025, 'latitude': 60.002},
               'destination': {'longitude': 10.005, 'latitude': 60.003}}
    route = TerrainPathPlanner(TerrainGridSource(sources, padding_m=10)).plan(request)['routes'][0]
    spans = route['section_spans']
    assert 1 < len(spans) <= 32
    assert any(span['generalized'] for span in spans)
    assert {value for span in spans for value in span['land_cover_classes']} == {30, 90}
    assert spans[0]['from_m'] == 0
    assert spans[-1]['to_m'] == pytest.approx(route['distance_m'])
    assert all(left['to_m'] == right['from_m'] for left, right in zip(spans, spans[1:]))


@pytest.mark.parametrize('spans', [[], [{'from_m': True, 'to_m': 100}],
    [{'from_m': 0, 'to_m': float('nan')}], [{'from_m': -1, 'to_m': 100}],
    [{'from_m': 0, 'to_m': 5}, {'from_m': 6, 'to_m': 100}],
    [{'from_m': 0, 'to_m': 20}, {'from_m': 19, 'to_m': 100}],
    [{'from_m': 0, 'to_m': 1}]])
def test_invalid_stored_spans_are_rejected(spans):
    geometry = {'type': 'LineString', 'coordinates': [[10, 60], [10.001, 60.001]]}
    with pytest.raises(ValueError):
        RouteContext()._sections(geometry, spans)
