from __future__ import annotations

import heapq
import itertools
import math
import random

import pytest

from apps.api.terrain_search import SearchResult, astar


_DIRECTIONS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _oracle(costs, start, goal, *, cell_size_m=(1.0, 1.0), elevations=None, relief_weight=2.0):
    """Independent Dijkstra implementation for small-grid cross-checks."""
    rows, cols = len(costs), len(costs[0])

    def open_(point):
        row, col = point
        return costs[row][col] is not None and (elevations is None or elevations[row][col] is not None)

    if not open_(start) or not open_(goal):
        return None
    frontier = [(0.0, start)]
    best = {start: 0.0}
    while frontier:
        distance, point = heapq.heappop(frontier)
        if distance != best[point]:
            continue
        if point == goal:
            return distance
        for dr, dc in _DIRECTIONS:
            neighbor = point[0] + dr, point[1] + dc
            if not (0 <= neighbor[0] < rows and 0 <= neighbor[1] < cols) or not open_(neighbor):
                continue
            if dr and dc and (not open_((point[0] + dr, point[1])) or not open_((point[0], point[1] + dc))):
                continue
            step = math.hypot(dc * cell_size_m[0], dr * cell_size_m[1])
            candidate = distance + step * (costs[point[0]][point[1]] + costs[neighbor[0]][neighbor[1]]) / 2
            if elevations is not None:
                candidate += relief_weight * abs(elevations[point[0]][point[1]] - elevations[neighbor[0]][neighbor[1]])
            if candidate < best.get(neighbor, math.inf):
                best[neighbor] = candidate
                heapq.heappush(frontier, (candidate, neighbor))
    return None


def test_finds_a_direct_orthogonal_path() -> None:
    result = astar(((1.0, 1.0),), (0, 0), (0, 1))

    assert result == SearchResult("found", ((0, 0), (0, 1)), 1.0, 2)


def test_returns_one_node_path_for_identical_open_endpoints() -> None:
    assert astar(((1.0,),), (0, 0), (0, 0)) == SearchResult("found", ((0, 0),), 0.0, 0)


def test_returns_no_path_for_blocked_endpoint_or_disconnected_cells() -> None:
    assert astar(((None, 1.0),), (0, 0), (0, 1)).status == "no_path"
    assert astar(((1.0, None, 1.0),), (0, 0), (0, 2)).status == "no_path"


def test_refuses_diagonal_corner_cutting() -> None:
    result = astar(((1.0, None), (None, 1.0)), (0, 0), (1, 1))
    assert result == SearchResult("no_path", (), None, 1)


def test_uses_asymmetric_physical_spacing_for_diagonal_edge() -> None:
    result = astar(((1.0, 1.0), (1.0, 1.0)), (0, 0), (1, 1), cell_size_m=(2.0, 3.0))
    assert result.path == ((0, 0), (1, 1))
    assert result.total_cost == pytest.approx(math.sqrt(13.0))


def test_prefers_a_longer_route_through_cheap_cells() -> None:
    costs = ((1.0, 100.0, 1.0), (0.1, 0.1, 0.1))
    result = astar(costs, (0, 0), (0, 2))
    assert result.status == "found"
    assert (0, 1) not in result.path
    assert result.total_cost == pytest.approx(_oracle(costs, (0, 0), (0, 2)))


def test_relief_is_a_soft_penalty_and_missing_height_blocks_cells() -> None:
    costs = ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    heights = ((0.0, 10.0, 0.0), (0.0, 0.0, 0.0))
    result = astar(costs, (0, 0), (0, 2), elevations=heights, relief_weight=2.0)
    assert result.status == "found"
    assert (0, 1) not in result.path
    assert result.total_cost == pytest.approx(_oracle(costs, (0, 0), (0, 2), elevations=heights))

    blocked_by_height = astar(((1.0, 1.0),), (0, 0), (0, 1), elevations=((0.0, None),))
    assert blocked_by_height.status == "no_path"


def test_expansion_budget_is_enforced_before_next_expansion() -> None:
    result = astar(((1.0, 1.0),), (0, 0), (0, 1), max_expansions=1)
    assert result == SearchResult("budget_exceeded", (), None, 1)


def test_ties_are_deterministic() -> None:
    costs = ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    results = [astar(costs, (0, 0), (2, 1)) for _ in range(10)]
    assert all(result == results[0] for result in results)


def test_matches_independent_dijkstra_for_every_three_by_three_barrier_layout() -> None:
    start, goal = (0, 0), (2, 2)
    for blockers in itertools.product((False, True), repeat=7):
        values = iter(blockers)
        costs = tuple(
            tuple(1.0 if (row, col) in (start, goal) or not next(values) else None for col in range(3))
            for row in range(3)
        )
        expected = _oracle(costs, start, goal)
        result = astar(costs, start, goal)
        assert (result.status == "found") == (expected is not None)
        if expected is not None:
            assert result.total_cost == pytest.approx(expected)


def test_matches_independent_dijkstra_for_random_cost_height_grids() -> None:
    randomizer = random.Random(20261027)
    for _ in range(100):
        costs = tuple(tuple(None if randomizer.random() < 0.2 else randomizer.choice((0.1, 0.5, 1.0, 3.0)) for _ in range(4)) for _ in range(4))
        heights = tuple(tuple(None if value is None or randomizer.random() < 0.15 else randomizer.uniform(-20.0, 20.0) for value in row) for row in costs)
        start, goal = (0, 0), (3, 3)
        expected = _oracle(costs, start, goal, cell_size_m=(2.5, 0.75), elevations=heights, relief_weight=1.25)
        result = astar(costs, start, goal, cell_size_m=(2.5, 0.75), elevations=heights, relief_weight=1.25)
        assert (result.status == "found") == (expected is not None)
        if expected is not None:
            assert result.total_cost == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"costs": ()}, "non-empty"),
        ({"costs": ((1.0,), (1.0, 1.0))}, "rectangular"),
        ({"costs": ((True,),)}, "finite numeric"),
        ({"costs": ((0.0,),)}, "outside allowed"),
        ({"costs": ((float("inf"),),)}, "finite numeric"),
        ({"costs": ((1_000_001.0,),)}, "outside allowed"),
        ({"costs": ((1.0,),), "start": (True, 0)}, "exact integer"),
        ({"costs": ((1.0,),), "goal": [0, 0]}, "exact integer"),
        ({"costs": ((1.0,),), "cell_size_m": (1.0, True)}, "finite numeric"),
        ({"costs": ((1.0,),), "cell_size_m": (0.0, 1.0)}, "outside allowed"),
        ({"costs": ((1.0,),), "relief_weight": 101.0}, "outside allowed"),
        ({"costs": ((1.0,),), "max_expansions": True}, "integer"),
        ({"costs": ((1.0,),), "elevations": ((1.0, 2.0),)}, "shape"),
        ({"costs": ((1.0,),), "elevations": ((float("nan"),),)}, "finite numeric"),
    ],
)
def test_rejects_invalid_inputs(kwargs, message) -> None:
    call = {"costs": ((1.0,),), "start": (0, 0), "goal": (0, 0)}
    call.update(kwargs)
    with pytest.raises(ValueError, match=message):
        astar(**call)


def test_rejects_dimension_limits_before_search_allocations() -> None:
    too_many_rows = tuple((1.0,) for _ in range(513))
    too_many_cells = tuple((1.0,) * 257 for _ in range(257))
    with pytest.raises(ValueError, match="512 rows"):
        astar(too_many_rows, (0, 0), (0, 0))
    with pytest.raises(ValueError, match="size limit"):
        astar(too_many_cells, (0, 0), (0, 0))
