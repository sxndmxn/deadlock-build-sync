#![forbid(unsafe_code)]

#[path = "check_safety/artifact_checks.rs"]
mod artifact_checks;
#[path = "check_safety/reference_data.rs"]
mod reference_data;
#[path = "check_safety/steam_checks.rs"]
mod steam_checks;

fn main() -> deadlock_data::Result<()> {
    artifact_checks::check_artifact_recovery()?;
    steam_checks::check_steam_safety()?;
    println!("Isolated safety checks passed. The checks did not use live Steam files.");
    Ok(())
}
