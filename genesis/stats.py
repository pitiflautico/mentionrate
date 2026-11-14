"""Estadística mínima y determinista para proporciones."""
from __future__ import annotations

import math

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción k/n. Con n=0 no se sabe nada: (0, 1)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate_diff(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float, float]:
    """Diferencia p2 - p1 con su intervalo de Newcombe (combina dos Wilson).

    Devuelve (diferencia, límite inferior, límite superior).
    """
    if n1 <= 0 or n2 <= 0:
        return (0.0, -1.0, 1.0)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    d = p2 - p1
    low = d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    high = d + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    return (d, max(-1.0, low), min(1.0, high))


def f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Devuelve (precisión, exhaustividad, F1). Sin positivos predichos ni reales, 0."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return (precision, recall, score)
