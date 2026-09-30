"""The maze is a proposal; this test is the authority.

Checks dimensions, horizontal symmetry, that every pellet is reachable from Spain's
start, that the ghost house door connects the house to the maze, and that the tunnel
joins both sides.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

MAZE_PATH = Path(__file__).resolve().parent.parent / "static" / "maze.txt"

WALL = "#"
DOOR = "-"
HOUSE = "G"
TUNNEL = "T"
PELLET = "."
POWER = "o"
START = "P"
WALKABLE = set(" .oPTG-")         # ghosts: they own the house and pass the door
PAC_WALKABLE = set(" .oPT")       # Spain cannot enter the house or the door


@pytest.fixture(scope="module")
def grid() -> list[str]:
    rows = MAZE_PATH.read_text(encoding="utf-8").splitlines()
    return [r for r in rows if r.strip("\n")]


def width(grid) -> int:
    return len(grid[0])


def at(grid, col: int, row: int) -> str:
    if row < 0 or row >= len(grid):
        return WALL
    if col < 0 or col >= width(grid):
        return WALL
    return grid[row][col]


def neighbours(grid, col: int, row: int, walkable: set[str]):
    """Four-way neighbours, with the row-10 tunnel wrapping left to right."""
    w = width(grid)
    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c, r = col + dc, row + dr
        if c < 0 or c >= w:
            if at(grid, col, row) == TUNNEL and dr == 0:
                c = (c + w) % w          # wrap through the tunnel
            else:
                continue
        if at(grid, c, r) in walkable:
            yield c, r


def find(grid, ch: str) -> list[tuple[int, int]]:
    return [(c, r) for r, line in enumerate(grid) for c, x in enumerate(line) if x == ch]


def flood(grid, start: tuple[int, int], walkable: set[str]) -> set[tuple[int, int]]:
    seen = {start}
    q = deque([start])
    while q:
        col, row = q.popleft()
        for n in neighbours(grid, col, row, walkable):
            if n not in seen:
                seen.add(n)
                q.append(n)
    return seen


# --------------------------------------------------------------------------- tests
def test_dimensions(grid):
    assert len(grid) == 22, f"expected 22 rows, got {len(grid)}"
    for row, line in enumerate(grid):
        assert len(line) == 21, f"row {row} has {len(line)} columns, expected 21"


def test_horizontal_symmetry(grid):
    for row, line in enumerate(grid):
        assert line == line[::-1], f"row {row} is not symmetric: {line}"


def test_single_start(grid):
    assert len(find(grid, START)) == 1


def test_border_is_sealed_except_the_tunnel(grid):
    w, h = width(grid), len(grid)
    for col in range(w):
        assert at(grid, col, 0) == WALL, f"top border open at column {col}"
        assert at(grid, col, h - 1) == WALL, f"bottom border open at column {col}"
    for row in range(h):
        for col in (0, w - 1):
            ch = at(grid, col, row)
            assert ch in (WALL, TUNNEL, " "), f"side border at {col},{row} is {ch!r}"


def test_tunnel_is_a_pair_on_the_same_row(grid):
    tunnels = find(grid, TUNNEL)
    assert len(tunnels) == 2, f"expected exactly 2 tunnel mouths, got {len(tunnels)}"
    (c1, r1), (c2, r2) = tunnels
    assert r1 == r2, "tunnel mouths must share a row"
    assert {c1, c2} == {0, width(grid) - 1}, "tunnel mouths must be on the side borders"


def test_every_pellet_is_reachable_by_spain(grid):
    start = find(grid, START)[0]
    reachable = flood(grid, start, PAC_WALKABLE)
    missed = [p for ch in (PELLET, POWER) for p in find(grid, ch) if p not in reachable]
    assert not missed, f"unreachable pellets at {missed}"


def test_four_power_pellets(grid):
    assert len(find(grid, POWER)) == 4


def test_ghosts_can_leave_the_house_and_reach_spain(grid):
    house = find(grid, HOUSE)
    assert house, "no ghost house"
    reachable = flood(grid, house[0], WALKABLE)
    assert find(grid, START)[0] in reachable, "ghosts cannot reach Spain's start"
    door = find(grid, DOOR)
    assert len(door) == 1, f"expected exactly 1 door, got {len(door)}"
    assert door[0] in reachable, "the door is not connected to the house"


def test_spain_cannot_enter_the_house(grid):
    start = find(grid, START)[0]
    reachable = flood(grid, start, PAC_WALKABLE)
    for tile in find(grid, HOUSE) + find(grid, DOOR):
        assert tile not in reachable, f"Spain can walk into the house at {tile}"


def test_tunnel_connects_both_sides(grid):
    left, right = sorted(find(grid, TUNNEL))
    reachable = flood(grid, left, PAC_WALKABLE)
    assert right in reachable, "the tunnel mouths are not connected"


def test_there_are_junctions_to_decide_at(grid):
    start = find(grid, START)[0]
    reachable = flood(grid, start, PAC_WALKABLE)
    junctions = [t for t in reachable if len(list(neighbours(grid, *t, PAC_WALKABLE))) >= 3]
    assert len(junctions) >= 20, f"only {len(junctions)} junctions, the maze is too linear"
