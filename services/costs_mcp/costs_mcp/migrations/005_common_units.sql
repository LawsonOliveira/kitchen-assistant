-- The units her own pantry uses (PLAN.md C77, latency pass). Every measure missing from the table becomes a question to
-- Dona Maria, and sometimes a web lookup, in the middle of a recipe. These are standard Brazilian sizes for the
-- ingredients of her spreadsheet; she can still correct any of them, and her answer supersedes the seed.
INSERT INTO measures (measure, ingredient_name, amount_base, amount_base_unit, source, evidence) VALUES
    ('unit', 'Cebola', 150, 'g', 'seed', 'cebola média, tabela usual brasileira'),
    ('unit', 'Tomate', 120, 'g', 'seed', 'tomate médio, tabela usual brasileira'),
    ('unit', 'Batata', 150, 'g', 'seed', 'batata média, tabela usual brasileira'),
    ('unit', 'Ovos', 50, 'g', 'seed', 'ovo grande sem casca, tabela usual brasileira'),
    ('unit', 'Peito de frango', 180, 'g', 'seed', 'filé de peito, tabela usual brasileira'),
    ('cup', 'Feijão carioquinha', 180, 'g', 'seed', 'xícara de feijão cru, tabela usual brasileira'),
    ('cup', 'Feijão preto', 180, 'g', 'seed', 'xícara de feijão cru, tabela usual brasileira'),
    ('cup', 'Macarrão espaguete', 100, 'g', 'seed', 'xícara de macarrão cru, tabela usual brasileira'),
    ('cup', 'Farinha de mandioca', 120, 'g', 'seed', 'xícara de farinha, tabela usual brasileira'),
    ('cup', 'Polenta (fubá)', 130, 'g', 'seed', 'xícara de fubá, tabela usual brasileira'),
    ('tablespoon', 'Queijo parmesão ralado', 10, 'g', 'seed', 'colher de sopa cheia, tabela usual brasileira'),
    ('tablespoon', 'Azeite de oliva extra virgem', 13, 'ml', 'seed', 'colher de sopa, tabela usual brasileira');
