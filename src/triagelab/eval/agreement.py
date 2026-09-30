"""Agreement between two raters, written by hand (AGENTS.md §7.5, §12.4).

- `cohen_kappa`: agreement on nominal categories beyond what chance predicts,
  kappa = (p_o - p_e) / (1 - p_e). Used for silver-vs-gold labels, per task.
- `weighted_kappa`: the same for ordered scores, where near-misses count partly.
  Quadratic weights (i - j)^2 / (k - 1)^2 are the convention for rubric scores, so
  judge-vs-human agreement on a 1-4 scale is reported with it.
- `exact_agreement` / `adjacent_agreement`: the plain rates that make kappa readable.

Kappa is undefined when chance agreement is already perfect (both raters always give
the same single answer); these functions return None then instead of dividing by zero.
"""

from collections import Counter
from collections.abc import Hashable, Sequence


def _paired[T](a: Sequence[T], b: Sequence[T]) -> None:
    if len(a) != len(b):
        raise ValueError(f"raters must rate the same items: {len(a)} vs {len(b)}")


def cohen_kappa[T: Hashable](a: Sequence[T], b: Sequence[T]) -> float | None:
    _paired(a, b)
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    chance = sum(count_a[c] * count_b[c] for c in count_a) / (n * n)
    if chance == 1.0:
        return None
    return (observed - chance) / (1.0 - chance)


def weighted_kappa(a: Sequence[int], b: Sequence[int], categories: Sequence[int]) -> float | None:
    """Quadratic-weighted kappa over ordered `categories` (e.g. 1, 2, 3, 4)."""
    _paired(a, b)
    n, k = len(a), len(categories)
    if n == 0 or k < 2:
        return None
    index = {c: i for i, c in enumerate(categories)}
    unknown = (set(a) | set(b)) - set(index)
    if unknown:
        raise ValueError(f"scores outside the categories: {sorted(unknown)}")

    def weight(i: int, j: int) -> float:
        return (i - j) ** 2 / (k - 1) ** 2

    observed = sum(weight(index[x], index[y]) for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(index[x] for x in a), Counter(index[y] for y in b)
    chance_pairs = sum(weight(i, j) * count_a[i] * count_b[j] for i in range(k) for j in range(k))
    expected = chance_pairs / (n * n)
    if expected == 0.0:
        return None
    return 1.0 - observed / expected


def exact_agreement[T](a: Sequence[T], b: Sequence[T]) -> float | None:
    _paired(a, b)
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a) if a else None


def adjacent_agreement(a: Sequence[int], b: Sequence[int], tolerance: int = 1) -> float | None:
    """Share of items where the two scores differ by at most `tolerance`."""
    _paired(a, b)
    return sum(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True)) / len(a) if a else None
