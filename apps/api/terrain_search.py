"""Deterministic bounded A* search over a cost raster."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Sequence


@dataclass(frozen=True)
class SearchResult:
    status: str
    path: tuple[tuple[int, int], ...]
    total_cost: float | None
    expanded: int


def astar(
    costs: Sequence[Sequence[float | None]],
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    cell_size_m: tuple[float, float] = (1.0, 1.0),
    elevations: Sequence[Sequence[float | None]] | None = None,
    relief_weight: float = 2.0,
    max_expansions: int = 65536,
) -> SearchResult:
    """Return the least-cost 8-connected raster path within the expansion cap."""
    rows, cols, minimum_cost, height_grid, dx, dy = _validate(
        costs, start, goal, cell_size_m, elevations, relief_weight, max_expansions
    )
    if not _open(costs, height_grid, start) or not _open(costs, height_grid, goal):
        return SearchResult("no_path", (), None, 0)
    if start == goal:
        return SearchResult("found", (start,), 0.0, 0)

    queue: list[tuple[float, float, int, int, int, tuple[int, int]]] = []
    serial = 0
    heapq.heappush(queue, (_heuristic(start, goal, dx, dy, minimum_cost), 0.0, 0, start[0], start[1], start))
    distances = {start: 0.0}
    parents: dict[tuple[int, int], tuple[int, int]] = {}
    expanded = 0
    directions = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

    while queue:
        _, current_cost, _, _, _, current = heapq.heappop(queue)
        if current_cost != distances.get(current):
            continue
        if expanded >= max_expansions:
            return SearchResult("budget_exceeded", (), None, expanded)
        expanded += 1
        if current == goal:
            path = [current]
            while path[-1] != start:
                path.append(parents[path[-1]])
            path.reverse()
            return SearchResult("found", tuple(path), current_cost, expanded)
        for dr, dc in directions:
            neighbor = (current[0] + dr, current[1] + dc)
            if not (0 <= neighbor[0] < rows and 0 <= neighbor[1] < cols):
                continue
            if not _open(costs, height_grid, neighbor):
                continue
            if dr and dc and (not _open(costs, height_grid, (current[0] + dr, current[1])) or not _open(costs, height_grid, (current[0], current[1] + dc))):
                continue
            step = math.hypot(dc * dx, dr * dy)
            current_weight, neighbor_weight = costs[current[0]][current[1]], costs[neighbor[0]][neighbor[1]]
            assert current_weight is not None and neighbor_weight is not None
            edge = step * (current_weight + neighbor_weight) / 2
            if height_grid is not None:
                current_height, neighbor_height = height_grid[current[0]][current[1]], height_grid[neighbor[0]][neighbor[1]]
                assert current_height is not None and neighbor_height is not None
                edge += relief_weight * abs(current_height - neighbor_height)
            candidate = current_cost + edge
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                parents[neighbor] = current
                serial += 1
                score = candidate + _heuristic(neighbor, goal, dx, dy, minimum_cost)
                heapq.heappush(queue, (score, candidate, serial, neighbor[0], neighbor[1], neighbor))
    return SearchResult("no_path", (), None, expanded)


def _open(costs: Sequence[Sequence[float | None]], heights: Sequence[Sequence[float | None]] | None, point: tuple[int, int]) -> bool:
    row, col = point
    return costs[row][col] is not None and (heights is None or heights[row][col] is not None)


def _heuristic(point: tuple[int, int], goal: tuple[int, int], dx: float, dy: float, minimum_cost: float) -> float:
    return math.hypot((goal[1] - point[1]) * dx, (goal[0] - point[0]) * dy) * minimum_cost


def _validate(costs: Sequence[Sequence[float | None]], start: tuple[int, int], goal: tuple[int, int], cell_size_m: tuple[float, float], elevations: Sequence[Sequence[float | None]] | None, relief_weight: float, max_expansions: int) -> tuple[int, int, float, Sequence[Sequence[float | None]] | None, float, float]:
    if not isinstance(costs, Sequence) or isinstance(costs, (str, bytes)) or not costs:
        raise ValueError("costs must be a non-empty rectangular sequence")
    rows = len(costs)
    if rows > 512:
        raise ValueError("cost grid exceeds 512 rows")
    if not isinstance(costs[0], Sequence) or isinstance(costs[0], (str, bytes)) or not costs[0]:
        raise ValueError("costs must have non-empty rows")
    cols = len(costs[0])
    if cols > 512 or rows * cols > 65536:
        raise ValueError("cost grid exceeds size limit")
    minimum = math.inf
    for row in costs:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != cols:
            raise ValueError("costs must be rectangular")
        for value in row:
            if value is not None:
                _finite(value, "cost", 0.0, 1_000_000.0, strict_low=True)
                minimum = min(minimum, float(value))
    if elevations is not None:
        if not isinstance(elevations, Sequence) or isinstance(elevations, (str, bytes)) or len(elevations) != rows:
            raise ValueError("elevations shape must match costs")
        for row in elevations:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != cols:
                raise ValueError("elevations shape must match costs")
            for value in row:
                if value is not None:
                    _finite(value, "elevation", -1_000_000.0, 1_000_000.0)
    for point, name in ((start, "start"), (goal, "goal")):
        if not isinstance(point, tuple) or len(point) != 2 or any(type(x) is not int for x in point):
            raise ValueError(f"{name} must be an exact integer (row, column) tuple")
        if not (0 <= point[0] < rows and 0 <= point[1] < cols):
            raise ValueError(f"{name} is outside costs")
    if not isinstance(cell_size_m, tuple) or len(cell_size_m) != 2:
        raise ValueError("cell_size_m must be a two-item tuple")
    dx = _finite(cell_size_m[0], "cell_size_m", 0.0, 1_000_000.0, strict_low=True)
    dy = _finite(cell_size_m[1], "cell_size_m", 0.0, 1_000_000.0, strict_low=True)
    _finite(relief_weight, "relief_weight", 0.0, 100.0)
    if type(max_expansions) is not int or not 1 <= max_expansions <= 65536:
        raise ValueError("max_expansions must be an integer from 1 to 65536")
    return rows, cols, minimum, elevations, dx, dy


def _finite(value: object, name: str, low: float, high: float, *, strict_low: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    number = float(value)
    if number > high or number < low or (strict_low and number <= low):
        raise ValueError(f"{name} is outside allowed bounds")
    return number
