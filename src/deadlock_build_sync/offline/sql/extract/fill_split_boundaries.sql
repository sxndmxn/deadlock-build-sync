UPDATE split_boundaries SET
    discovery_end=coalesce(discovery_end, $discovery_end),
    train_end=coalesce(train_end, $train_end), validation_end=coalesce(validation_end, $validation_end);
