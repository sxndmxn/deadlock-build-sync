-- The largest files start first, so that no large file starts at the end.
SELECT r.data_file
FROM remote_files AS r
WHERE r.data_file NOT IN (SELECT c.data_file FROM remote_cache.files AS c)
ORDER BY r.data_file_size_bytes DESC, r.data_file ASC;
