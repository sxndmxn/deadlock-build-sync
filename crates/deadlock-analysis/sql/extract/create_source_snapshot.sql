CREATE OR REPLACE TABLE source_snapshot AS
SELECT $version::BIGINT AS "version";
