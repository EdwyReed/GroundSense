from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

from apps.api.route_context import RouteContext
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import StaticDouble, VALID, planner
from tests.runtime_routes.test_antecedent_context import HistoryWeather


class OutlookWeather(HistoryWeather):
    def forecast_for_section(self, latitude, longitude, trip_date):
        dto = super().forecast_for_section(latitude, longitude, trip_date)
        start = datetime.fromisoformat(trip_date).replace(tzinfo=UTC)
        dto['units'].update(soil_temperature_0cm='°C', snow_depth='m')
        dto['research_series'] = []
        for h in range(73):
            end = start + timedelta(hours=h)
            dto['research_series'].append({'time': end.isoformat(), 'precipitation': 900 if h == 0 else 1,
                'precipitation_interval_start': (end - timedelta(hours=1)).isoformat(), 'precipitation_interval_end': end.isoformat(),
                'soil_temperature_0cm': -2 if h < 24 else 3, 'snow_depth': 0})
        self.dto = dto
        self.before = deepcopy(dto)
        return dto


def test_offroad_outlook_and_current_history_share_exactly_one_unchanged_forecast():
    source = OutlookWeather()
    context = RouteContext(terrain_evidence_factory=lambda _: None)
    result = context.build(TerrainPlanner().plan(VALID), {'plan_id': 'a' * 32, 'route_id': 'transect-1', 'section_index': 0}, StaticDouble(), source)
    assert source.calls == ['section']
    weather = result['weather']
    assert weather['outlook']['date'] == VALID['trip_date']
    assert [d['date'] for d in weather['outlook']['days']] == ['2026-10-27', '2026-10-28']
    assert weather['outlook']['status'] == 'available'
    assert all(day['precipitation']['total_mm'] == 24 for day in weather['outlook']['days'])
    assert weather['day_summary']['precipitation']['total_mm'] == 24
    assert weather['antecedent_precipitation']['total_mm'] == 168
    assert weather['source']['content_sha256'] == source.dto['source']['content_sha256']
    assert source.dto == source.before
    assert not {'research_series', 'antecedent_series'} & weather.keys()
    json.dumps(result, allow_nan=False)


def test_legacy_road_context_keeps_original_request_and_has_no_outlook():
    source = OutlookWeather()
    result = RouteContext().build(planner().plan(VALID), {'plan_id': 'a' * 32, 'route_id': 'route-1', 'section_index': 0}, StaticDouble(), source)
    assert source.calls == ['legacy']
    assert 'outlook' not in result['weather']
