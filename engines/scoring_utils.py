from __future__ import annotations


def strength(score: float) -> str:
    if score >= 90:
        return "Very High"
    if score >= 75:
        return "High"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "Monitor"
    return "Low"
