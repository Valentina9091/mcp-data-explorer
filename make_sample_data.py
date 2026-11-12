"""Generate a small e-commerce dataset with deliberately planted data-quality problems,
so the data_quality_report tool has something to find."""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
out = Path(__file__).parent / "data"
out.mkdir(exist_ok=True)

regions = ["North", "South", "East", "West"]
segments = ["consumer", "smb", "enterprise"]
products = {"Laptop": 1200, "Monitor": 300, "Keyboard": 80, "Mouse": 40, "Dock": 220, "Headset": 150}

customers = []
for i in range(1, 501):
    customers.append({
        "customer_id": i,
        "region": random.choice(regions),
        "segment": random.choices(segments, [0.6, 0.3, 0.1])[0],
        "signup_date": (date(2023, 1, 1) + timedelta(days=random.randint(0, 900))).isoformat(),
        # planted: ~8% missing emails
        "email": "" if random.random() < 0.08 else f"user{i}@example.com",
    })
customers.append(dict(customers[10]))  # planted: one exact duplicate row

orders = []
for i in range(1, 5001):
    prod = random.choice(list(products))
    qty = random.choices([1, 2, 3, 5], [0.7, 0.2, 0.07, 0.03])[0]
    price = round(products[prod] * random.uniform(0.85, 1.1), 2)
    orders.append({
        "order_id": i,
        "customer_id": random.randint(1, 500),
        "order_date": (date(2025, 1, 1) + timedelta(days=random.randint(0, 300))).isoformat(),
        "product": prod,
        "quantity": qty,
        "unit_price": price,
        "discount_pct": random.choice([0, 0, 0, 5, 10, 15]),
    })
# planted problems
for o in random.sample(orders, 6):
    o["unit_price"] = round(o["unit_price"] * 40, 2)          # fat-finger outliers
for o in random.sample(orders, 4):
    o["quantity"] = -o["quantity"]                             # returns booked as negatives
for o in random.sample(orders, 3):
    o["order_date"] = "2027-03-01"                             # future dates
orders[100]["order_id"] = orders[99]["order_id"]               # duplicate key

for name, rows in [("customers", customers), ("orders", orders)]:
    with open(out / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
print(f"wrote {len(customers)} customers and {len(orders)} orders to {out}")
