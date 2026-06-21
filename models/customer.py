from dataclasses import dataclass


@dataclass(slots=True)
class Customer:
    customer_id: str
    customer_name: str
    segment: str = ""
