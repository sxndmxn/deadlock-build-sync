use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs::File;
use std::io::Read as _;
use std::path::Path;

use deadlock_data::{Error, Result, integer, object, text};
use serde_json::Value;

const MAXIMUM_TRACE_BYTES: u64 = 101 * 1024 * 1024;

#[derive(Debug)]
struct SummarySpan {
    label: String,
    depth: usize,
    elapsed: Option<u64>,
    status: String,
}

#[derive(Debug, Default)]
struct Summary {
    metadata: Value,
    functions: BTreeMap<u64, String>,
    spans: BTreeMap<u64, SummarySpan>,
    order: Vec<u64>,
    truncated: bool,
}

impl Summary {
    fn record(&mut self, event: &Value) -> Result<()> {
        object(event)?;
        match event["event"].as_str() {
            Some("trace_start") => self.metadata = event.clone(),
            Some("function_definition") => {
                self.functions.insert(
                    integer(event, "function_id")?,
                    format!("{}.{}", text(event, "module")?, text(event, "function")?),
                );
            }
            Some("call" | "stage_start") => self.add_span(event)?,
            Some("return" | "stage_end") => {
                if let Some(id) = event["call_id"]
                    .as_u64()
                    .or_else(|| event["stage_id"].as_u64())
                    && let Some(span) = self.spans.get_mut(&id)
                {
                    span.elapsed = event["elapsed_ns"].as_u64();
                    span.status = event["status"].as_str().unwrap_or("incomplete").into();
                }
            }
            Some("trace_complete") => {
                if !self.metadata.is_object() {
                    return Err(Error::new("Trace completion has no start event"));
                }
                self.metadata["status"] = event["status"].clone();
                self.metadata["elapsed_ns"] = event["elapsed_ns"].clone();
            }
            Some("trace_truncated") => self.truncated = true,
            _ => (),
        }
        Ok(())
    }

    fn add_span(&mut self, event: &Value) -> Result<()> {
        let calls = event["event"] == "call";
        let identifier = integer(event, if calls { "call_id" } else { "stage_id" })?;
        let label = if !calls {
            text(event, "stage")?.into()
        } else if let Some(id) = event["function_id"].as_u64() {
            self.functions
                .get(&id)
                .cloned()
                .ok_or_else(|| Error::new("Trace call references an unknown function"))?
        } else {
            format!("{}.{}", text(event, "module")?, text(event, "function")?)
        };
        let parent = event["parent_call_id"]
            .as_u64()
            .or_else(|| event["parent_stage_id"].as_u64());
        let depth = event["depth"]
            .as_u64()
            .map(usize::try_from)
            .transpose()?
            .unwrap_or_else(|| {
                parent
                    .and_then(|id| self.spans.get(&id))
                    .map_or(0, |span| span.depth + 1)
            });
        if depth > 1024 || self.spans.contains_key(&identifier) {
            return Err(Error::new(
                "Trace has excessive depth or repeated span identifiers",
            ));
        }
        self.spans.insert(
            identifier,
            SummarySpan {
                label,
                depth,
                elapsed: None,
                status: "incomplete".into(),
            },
        );
        self.order.push(identifier);
        Ok(())
    }
}

pub fn render_trace_summary(path: &Path, maximum_nodes: u32) -> Result<String> {
    if maximum_nodes == 0 {
        return Err(Error::new("Trace summary requires a positive node limit"));
    }
    let path = if path.is_dir() {
        path.join("trace.jsonl")
    } else {
        path.to_path_buf()
    };
    let mut bytes = Vec::new();
    File::open(&path)?
        .take(MAXIMUM_TRACE_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len())? > MAXIMUM_TRACE_BYTES {
        return Err(Error::new("Execution trace exceeds the size limit"));
    }
    let mut summary = Summary::default();
    for (index, line) in std::str::from_utf8(&bytes)?.lines().enumerate() {
        let event: Value = serde_json::from_str(line)
            .map_err(|error| Error::new(format!("Trace line {} is invalid: {error}", index + 1)))?;
        summary.record(&event)?;
    }
    render(&path, &summary, usize::try_from(maximum_nodes)?)
}

fn render(path: &Path, summary: &Summary, maximum_nodes: usize) -> Result<String> {
    let metadata = &summary.metadata;
    let mut output = format!(
        "Trace: {}\nMode: {} | Command: {} | Status: {} | Elapsed: {}\n{} tree:\n",
        path.display(),
        metadata["mode"].as_str().unwrap_or("unknown"),
        metadata["command"].as_str().unwrap_or("unknown"),
        metadata["status"].as_str().unwrap_or("incomplete"),
        duration(metadata["elapsed_ns"].as_u64()),
        if metadata["mode"] == "calls" {
            "Call"
        } else {
            "Stage"
        }
    );
    for id in summary.order.iter().take(maximum_nodes) {
        let span = &summary.spans[id];
        writeln!(
            output,
            "{}{} [{}, {}]",
            "  ".repeat(span.depth),
            span.label,
            duration(span.elapsed),
            span.status
        )?;
    }
    if summary.order.len() > maximum_nodes {
        writeln!(
            output,
            "{} additional spans omitted",
            summary.order.len() - maximum_nodes
        )?;
    }
    if summary.truncated {
        output.push_str("The trace file reached its size limit. Later events are unavailable.\n");
    }
    write_totals(&mut output, summary)?;
    Ok(output)
}

fn write_totals(output: &mut String, summary: &Summary) -> Result<()> {
    let mut totals = BTreeMap::<&str, (usize, u64, u64)>::new();
    for span in summary.spans.values() {
        let (count, total, maximum) = totals.entry(&span.label).or_default();
        let elapsed = span.elapsed.unwrap_or(0);
        *count += 1;
        *total = total
            .checked_add(elapsed)
            .ok_or_else(|| Error::new("Trace duration total exceeds 64 bits"))?;
        *maximum = (*maximum).max(elapsed);
    }
    let mut totals = totals.into_iter().collect::<Vec<_>>();
    totals.sort_by_key(|(name, (_, total, _))| (std::cmp::Reverse(*total), *name));
    output.push_str("Per-function inclusive time:\n");
    for (name, (count, total, maximum)) in totals {
        writeln!(
            output,
            "{} total | {} maximum | {count} calls | {name}",
            duration(Some(total)),
            duration(Some(maximum))
        )?;
    }
    Ok(())
}

fn duration(nanoseconds: Option<u64>) -> String {
    nanoseconds.map_or_else(
        || "incomplete".into(),
        |value| format!("{}.{:03} ms", value / 1_000_000, (value % 1_000_000) / 1000),
    )
}
