CREATE TEMP TABLE worker_records AS
SELECT range AS id, repeat(md5(? || ':' || range::VARCHAR), 4) AS payload
FROM range(300000);
