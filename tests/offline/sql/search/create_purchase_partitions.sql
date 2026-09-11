ALTER TABLE first_purchases ADD COLUMN player_slot INTEGER DEFAULT 0;
ALTER TABLE first_purchases ADD COLUMN fold VARCHAR DEFAULT 'train';
CREATE TABLE experiment_matches AS
SELECT match_id FROM discovery_partitions
WHERE "partition" = 'discovery';
