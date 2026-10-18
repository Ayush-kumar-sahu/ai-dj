"""Sequence a set of tracks into the running order with the smoothest transitions.

This is an asymmetric Hamiltonian *path* problem: mixing A→B is not the same cost as
B→A (the BPM stretch is measured against A, and only A needs an outro). Exact solving
is overkill for a DJ set, so: greedy nearest-neighbour seeded from every possible
opener, then improved with relocate + reverse moves until nothing gets better.
"""

from __future__ import annotations

import numpy as np

from . import compatibility
from .types import TrackAnalysis

MAX_PASSES = 40


def cost_matrix(tracks: list[TrackAnalysis]) -> np.ndarray:
    """M[i][j] = cost of mixing tracks[i] into tracks[j]. Lower is better."""
    n = len(tracks)
    m = np.full((n, n), np.inf, dtype=np.float64)
    for i in range(n):
        for j in range(n):
            if i != j:
                m[i, j] = compatibility.score(tracks[i], tracks[j])[0]
    return m


def path_cost(order: list[int], m: np.ndarray) -> float:
    return float(sum(m[a, b] for a, b in zip(order, order[1:])))


def optimal_order(tracks: list[TrackAnalysis],
                  fixed_start: int | None = None) -> tuple[list[int], float]:
    """Return (indices in mix order, total transition cost)."""
    n = len(tracks)
    if n < 3:
        return list(range(n)), 0.0

    m = cost_matrix(tracks)
    starts = [fixed_start] if fixed_start is not None else range(n)

    best_order, best_cost = None, np.inf
    for start in starts:
        order = _greedy(start, n, m)
        order = _improve(order, m, fixed_start is not None)
        cost = path_cost(order, m)
        if cost < best_cost:
            best_order, best_cost = order, cost

    assert best_order is not None
    return best_order, best_cost


def _greedy(start: int, n: int, m: np.ndarray) -> list[int]:
    order = [start]
    remaining = set(range(n)) - {start}
    while remaining:
        current = order[-1]
        nxt = min(remaining, key=lambda j: m[current, j])
        order.append(nxt)
        remaining.discard(nxt)
    return order


def _improve(order: list[int], m: np.ndarray, keep_start: bool) -> list[int]:
    """Local search over relocate + reverse moves.

    Both moves change edge directions, so costs are recomputed in full rather than
    with the symmetric-TSP delta trick — correctness matters more than speed at n<50.
    """
    best = list(order)
    best_cost = path_cost(best, m)
    first_movable = 1 if keep_start else 0

    for _ in range(MAX_PASSES):
        improved = False
        for cand in _neighbours(best, first_movable):
            cost = path_cost(cand, m)
            if cost < best_cost - 1e-9:
                best, best_cost, improved = cand, cost, True
        if not improved:
            break
    return best


def _neighbours(order: list[int], first_movable: int):
    n = len(order)
    # relocate: pull one track out and drop it somewhere else
    for i in range(first_movable, n):
        for j in range(first_movable, n):
            if i == j:
                continue
            cand = order[:i] + order[i + 1:]
            cand.insert(j, order[i])
            yield cand
    # reverse: flip a run of tracks
    for i in range(first_movable, n - 1):
        for j in range(i + 2, n + 1):
            yield order[:i] + order[i:j][::-1] + order[j:]
