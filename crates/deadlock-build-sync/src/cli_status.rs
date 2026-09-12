use deadlock_data::Result;
use deadlock_input::{ApiOptions, DeadlockApi};

use crate::cli_arguments::StatusArguments;
use crate::cli_output::{print_json, print_text};
use crate::cli_paths::{artifact_directory, cache_location};
use crate::freshness::build_freshness_report;

pub fn run_status(args: &StatusArguments, base_url: &str) -> Result<u8> {
    let directory = artifact_directory(args.artifacts.as_deref())?;
    let location = cache_location(&args.location);
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        ..ApiOptions::default()
    })?;
    let (code, report) = build_freshness_report(&directory, &mut api, location)?;
    if args.json {
        print_json(&report)?;
    } else if let Some(stages) = report["stages"].as_array() {
        for stage in stages {
            print_text(&format!(
                "{}: {} — {}",
                stage["stage"].as_str().unwrap_or_default(),
                stage["state"].as_str().unwrap_or_default(),
                stage["detail"].as_str().unwrap_or_default()
            ))?;
        }
    }
    Ok(code)
}
