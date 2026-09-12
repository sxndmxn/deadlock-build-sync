use deadlock_data::{Result, TraceSession, state_directory, trace_operation};

use crate::cli_arguments::{Cli, Command, TraceMode};
use crate::cli_artifacts::{run_install_artifacts, run_narratives, run_restore};
use crate::cli_build::{run_build, run_export, run_install, run_preview, run_sync};
use crate::cli_output::print_text;
use crate::cli_paths::absolute_path;
use crate::cli_quality::run_quality;
use crate::cli_recommendation::run_recommend;
use crate::cli_refresh::run_refresh;
use crate::cli_status::run_status;
use crate::trace_summary::render_trace_summary;

/// # Errors
/// Returns an error when command inputs, generation, validation, storage, or trace configuration fails.
pub fn run_cli(cli: &Cli) -> Result<u8> {
    let mut trace = cli
        .trace
        .map(|mode| {
            TraceSession::start(
                &state_directory()?.join("traces"),
                cli.command.name(),
                mode == TraceMode::Calls,
            )
        })
        .transpose()?;
    let result = trace_operation("cli.run_command", Some("command"), || dispatch(cli));
    if let Some(trace) = &mut trace {
        let code = result.as_ref().copied().unwrap_or(1);
        if let Err(error) = trace.finish(code) {
            eprintln!("Trace output failed: {error}");
        }
        eprintln!("Trace: {}", trace.directory().display());
    }
    result
}

fn dispatch(cli: &Cli) -> Result<u8> {
    let base_url = &cli.api_base_url;
    match &cli.command {
        Command::Build(args) => run_build(args, base_url),
        Command::Sync(args) => run_sync(args, base_url),
        Command::Preview(args) => run_preview(args, base_url),
        Command::Install(args) => run_install(args, base_url),
        Command::ExportContext(args) => run_export(args, base_url),
        Command::InstallArtifacts(args) => run_install_artifacts(args),
        Command::GenerateNarratives(args) => run_narratives(args),
        Command::Restore(args) => run_restore(args),
        Command::Recommend(args) => run_recommend(args, base_url),
        Command::QualityReport(args) => run_quality(args),
        Command::Status(args) => run_status(args, base_url),
        Command::TraceSummary(args) => {
            print_text(&render_trace_summary(
                &absolute_path(&args.path)?,
                args.max_nodes,
            )?)?;
            Ok(0)
        }
        Command::RefreshEvidence(args) => run_refresh(args, base_url),
    }
}
