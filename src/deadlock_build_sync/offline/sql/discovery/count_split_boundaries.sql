SELECT count(*) FROM information_schema."tables"
WHERE
    table_catalog = current_database()
    AND table_schema = current_schema()
    AND table_name = 'split_boundaries';
