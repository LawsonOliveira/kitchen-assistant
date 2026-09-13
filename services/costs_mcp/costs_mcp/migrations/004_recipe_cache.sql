-- Researched recipes reused across rounds and conversations (PLAN.md PL8): looked up by normalized title words first;
-- pgvector only if semantic matching proves necessary. Only web recipes with provenance are cached, never the owner's.
CREATE TABLE recipe_cache (
    id              BIGSERIAL PRIMARY KEY,
    source_url      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    recipe          JSONB NOT NULL,
    query           TEXT NOT NULL,
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
