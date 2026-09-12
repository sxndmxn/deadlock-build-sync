#![forbid(unsafe_code)]
#![deny(warnings)]

use std::process::ExitCode;

use clap::Parser;
use deadlock_build_sync::{Cli, run_cli};

fn main() -> ExitCode {
    match run_cli(&Cli::parse()) {
        Ok(code) => ExitCode::from(code),
        Err(error) => {
            eprintln!("Error: {error}");
            ExitCode::FAILURE
        }
    }
}
