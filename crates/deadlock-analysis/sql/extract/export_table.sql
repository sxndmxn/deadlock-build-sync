-- The export uses the schema of the table supplied through a bound parameter.
COPY (SELECT * FROM query_table($table)) TO $path ( -- noqa: AM04
    FORMAT parquet,
    COMPRESSION zstd,
    ROW_GROUP_SIZE 100000
);
