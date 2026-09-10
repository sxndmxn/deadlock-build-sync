SELECT count(*) FROM worker_records
WHERE payload != repeat(md5(? || ':' || id::VARCHAR), 4);
