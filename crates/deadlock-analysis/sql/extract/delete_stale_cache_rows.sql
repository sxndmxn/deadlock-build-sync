-- The cache drops the files that left the remote catalog,
-- and the rows of an interrupted copy, which has no row in remote_cache.files.
DELETE FROM remote_cache.files
WHERE data_file NOT IN (SELECT data_file FROM remote_files);

DELETE FROM remote_cache.players
WHERE data_file NOT IN (SELECT data_file FROM remote_cache.files);
