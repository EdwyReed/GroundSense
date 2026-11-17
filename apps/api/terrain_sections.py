"""Route-dependent display sections of the static search grid, not mobility."""
from __future__ import annotations

from bisect import bisect_right
import math
from typing import Any

from apps.api.route_planner import RoutePlanner
from apps.api.terrain_grid import COVER_CODES, TerrainGrid

MAX_SECTIONS = 32
COVER_LABELS = {10: 'Дерева', 20: 'Чагарники', 30: 'Трав’яний покрив', 40: 'Рілля',
                50: 'Забудова', 60: 'Розріджений покрив', 70: 'Сніг / лід', 80: 'Вода',
                90: 'Водно-болотні угіддя', 95: 'Мангри', 100: 'Мохи / лишайники'}
TREND_LABELS = {'level': 'без значного перепаду', 'up': 'підйом', 'down': 'спуск',
                'steep_up': 'значний підйом', 'steep_down': 'значний спуск', 'unknown': 'немає даних'}


def section_spans(grid: TerrainGrid, coordinates: list[list[float]]) -> list[dict[str, Any]]:
    lengths = [RoutePlanner._distance_m({'longitude': a[0], 'latitude': a[1]}, {'longitude': b[0], 'latitude': b[1]})
               for a, b in zip(coordinates, coordinates[1:])]
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    total = cumulative[-1]
    step = max(.5, min(grid.cell_size_m) / 2)
    count = math.ceil(total / step)
    if not 0 < count <= 65536:
        raise ValueError('Section sampling budget exceeded.')

    def cell_at(chainage: float) -> tuple[int, int]:
        index = min(bisect_right(cumulative, chainage) - 1, len(lengths) - 1)
        fraction = (chainage - cumulative[index]) / lengths[index] if lengths[index] else 0
        left, right = coordinates[index], coordinates[index + 1]
        return grid.cell_at({'longitude': left[0] + (right[0] - left[0]) * fraction,
                             'latitude': left[1] + (right[1] - left[1]) * fraction})

    def merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        return {**left, 'to_m': right['to_m'],
                'land_cover_classes': sorted(set(left['land_cover_classes']) | set(right['land_cover_classes'])),
                'unknown_cover': left['unknown_cover'] or right['unknown_cover'],
                'dsm_trends': sorted(set(left['dsm_trends']) | set(right['dsm_trends'])), 'generalized': True}

    runs: list[dict[str, Any]] = []
    previous = None
    # A half-cell sampling step resolves the planning grid, not native 10 m boundaries.
    # DSM change is measured along this actual polyline over >=60 m, not bare-earth slope.
    window = max(30.0, max(grid.cell_size_m))
    for index in range(count):
        start, end = total * index / count, total * (index + 1) / count
        middle = (start + end) / 2
        row, col = cell_at(middle)
        mask = grid.cover_masks[row][col] if grid.cover_masks and grid.costs[row][col] is not None else 0
        codes = [code for bit, code in enumerate(COVER_CODES) if mask & (1 << bit)]
        lo, hi = max(0.0, middle - window), min(total, middle + window)
        r0, c0 = cell_at(lo)
        r1, c1 = cell_at(hi)
        h0, h1 = grid.elevations[r0][c0], grid.elevations[r1][c1]
        if h0 is None or h1 is None or hi <= lo:
            trend = 'unknown'
        else:
            grade = math.degrees(math.atan2(h1 - h0, hi - lo))
            trend = 'level' if abs(grade) < 5 else ('steep_' if abs(grade) >= 15 else '') + ('up' if grade > 0 else 'down')
        signature = (mask, trend)
        if runs and signature == previous:
            runs[-1]['to_m'] = end
        else:
            runs.append({'from_m': start, 'to_m': end, 'land_cover_classes': codes,
                         'unknown_cover': not codes, 'dsm_trends': [trend], 'generalized': False})
        previous = signature
    # Keep native cover transitions, including short wetlands. Only generalize if
    # the display budget is exceeded; retain all classes/unknowns in merged groups.
    if len(runs) > MAX_SECTIONS:
        group_size = math.ceil(len(runs) / MAX_SECTIONS)
        grouped = []
        for offset in range(0, len(runs), group_size):
            group = runs[offset]
            for following in runs[offset + 1:offset + group_size]:
                group = merge(group, following)
            grouped.append(group)
        runs = grouped
    for run in runs:
        labels = [COVER_LABELS[code] for code in run['land_cover_classes']]
        if run['unknown_cover']:
            labels.append('невідомий покрив')
        cover = ' / '.join(labels) if len(labels) <= 2 else 'Змішаний покрив'
        relief = TREND_LABELS[run['dsm_trends'][0]] if len(run['dsm_trends']) == 1 else 'змінний перепад'
        run['label_uk'] = f'{cover} · DSM: {relief}'
        run['basis'] = 'sampled_search_grid'
        run['source_sha256'] = grid.source.get('content_sha256')
        run['support_m'] = list(grid.cell_size_m)
    return runs
