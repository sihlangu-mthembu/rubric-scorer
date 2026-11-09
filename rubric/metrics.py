"""Agreement metrics, adapted from annotation-qa-metrics (same author)."""

from collections import Counter
from itertools import combinations


def percent_agreement(a: list[str], b: list[str]) -> float:
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Agreement between two reviewers corrected for chance: (observed - expected) / (1 - expected)."""
    n = len(a)
    observed = percent_agreement(a, b)
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(a) | set(b)) / (n * n)
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def interpret_kappa(kappa: float) -> str:
    """Landis & Koch (1977) bands."""
    for limit, name in [(0.0, "poor"), (0.20, "slight"), (0.40, "fair"), (0.60, "moderate"), (0.80, "substantial")]:
        if kappa <= limit:
            return name
    return "almost perfect"


def pairwise_agreement(labels_by_reviewer: dict[str, dict[int, str]], min_shared: int = 2) -> list[dict]:
    """For every pair of reviewers, compare labels on the items both scored."""
    rows = []
    for r1, r2 in combinations(sorted(labels_by_reviewer), 2):
        shared = sorted(set(labels_by_reviewer[r1]) & set(labels_by_reviewer[r2]))
        if len(shared) < min_shared:
            continue
        a = [labels_by_reviewer[r1][i] for i in shared]
        b = [labels_by_reviewer[r2][i] for i in shared]
        k = cohens_kappa(a, b)
        rows.append({"pair": f"{r1} vs {r2}", "shared": len(shared),
                     "agreement": percent_agreement(a, b), "kappa": k, "band": interpret_kappa(k)})
    return rows
