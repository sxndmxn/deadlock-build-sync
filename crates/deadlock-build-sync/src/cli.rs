use deadlock_data::{Result, TraceSession, state_directory, trace_operation};

use crate::cli_arguments::{Cli, Command, TraceMode};
use crate::cli_artifacts::{run_install_artifacts, run_narratives, run_restore};
use crate::cli_build::{run_build, run_export, run_install, run_preview, run_sync};
use crate::cli_output::print_text;
use crate::cli_paths::absolute_path;
use crate::cli_quality::run_quality;
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
        Command::Build(arguments) => run_build(arguments, base_url),
        Command::Sync(arguments) => run_sync(arguments, base_url),
        Command::Preview(arguments) => run_preview(arguments, base_url),
        Command::Install(arguments) => run_install(arguments, base_url),
        Command::ExportContext(arguments) => run_export(arguments, base_url),
        Command::InstallArtifacts(arguments) => run_install_artifacts(arguments, base_url),
        Command::GenerateNarratives(arguments) => run_narratives(arguments),
        Command::Restore(arguments) => run_restore(arguments),
        Command::QualityReport(arguments) => run_quality(arguments),
        Command::Status(arguments) => run_status(arguments, base_url),
        Command::TraceSummary(arguments) => {
            print_text(&render_trace_summary(
                &absolute_path(&arguments.path)?,
                arguments.max_nodes,
            )?)?;
            Ok(0)
        }
        Command::RefreshEvidence(arguments) => run_refresh(arguments, base_url),
    }
}
