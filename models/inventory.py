from dataclasses import dataclass


@dataclass(slots=True)
class Inventory:
    product_id: str
    quantity_on_hand: float
    reorder_threshold: float = 0.0
