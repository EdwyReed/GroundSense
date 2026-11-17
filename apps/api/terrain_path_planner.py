"""Heuristic off-road area pathfinding, separate from vehicle admission."""
from __future__ import annotations

from datetime import UTC, datetime
import threading
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from apps.api.route_planner import RoutePlanner, _payload
from apps.api.terrain_grid import GridUnavailable, TerrainGridSource
from apps.api.terrain_search import astar
from apps.api.terrain_sections import section_spans


class TerrainPathPlanner:
    def __init__(self, grids: TerrainGridSource, *, max_expansions: int = 65536) -> None:
        if type(max_expansions) is not int or not 1 <= max_expansions <= 65536:
            raise ValueError('Invalid search expansion budget.')
        self.grids, self.max_expansions = grids, max_expansions

    def validate_request(self, payload: Any) -> dict[str, Any]:
        request = RoutePlanner().validate_request(payload)
        try:
            self.grids._bounds(request['origin'], request['destination'])
        except ValueError as exc:
            raise ValueError('Пошук бездоріжжям: точки від 1 м до 20 км, широти від −75° до 75°, без перетину 180°.') from exc
        return request

    def plan(self, payload: Any) -> dict[str, Any]:
        request = self.validate_request(payload)
        retrieved = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
        response: dict[str, Any] = {'request': request, 'analysis_kind': 'terrain_candidate', 'status': 'unavailable', 'routes': [],
                    'vehicle_assessment': 'not_assessed', 'date_assessment': 'not_assessed', 'synthetic': False,
                    'source': {'id': 'terrain-search-grid', 'profile': 'heuristic_area_candidate', 'retrieved_at': retrieved},
                    'routing': {'algorithm': 'a_star_8_connected', 'date_used': False, 'vehicle_used': False},
                    'warnings_uk': ['Попередні кандидати за статичним покривом 2021 і поверхнею DSM; не підтвердження проїзду.',
                                    'Дата, маса, просвіти в лісі та поточне підтоплення не враховані в пошуку. Прогноз на дату доступний у даних ділянки.']}
        try:
            grid = self.grids.read(request['origin'], request['destination'])
        except GridUnavailable:
            response['routing']['search_status'] = 'grid_unavailable'
            response['warnings_uk'].insert(0, 'Дані області пошуку недоступні або перевищено їх обмеження. Пряму лінію замість шляху не підставлено.')
            return response
        response['source'] = {**grid.source, 'profile': 'heuristic_area_candidate'}
        response['routing']['grid_source'] = grid.source
        start, goal = grid.cell_at(request['origin']), grid.cell_at(request['destination'])
        balanced = astar(grid.costs, start, goal, cell_size_m=grid.cell_size_m, elevations=grid.elevations, max_expansions=self.max_expansions)
        response['routing'].update(search_status=balanced.status, expanded_total=balanced.expanded)
        if balanced.status != 'found':
            response['status'] = 'no_route' if balanced.status == 'no_path' else 'unavailable'
            response['warnings_uk'].insert(0, 'Кандидата не знайдено в цій області та за цією політикою. Це не доказ відсутності проїзду поза областю або в прогалинах даних.' if balanced.status == 'no_path' else 'Досягнуто бюджет пошуку; результат невідомий, а не «шляху немає».')
            return response
        variants = [(balanced, 'landcover-relief', 'За покривом і DSM')]
        # A real second search, never decorative alternatives or a straight fallback.
        uniform = tuple(tuple(1.0 if value is not None else None for value in row) for row in grid.costs)
        shortest = astar(uniform, start, goal, cell_size_m=grid.cell_size_m, max_expansions=self.max_expansions)
        response['routing']['expanded_total'] += shortest.expanded
        if shortest.status == 'found':
            overlap = len(set(balanced.path) & set(shortest.path)) / max(1, min(len(balanced.path), len(shortest.path)))
            if overlap < .85:
                variants.append((shortest, 'shortest-mapped-grid', 'За відстанню по сітці'))
        routes = []
        for result, policy, name in variants:
            try:
                coords = grid.path_to_coordinates(result.path, request['origin'], request['destination'])
            except GridUnavailable:
                continue
            distance = sum(RoutePlanner._distance_m({'longitude': a[0], 'latitude': a[1]}, {'longitude': b[0], 'latitude': b[1]}) for a, b in zip(coords, coords[1:]))
            routes.append({'id': f'terrain-path-{len(routes) + 1}', 'name': name, 'distance_m': distance,
                           'geometry_kind': 'terrain_candidate', 'geometry': {'type': 'LineString', 'coordinates': coords},
                           'conditions': {'status': 'not_assessed', 'summary_uk': 'Кандидат по місцевості · проїзд не підтверджено'},
                           'surface': {'paved_m': None, 'unpaved_m': None}, 'segments': [],
                           'section_spans': section_spans(grid, coords),
                           'planning': {'policy': policy, 'cost': result.total_cost, 'cost_unit': 'relative heuristic cost, not time or mobility',
                                        'grid_steps': max(0, len(result.path) - 1)}})
        response['routes'] = routes
        response['status'] = 'ready' if routes else 'unavailable'
        if not routes:
            response['routing']['search_status'] = 'geometry_budget_exceeded'
            response['warnings_uk'].insert(0, 'Знайдена геометрія перевищує межі відображення. Скорочену пряму замість неї не підставлено.')
        return response


def register_terrain_path_endpoints(app: FastAPI, mutate: Callable[..., Any], consume_source_budget: Callable[[str], None], *, planner: TerrainPathPlanner | None = None) -> None:
    adapter = planner or TerrainPathPlanner(TerrainGridSource(app.state.static_sources))
    app.state.terrain_path_planner = adapter
    app.state.terrain_search_slots = threading.BoundedSemaphore(1)

    @app.post('/api/v1/terrain-path-plans')
    async def terrain_path_plan(request: Request, session: Any = Depends(mutate)) -> dict[str, Any]:
        payload = await _payload(request, RoutePlanner.MAX_REQUEST_BYTES)
        try:
            validated = adapter.validate_request(payload)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        search_slots = app.state.terrain_search_slots
        if not search_slots.acquire(blocking=False):
            raise HTTPException(429, detail='Пошук зайнятий. Спробуйте пізніше.')
        slots = getattr(app.state, 'context_slots', None)
        if slots is None or not slots.acquire(blocking=False):
            search_slots.release()
            raise HTTPException(429, detail='Забагато одночасних запитів джерел. Спробуйте пізніше.')
        try:
            consume_source_budget(session.workspace_id)
            result = await run_in_threadpool(adapter.plan, validated)
            if result['status'] == 'ready':
                result['plan_id'] = app.state.route_plan_store.put(session.workspace_id, result)
            return result
        finally:
            slots.release()
            search_slots.release()
