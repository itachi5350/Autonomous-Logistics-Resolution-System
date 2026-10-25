CREATE TABLE customers (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE products (
    sku       TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    price_inr INTEGER NOT NULL CHECK (price_inr >= 0)
);

CREATE TABLE orders (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    sku             TEXT NOT NULL REFERENCES products(sku),
    order_value_inr INTEGER NOT NULL CHECK (order_value_inr >= 0),
    amount_paid_inr INTEGER NOT NULL CHECK (amount_paid_inr >= 0),  -- money actually collected
    payment_method  TEXT NOT NULL CHECK (payment_method IN ('PREPAID', 'COD')),
    status          TEXT NOT NULL DEFAULT 'shipped'
);

CREATE TABLE shipments (
    tracking_id   TEXT PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(id),
    status        TEXT NOT NULL,
    last_event_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE inventory (
    sku       TEXT NOT NULL REFERENCES products(sku),
    warehouse TEXT NOT NULL,
    quantity  INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (sku, warehouse)
);

-- Used from Phase 1 onwards
CREATE TABLE shipping_events (
    event_id    TEXT PRIMARY KEY,
    tracking_id TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cases (
    id                TEXT PRIMARY KEY,
    tracking_id       TEXT NOT NULL,
    status            TEXT NOT NULL,
    decision          JSONB,
    action_amount_inr INTEGER,
    options           JSONB,
    custumer_choice   TEXT,
    customer_replied_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at         TIMESTAMPTZ
);

CREATE TABLE approvals (
    case_id    TEXT PRIMARY KEY REFERENCES cases(id),
    status     TEXT NOT NULL,
    approver   TEXT,
    comment    TEXT,
    decided_at TIMESTAMPTZ
);

CREATE TABLE actions (
    id              SERIAL PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    action_type     TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    api_result      JSONB,
    attempts        INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS options JSONB,
    ADD COLUMN IF NOT EXISTS customer_message TEXT,
    ADD COLUMN IF NOT EXISTS customer_choice TEXT,
    ADD COLUMN IF NOT EXISTS customer_replied_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reply_token TEXT,
    ADD COLUMN IF NOT EXISTS approval_token TEXT,
    ADD COLUMN IF NOT EXISTS final_action TEXT;

