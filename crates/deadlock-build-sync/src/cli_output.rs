use std::io::{self, Write};

use deadlock_data::Result;
use serde_json::Value;

pub fn print_json(value: &Value) -> Result<()> {
    let mut output = io::stdout().lock();
    serde_json::to_writer_pretty(&mut output, value)?;
    writeln!(output)?;
    Ok(())
}

pub fn print_text(value: &str) -> Result<()> {
    let mut output = io::stdout().lock();
    writeln!(output, "{value}")?;
    Ok(())
}
