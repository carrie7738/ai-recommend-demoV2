from __future__ import annotations


HIGH_STRENGTH_SCORE = 75


def strength(score: float) -> str:
    """Map a 0-100 score to a recommendation strength label.

    Note: "Monitor" is a low-strength "observe" tier, not an action command.
    It means the product is worth watching but not urgently recommended.
    """
    if score >= 90:
        return "Very High"
    if score >= HIGH_STRENGTH_SCORE:
        return "High"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "Monitor"
    return "Low"
