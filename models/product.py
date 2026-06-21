from dataclasses import dataclass


@dataclass(slots=True)
class Product:
    product_id: str
    product_name: str
    category: str = ""
