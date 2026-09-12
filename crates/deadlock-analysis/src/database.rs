use std::collections::BTreeMap;
use std::path::Path;
use std::time::Duration;

use deadlock_data::{Error, Result, trace_operation};
use duckdb::{Connection, ToSql, types::Value as SqlValue};
use serde::de::DeserializeOwned;
use serde_json::Value;

pub type Parameters = BTreeMap<String, SqlValue>;

#[derive(Debug)]
pub struct AnalysisDatabase {
    connection: Connection,
}

impl AnalysisDatabase {
    pub fn open(path: &Path) -> Result<Self> {
        Ok(Self {
            connection: Connection::open(path).map_err(|error| database_error(&error))?,
        })
    }

    pub fn open_read_only(path: &Path, temporary: &Path) -> Result<Self> {
        std::fs::create_dir_all(temporary)?;
        let configuration = duckdb::Config::default()
            .access_mode(duckdb::AccessMode::ReadOnly)
            .map_err(|error| database_error(&error))?
            .threads(1)
            .map_err(|error| database_error(&error))?
            .max_memory("512MiB")
            .map_err(|error| database_error(&error))?
            .with("temp_directory", temporary.to_string_lossy())
            .map_err(|error| database_error(&error))?;
        Ok(Self {
            connection: Connection::open_with_flags(path, configuration)
                .map_err(|error| database_error(&error))?,
        })
    }

    pub fn execute(&self, sql: &str, parameters: &Parameters) -> Result<()> {
        trace_operation("analysis.database.execute", None, || {
            if parameters.is_empty() {
                self.connection
                    .execute_batch(sql)
                    .map_err(|error| database_error(&error))?;
            } else {
                self.connection
                    .execute(sql, parameter_references(parameters).as_slice())
                    .map_err(|error| database_error(&error))?;
            }
            Ok(())
        })
    }

    pub fn execute_remote(&self, sql: &str, parameters: &Parameters) -> Result<()> {
        for attempt in 0..4 {
            match self.execute(sql, parameters) {
                Ok(()) => return Ok(()),
                Err(error) if attempt < 3 && retryable(&error) => {
                    let delay = 1 << attempt;
                    eprintln!("Remote snapshot data is unavailable. Retry after {delay} seconds");
                    std::thread::sleep(Duration::from_secs(delay));
                }
                Err(error) => return Err(error),
            }
        }
        Err(Error::new("Remote query has no remaining attempts"))
    }

    pub fn count(&self, sql: &str, parameters: &Parameters) -> Result<u64> {
        self.connection
            .query_row(sql, parameter_references(parameters).as_slice(), |row| {
                row.get(0)
            })
            .map_err(|error| database_error(&error))
    }

    pub fn query(&self, sql: &str, parameters: &Parameters) -> Result<Vec<Value>> {
        self.query_rows(sql, parameters)
    }

    pub fn query_rows<T: DeserializeOwned>(
        &self,
        sql: &str,
        parameters: &Parameters,
    ) -> Result<Vec<T>> {
        let mut rows = Vec::new();
        self.visit_rows(sql, parameters, |row| {
            rows.push(row);
            Ok(())
        })?;
        Ok(rows)
    }

    pub fn visit_rows<T: DeserializeOwned>(
        &self,
        sql: &str,
        parameters: &Parameters,
        mut visit: impl FnMut(T) -> Result<()>,
    ) -> Result<()> {
        trace_operation("analysis.database.query", None, || {
            let query = format!(
                "SELECT to_json(result) FROM ({}) AS result",
                sql.trim().trim_end_matches(';')
            );
            let mut statement = self
                .connection
                .prepare(&query)
                .map_err(|error| database_error(&error))?;
            let rows = statement
                .query_map(parameter_references(parameters).as_slice(), |row| {
                    row.get::<_, String>(0)
                })
                .map_err(|error| database_error(&error))?;
            for row in rows {
                visit(serde_json::from_str(
                    &row.map_err(|error| database_error(&error))?,
                )?)?;
            }
            Ok(())
        })
    }

    pub fn insert_rows(&self, sql: &str, rows: &[Vec<SqlValue>]) -> Result<()> {
        let mut statement = self
            .connection
            .prepare(sql)
            .map_err(|error| database_error(&error))?;
        for row in rows {
            statement
                .execute(duckdb::params_from_iter(row))
                .map_err(|error| database_error(&error))?;
        }
        Ok(())
    }
}

fn parameter_references(parameters: &Parameters) -> Vec<(&str, &dyn ToSql)> {
    parameters
        .iter()
        .map(|(name, value)| (name.as_str(), value as &dyn ToSql))
        .collect()
}

fn retryable(error: &Error) -> bool {
    [
        "No magic bytes found at end of file",
        "HTTP GET error",
        "Connection error",
    ]
    .iter()
    .any(|marker| error.to_string().contains(marker))
}

fn database_error(error: &duckdb::Error) -> Error {
    Error::new(format!("Analysis database operation failed: {error}"))
}
