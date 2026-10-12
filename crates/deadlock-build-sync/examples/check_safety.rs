#![forbid(unsafe_code)]

#[path = "check_safety/artifact_checks.rs"]
mod artifact_checks;
#[path = "check_safety/focus_checks.rs"]
mod focus_checks;
#[path = "check_safety/freshness_checks.rs"]
mod freshness_checks;
#[path = "check_safety/imbue_checks.rs"]
mod imbue_checks;
#[path = "check_safety/reference_data.rs"]
mod reference_data;
#[path = "check_safety/resume_checks.rs"]
mod resume_checks;
#[path = "check_safety/steam_checks.rs"]
mod steam_checks;

fn main() -> deadlock_data::Result<()> {
    artifact_checks::check_artifact_recovery()?;
    resume_checks::check_resume_sources()?;
    freshness_checks::check_installation_freshness()?;
    imbue_checks::check_imbue_encoding()?;
    focus_checks::check_build_focus()?;
    steam_checks::check_steam_safety()?;
    println!("Isolated safety checks passed. The checks did not use live Steam files.");
    Ok(())
}
