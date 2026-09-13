-- Loop 0 schema (PLAN.md, Database schema, items marked L0).

CREATE TABLE IF NOT EXISTS schema_version (
    version    INT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingredients (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    base_unit  TEXT NOT NULL CHECK (base_unit IN ('g', 'ml', 'unit')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spreadsheet stock only; purchases never mutate it.
CREATE TABLE pantry_stock (
    ingredient_id BIGINT PRIMARY KEY REFERENCES ingredients (id),
    quantity_base NUMERIC(14, 4) NOT NULL CHECK (quantity_base >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingredient_prices (
    id                      BIGSERIAL PRIMARY KEY,
    ingredient_id           BIGINT NOT NULL REFERENCES ingredients (id),
    total_price_paid        NUMERIC(12, 2) NOT NULL CHECK (total_price_paid > 0),
    quantity_purchased_base NUMERIC(14, 4) NOT NULL CHECK (quantity_purchased_base > 0),
    purchase_unit_label     TEXT NOT NULL,
    source                  TEXT NOT NULL CHECK (source IN ('spreadsheet', 'web_estimate', 'owner_confirmed')),
    source_url              TEXT NULL,
    evidence                TEXT NULL,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at           TIMESTAMPTZ NULL
);

-- Exactly one current price per ingredient (latest-price rule).
CREATE UNIQUE INDEX ingredient_prices_one_current ON ingredient_prices (ingredient_id) WHERE superseded_at IS NULL;

CREATE VIEW current_ingredient_prices AS
SELECT * FROM ingredient_prices WHERE superseded_at IS NULL;
