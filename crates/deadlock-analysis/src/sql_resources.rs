/// Includes `sql/NAME.sql` at compile time. A missing file stops the build.
macro_rules! sql {
    ($name:literal) => {
        include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/sql/", $name, ".sql"))
    };
}

pub(crate) use sql;
