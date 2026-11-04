"""Load the CSV files, clean them, and report data-quality problems.

The CSVs are small (65 products, 19 orders), so the standard library is enough.
No pandas, no database. Everything is loaded once into plain dataclasses.

Run `python -m emporio.data` to print the data-quality report.
"""
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR
from .text import fold


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    price: float
    category_id: int
    category: str
    description: str
    stock: int
    status: str  # active | discontinued | coming_soon
    specs: dict

    @property
    def available(self) -> bool:
        """Can the customer buy it today? Only active AND in stock.

        Note: a few rows say coming_soon or discontinued but still have stock.
        The manual (7.3) says to treat those as not available, so status wins.
        """
        return self.status == "active" and self.stock > 0


@dataclass(frozen=True)
class Promotion:
    id: int
    product_id: int
    discount_percent: float
    name: str
    active: bool


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str


@dataclass(frozen=True)
class Order:
    id: int
    customer_id: int
    date: str  # ISO date
    status: str  # pending | confirmed | shipped | delivered | cancelled
    total: float
    payment_method: str
    tracking_code: str | None
    estimated_delivery: str | None
    notes: str | None
    items: tuple  # ((product_id, quantity), ...)


@dataclass
class Store:
    products: dict[int, Product]
    categories: dict[int, str]
    promotions: list[Promotion]
    customers: dict[int, Customer]
    orders: dict[int, Order]
    issues: list[str] = field(default_factory=list)

    def active_promotion(self, product_id: int) -> Promotion | None:
        """The best active promotion. Promotions are not cumulative (manual 6.2)."""
        active = [p for p in self.promotions if p.active and p.product_id == product_id]
        return max(active, key=lambda p: p.discount_percent, default=None)


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Strip spaces and turn empty cells into None.
    return [{k.strip(): (v.strip() or None) if v is not None else None for k, v in r.items()} for r in rows]


def load_store(data_dir: Path = DATA_DIR) -> Store:
    issues: list[str] = []

    categories = {int(r["category_id"]): r["name"] for r in _read(data_dir / "categories.csv")}

    products = {}
    for r in _read(data_dir / "products.csv"):
        try:
            specs = json.loads(r["specs"]) if r["specs"] else {}
        except json.JSONDecodeError:
            specs = {}
            issues.append(f"Product {r['product_id']}: specs is not valid JSON (ignored).")
        p = Product(
            id=int(r["product_id"]),
            name=r["name"],
            price=float(r["price_brl"]),
            category_id=int(r["category_id"]),
            category=categories.get(int(r["category_id"]), "Sem categoria"),
            description=r["description"] or "",
            stock=int(r["stock_quantity"]),
            status=r["status"],
            specs=specs,
        )
        products[p.id] = p

    promotions = [
        Promotion(int(r["promotion_id"]), int(r["product_id"]), float(r["discount_percent"]),
                  r["description"], r["is_active"] == "1")
        for r in _read(data_dir / "promotions.csv")
    ]

    customers = {
        int(r["customer_id"]): Customer(int(r["customer_id"]), r["name"], r["phone"], r["email"], r["city"])
        for r in _read(data_dir / "customers.csv")
    }

    items: dict[int, list] = {}
    for r in _read(data_dir / "order_items.csv"):
        items.setdefault(int(r["order_id"]), []).append((int(r["product_id"]), int(r["quantity"])))

    orders = {}
    for r in _read(data_dir / "orders.csv"):
        oid = int(r["order_id"])
        orders[oid] = Order(oid, int(r["customer_id"]), r["order_date"], r["status"], float(r["total_brl"]),
                            r["payment_method"], r["tracking_code"], r["estimated_delivery"], r["notes"],
                            tuple(items.get(oid, [])))

    store = Store(products, categories, promotions, customers, orders, issues)
    issues.extend(check_quality(store))
    return store


def check_quality(store: Store) -> list[str]:
    """Look for problems in the data. We report them. We do not silently 'fix' them."""
    found = []

    for o in store.orders.values():
        calc = sum(store.products[pid].price * qty for pid, qty in o.items)
        if o.items and abs(calc - o.total) > 0.01:
            found.append(f"Order {o.id}: total {o.total:.2f} differs from the sum of items {calc:.2f}. "
                         f"We show the recorded total and never recompute it.")
        if o.customer_id not in store.customers:
            found.append(f"Order {o.id}: customer {o.customer_id} does not exist.")
        for pid, _ in o.items:
            if store.products[pid].status != "active":
                found.append(f"Order {o.id}: contains product {pid} with status "
                             f"'{store.products[pid].status}'.")

    for p in store.products.values():
        if p.status in ("coming_soon", "discontinued") and p.stock > 0:
            found.append(f"Product {p.id} ({p.name}): status '{p.status}' but stock is {p.stock}. "
                         f"We treat it as NOT available.")

    for cid, name in store.categories.items():
        if not any(p.category_id == cid for p in store.products.values()):
            found.append(f"Category '{name}' exists but has no products.")

    seen: dict[str, int] = {}
    for c in store.customers.values():
        key = fold(c.email)
        if key in seen:
            found.append(f"Customers {seen[key]} and {c.id} share the e-mail {c.email}.")
        seen[key] = c.id

    for pr in store.promotions:
        if pr.active and pr.product_id not in store.products:
            found.append(f"Promotion {pr.id}: product {pr.product_id} does not exist.")

    missing_tracking = [o.id for o in store.orders.values()
                        if o.status in ("shipped", "delivered") and not o.tracking_code]
    if missing_tracking:
        found.append(f"Shipped/delivered orders without tracking code: {missing_tracking}.")

    found.append("Orders have only an ESTIMATED delivery date, never the real one. "
                 "Return windows count from the real delivery, so the agent must say this.")
    found.append("Promotions have no start/end dates. The is_active flag is our only source of truth.")
    return found


if __name__ == "__main__":
    s = load_store()
    print(f"{len(s.products)} products, {len(s.orders)} orders, {len(s.customers)} customers, "
          f"{sum(p.active for p in s.promotions)} active promotions\n")
    for line in s.issues:
        print("-", line)
