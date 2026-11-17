from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.api.route_context import RouteContext
from apps.api.terrain_planner import TerrainPlanner
from tests.runtime_routes.test_route_context import StaticDouble, VALID, WeatherDouble, planner


class HistoryWeather(WeatherDouble):
    def __init__(self):
        self.calls = []

    def forecast(self, *args):
        self.calls.append('legacy')
        return super().forecast(*args)

    def forecast_for_section(self, latitude, longitude, trip_date):
        self.calls.append('section')
        value = WeatherDouble().forecast(latitude, longitude, trip_date)
        end = datetime.fromisoformat(trip_date).replace(tzinfo=UTC)
        start = end - timedelta(days=7)
        value['antecedent_series'] = [{'time': (start + timedelta(hours=h)).isoformat(), 'precipitation': 900 if h == 0 else 1,
            'precipitation_interval_start': (start + timedelta(hours=h - 1)).isoformat(),
            'precipitation_interval_end': (start + timedelta(hours=h)).isoformat()} for h in range(169)]
        return value


def test_only_offroad_context_uses_single_history_capable_weather_call_without_raw_series():
    weather = HistoryWeather()
    context = RouteContext(terrain_evidence_factory=lambda _: None)
    selected = {'plan_id': 'a' * 32, 'route_id': 'transect-1', 'section_index': 0}
    result = context.build(TerrainPlanner().plan(VALID), selected, StaticDouble(), weather)
    assert weather.calls == ['section']
    summary = result['weather']['antecedent_precipitation']
    assert summary['date'] == VALID['trip_date'] and summary['total_mm'] == 168
    assert summary['known_intervals'] == 168 and len(summary['days']) == 7
    assert all(day['total_mm'] == 24 for day in summary['days'])
    assert 'antecedent_series' not in result['weather'] and 'research_series' not in result['weather']
    assert 'day_summary' in result['weather']


def test_road_context_retains_original_forecast_request_and_has_no_history_summary():
    weather = HistoryWeather()
    result = RouteContext().build(planner().plan(VALID), {'plan_id': 'a' * 32, 'route_id': 'route-1', 'section_index': 0}, StaticDouble(), weather)
    assert weather.calls == ['legacy']
    assert 'antecedent_precipitation' not in result['weather']
