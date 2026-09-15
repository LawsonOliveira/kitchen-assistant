-- Household measures in the database (PLAN.md PL6): the D23 table as seed rows, measures recipe_expert found on the web
-- (never used in CMV until the owner confirms them, like price estimates in D27) and her confirmations.
CREATE TABLE measures (
    id               BIGSERIAL PRIMARY KEY,
    measure          TEXT NOT NULL,
    ingredient_name  TEXT NULL,  -- NULL: applies to any ingredient
    amount_base      NUMERIC(14, 4) NOT NULL CHECK (amount_base > 0),
    amount_base_unit TEXT NOT NULL CHECK (amount_base_unit IN ('g', 'ml')),
    source           TEXT NOT NULL CHECK (source IN ('seed', 'web_estimate', 'owner_confirmed')),
    source_url       TEXT NULL,
    evidence         TEXT NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at    TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX measures_one_current ON measures (measure, coalesce(ingredient_name, '')) WHERE superseded_at IS NULL;

INSERT INTO measures (measure, ingredient_name, amount_base, amount_base_unit, source, evidence) VALUES
    ('cup', 'Farinha de trigo', 120, 'g', 'seed', 'PLAN.md D23 table'),
    ('cup', 'Arroz branco tipo 1', 185, 'g', 'seed', 'PLAN.md D23 table'),
    ('cup', 'Açúcar', 180, 'g', 'seed', 'PLAN.md D23 table'),
    ('cup', 'Leite integral', 240, 'ml', 'seed', 'PLAN.md D23 table'),
    ('tablespoon', 'Manteiga', 15, 'g', 'seed', 'PLAN.md D23 table'),
    ('tablespoon', 'Óleo de soja', 15, 'ml', 'seed', 'PLAN.md D23 table'),
    ('tablespoon', NULL, 15, 'ml', 'seed', 'PLAN.md D23 table'),
    ('teaspoon', NULL, 5, 'ml', 'seed', 'PLAN.md D23 table'),
    ('clove', 'Alho', 5, 'g', 'seed', 'PLAN.md D23 table'),
    ('pinch', NULL, 1, 'g', 'seed', 'PLAN.md D23 table'),
    ('drizzle', NULL, 5, 'ml', 'seed', 'PLAN.md D23 table'),
    ('to_taste', NULL, 1, 'g', 'seed', 'PLAN.md D23 table'),
    ('can', 'Creme de leite', 200, 'g', 'seed', 'PLAN.md D23 table'),
    ('can', 'Leite condensado', 395, 'g', 'seed', 'PLAN.md D23 table'),
    ('can', 'Milho verde', 170, 'g', 'seed', 'PLAN.md D23 table'),
    ('can', 'Extrato de tomate', 340, 'g', 'seed', 'PLAN.md D23 table');
