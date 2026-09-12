use deadlock_data::{Error, Result, fingerprint, read_json};
use deadlock_guides::{QualityInputs, build_quality_report, parse_replay};

use crate::cli_arguments::QualityArguments;
use crate::cli_output::print_json;
use crate::cli_paths::{absolute_path, artifact_directory};

pub fn run_quality(args: &QualityArguments) -> Result<u8> {
    let inputs = QualityInputs::load(&artifact_directory(args.artifacts.as_deref())?)?;
    let mut cases = Vec::new();
    let mut assets = Vec::new();
    let replay_sha256 = if let Some(path) = &args.replay {
        let asset_path = args.assets.as_deref().ok_or_else(|| {
            Error::new("Quality replay requires --assets with pinned item assets")
        })?;
        let document = read_json(&absolute_path(path)?)?;
        cases = parse_replay(
            &document,
            &inputs.policies,
            inputs.cutoff,
            &inputs.evidence.metadata().artifact_id,
        )?;
        assets = inputs.load_replay_assets(&absolute_path(asset_path)?)?;
        Some(fingerprint(&document)?)
    } else {
        None
    };
    let report = build_quality_report(&inputs, &cases, &assets, replay_sha256.as_deref())?;
    print_json(&report)?;
    Ok(match report["status"].as_str() {
        Some("pass") => 0,
        Some("fail") => 1,
        _ => 2,
    })
}
