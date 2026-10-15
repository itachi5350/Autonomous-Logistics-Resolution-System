import os
from datetime import datetime, timedelta, timezone
import psycopg
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://logistics:logistics@localhost:5433/logistics")
NOW = datetime.now(timezone.utc)

CUSTOMERS = [
    (1, "Aarav Mehta", "aarav@example.com"),
    (2, "Diya Nair", "diya@example.com"),
    (3, "Kabir Singh", "kabir@example.com"),
    (4, "Ishita Rao", "ishita@example.com"),
]
PRODUCTS = [
    ("MBP-14", "MacBook Pro 14-inch", 150000),
    ("MOUSE-01", "Wireless Mouse", 1499),
    ("HEAD-NC", "Noise-Cancelling Headphones", 8999),
    ("CASE-01", "Phone Case", 499),
]
ORDERS = [  # id, customer_id, sku, order_value_inr, amount_paid_inr, payment_method
    (1, 1, "MBP-14",   150000, 150000, "PREPAID"),
    (2, 2, "MOUSE-01",   1499,   1499, "PREPAID"),
    (3, 3, "HEAD-NC",    8999,   8999, "PREPAID"),
    (4, 4, "CASE-01",     499,      0, "COD"),
    (5, 2, "MOUSE-01",   1499,      0, "COD"),
    (6, 3, "MBP-14",   150000,      0, "COD"),
]
SHIPMENTS = [  # tracking_id, order_id, status, hours since last event
    ("TRK991", 4, "at_hub", 2),        # healthy package (ignored)
    ("TRK992", 1, "in_transit", 73),   # prepaid MacBook stuck
    ("TRK993", 2, "in_transit", 75),   # prepaid mouse stuck
    ("TRK994", 3, "in_transit", 80),   # prepaid headphones, out of stock in Bengaluru
    ("TRK995", 5, "in_transit", 76),   # COD mouse stuck
    ("TRK996", 6, "in_transit", 78),   # COD MacBook stuck
]
INVENTORY = [
    ("MBP-14", "Bengaluru", 3),
    ("MBP-14", "Mumbai", 1),
    ("MOUSE-01", "Bengaluru", 50),
    ("HEAD-NC", "Bengaluru", 0),
    ("HEAD-NC", "Mumbai", 2),
    ("CASE-01", "Bengaluru", 200),
]

with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
    cur.execute(
        "TRUNCATE approvals, actions, cases, shipping_events, inventory, shipments, "
        "orders, products, customers RESTART IDENTITY CASCADE"
    )
    cur.executemany("INSERT INTO customers (id, name, email) VALUES (%s, %s, %s)", CUSTOMERS)
    cur.executemany("INSERT INTO products (sku, name, price_inr) VALUES (%s, %s, %s)", PRODUCTS)
    cur.executemany(
        "INSERT INTO orders (id, customer_id, sku, order_value_inr, amount_paid_inr, payment_method) VALUES (%s, %s, %s, %s, %s, %s)",
        ORDERS
    )
    cur.executemany(
        "INSERT INTO shipments (tracking_id, order_id, status, last_event_at) VALUES (%s, %s, %s, %s)",
        [(t, o, s, NOW - timedelta(hours=h)) for t, o, s, h in SHIPMENTS],
    )
    cur.executemany("INSERT INTO inventory (sku, warehouse, quantity) VALUES (%s, %s, %s)", INVENTORY)
    cur.execute("SELECT setval('customers_id_seq', (SELECT MAX(id) FROM customers))")
    cur.execute("SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders))")
    conn.commit()
print("Seeded 4 customers, 4 products, 6 orders, 6 shipments.")