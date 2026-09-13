-- Loop 1 schema (PLAN.md, Database schema, items marked L1).
-- Never stored, always derived: unit cost, CMV, available stock, budget remaining, scenarios, alerts, launch menu.

ALTER TABLE ingredients
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'food' CHECK (kind IN ('food', 'packaging'));

CREATE TABLE conversion_factors (
    id            BIGSERIAL PRIMARY KEY,
    ingredient_id BIGINT NOT NULL REFERENCES ingredients (id),
    measure       TEXT NOT NULL,
    amount_base   NUMERIC(14, 4) NOT NULL CHECK (amount_base > 0),
    amount_base_unit TEXT NOT NULL CHECK (amount_base_unit IN ('g', 'ml', 'unit')),
    evidence      TEXT NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX conversion_factors_one_current ON conversion_factors (ingredient_id, measure) WHERE superseded_at IS NULL;

CREATE TABLE kitchen_profile (
    requirement_key TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK (status IN ('available', 'unavailable')),
    numeric_value   NUMERIC NULL,
    evidence        TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- free-text requirements are confirmed per dish, never globally
    CHECK (requirement_key NOT LIKE 'other:%' AND requirement_key NOT LIKE 'gas_or_energy:%')
);

CREATE TABLE budget (
    id             SMALLINT PRIMARY KEY CHECK (id = 1),
    initial_amount NUMERIC(12, 2) NOT NULL DEFAULT 80.00
);
INSERT INTO budget (id) VALUES (1);

CREATE TABLE budget_adjustments (
    id         BIGSERIAL PRIMARY KEY,
    delta      NUMERIC(12, 2) NOT NULL CHECK (delta <> 0),
    evidence   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dishes (
    id                      BIGSERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    recipe                  JSONB NOT NULL,
    source_url              TEXT NOT NULL,
    yield_portions          INT NOT NULL CHECK (yield_portions > 0),
    launch_batch_portions   INT NOT NULL CHECK (launch_batch_portions > 0),
    packaging_ingredient_id BIGINT NULL REFERENCES ingredients (id),
    status                  TEXT NOT NULL CHECK (status IN ('candidate', 'accepted', 'rejected')),
    rejected_reason         TEXT NULL,
    selected_target_cmv_pct NUMERIC(4, 3) NULL,
    selected_price          NUMERIC(12, 2) NULL,
    evidence                TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at             TIMESTAMPTZ NULL,
    rejected_at             TIMESTAMPTZ NULL,
    CHECK ((status = 'rejected') = (rejected_reason IS NOT NULL)),
    CHECK (selected_price IS NULL OR status = 'accepted')
);

CREATE TABLE dish_requirements (
    dish_id               BIGINT NOT NULL REFERENCES dishes (id),
    requirement           TEXT NOT NULL,
    origin                TEXT NOT NULL CHECK (origin IN ('recipe', 'derived')),
    confirmation_status   TEXT NULL CHECK (confirmation_status IN ('available', 'unavailable')),
    confirmation_evidence TEXT NULL,
    confirmed_at          TIMESTAMPTZ NULL,
    PRIMARY KEY (dish_id, requirement),
    CHECK (confirmation_status IS NULL OR requirement LIKE 'other:%' OR requirement LIKE 'gas_or_energy:%')
);

-- "A food purchase requires dish_id" spans two tables: enforced in operations.register_purchase.
CREATE TABLE purchases (
    id                    BIGSERIAL PRIMARY KEY,
    ingredient_id         BIGINT NOT NULL REFERENCES ingredients (id),
    dish_id               BIGINT NULL REFERENCES dishes (id),
    packages              INT NOT NULL CHECK (packages > 0),
    package_quantity_base NUMERIC(14, 4) NOT NULL CHECK (package_quantity_base > 0),
    package_price         NUMERIC(12, 2) NOT NULL CHECK (package_price > 0),
    price_source          TEXT NOT NULL,
    source_url            TEXT NULL,
    evidence              TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dish_reservations (
    dish_id       BIGINT NOT NULL REFERENCES dishes (id),
    ingredient_id BIGINT NOT NULL REFERENCES ingredients (id),
    quantity_base NUMERIC(14, 4) NOT NULL CHECK (quantity_base > 0),
    PRIMARY KEY (dish_id, ingredient_id)
);

CREATE TABLE menu_copy (
    dish_id     BIGINT PRIMARY KEY REFERENCES dishes (id),
    title       VARCHAR(60) NOT NULL,
    description VARCHAR(250) NOT NULL,
    evidence    TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE promotions (
    id           BIGSERIAL PRIMARY KEY,
    dish_id      BIGINT NOT NULL REFERENCES dishes (id),
    description  VARCHAR(250) NOT NULL,
    discount_pct NUMERIC(4, 3) NOT NULL CHECK (discount_pct > 0 AND discount_pct < 1),
    evidence     TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pantry_imports (
    id          BIGSERIAL PRIMARY KEY,
    file_path   TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    diff        JSONB NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('previewed', 'applied', 'failed')),
    error       JSONB NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at  TIMESTAMPTZ NULL
);

CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    agent      TEXT NOT NULL,
    tool       TEXT NOT NULL,
    args       JSONB NOT NULL,
    result     JSONB NULL,
    error_code TEXT NULL,
    trace_id   TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_trace_id ON audit_log (trace_id);

CREATE VIEW available_stock AS
SELECT i.id AS ingredient_id,
       i.name,
       i.base_unit,
       COALESCE(s.quantity_base, 0)
         + COALESCE((SELECT sum(p.packages * p.package_quantity_base) FROM purchases p WHERE p.ingredient_id = i.id), 0)
         - COALESCE((SELECT sum(r.quantity_base) FROM dish_reservations r WHERE r.ingredient_id = i.id), 0)
         AS quantity_base
FROM ingredients i
LEFT JOIN pantry_stock s ON s.ingredient_id = i.id;

CREATE VIEW budget_status AS
SELECT b.initial_amount,
       COALESCE((SELECT sum(delta) FROM budget_adjustments), 0) AS adjustments_total,
       COALESCE((SELECT sum(packages * package_price) FROM purchases), 0) AS purchases_total,
       b.initial_amount
         + COALESCE((SELECT sum(delta) FROM budget_adjustments), 0)
         - COALESCE((SELECT sum(packages * package_price) FROM purchases), 0) AS remaining
FROM budget b;
