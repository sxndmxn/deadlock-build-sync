use std::cell::RefCell;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

use serde_json::{Value, json};

use crate::error::{Error, Result};

const MAXIMUM_TRACE_BYTES: usize = 100 * 1024 * 1024;
thread_local! { static ACTIVE_TRACE: RefCell<Option<TraceWriter>> = const { RefCell::new(None) }; }

#[derive(Debug)]
struct TraceWriter {
    output: File,
    calls: bool,
    next_identifier: u64,
    parents: Vec<u64>,
    bytes: usize,
    stopped: bool,
}

impl TraceWriter {
    fn write(&mut self, event: &Value) {
        if self.stopped {
            return;
        }
        let Ok(mut bytes) = serde_json::to_vec(event) else {
            self.stopped = true;
            return;
        };
        bytes.push(b'\n');
        if self.bytes + bytes.len() + 128 > MAXIMUM_TRACE_BYTES {
            let marker =
                b"{\"event\":\"trace_truncated\",\"schema_version\":1,\"max_bytes\":104857600}\n";
            let _result = self.output.write_all(marker);
            self.stopped = true;
            return;
        }
        self.bytes += bytes.len();
        if self.output.write_all(&bytes).is_err() {
            self.stopped = true;
        }
    }

    fn begin(&mut self, function: &str, stage: Option<&str>) -> Option<u64> {
        if !self.calls && stage.is_none() {
            return None;
        }
        let id = self.next_identifier;
        self.next_identifier += 1;
        let parent = self.parents.last().copied();
        let event = if self.calls {
            json!({"event":"call","call_id":id,"module":"deadlock_build_sync","function":function,"parent_call_id":parent})
        } else {
            json!({"event":"stage_start","schema_version":1,"stage_id":id,"stage":stage,
                "parent_stage_id":parent,"depth":self.parents.len()})
        };
        self.write(&event);
        self.parents.push(id);
        Some(id)
    }

    fn end(&mut self, id: u64, started: Instant, failed: bool) {
        let status = if failed { "failure" } else { "success" };
        let elapsed = nanoseconds(started);
        let event = if self.calls {
            json!({"event":"return","call_id":id,"elapsed_ns":elapsed,"status":status})
        } else {
            json!({"event":"stage_end","schema_version":1,"stage_id":id,"elapsed_ns":elapsed,"status":status})
        };
        self.write(&event);
        if self.parents.last() == Some(&id) {
            self.parents.pop();
        }
    }
}

#[derive(Debug)]
pub struct TraceSession {
    directory: PathBuf,
    started: Instant,
    finished: bool,
}

impl TraceSession {
    /// # Errors
    /// Returns an error when a trace is already active or a trace directory cannot be created.
    pub fn start(root: &Path, command: &str, calls: bool) -> Result<Self> {
        if ACTIVE_TRACE.with(|state| state.borrow().is_some()) {
            return Err(Error::new("An execution trace is already active"));
        }
        fs::create_dir_all(root)?;
        prune_completed(root)?;
        let directory = create_directory(root)?;
        let mut writer = TraceWriter {
            output: File::options()
                .create_new(true)
                .write(true)
                .open(directory.join("trace.jsonl"))?,
            calls,
            next_identifier: 1,
            parents: Vec::new(),
            bytes: 0,
            stopped: false,
        };
        writer.write(&json!({"event":"trace_start","schema_version":1,"command":command,"mode":if calls {"calls"} else {"stages"},
            "started_at":chrono::Utc::now().to_rfc3339()}));
        ACTIVE_TRACE.with(|state| *state.borrow_mut() = Some(writer));
        Ok(Self {
            directory,
            started: Instant::now(),
            finished: false,
        })
    }

    #[must_use]
    pub fn directory(&self) -> &Path {
        &self.directory
    }

    /// # Errors
    /// Returns an error when the completed trace cannot be synchronized or its active marker cannot be removed.
    pub fn finish(&mut self, exit_code: u8) -> Result<()> {
        if self.finished {
            return Ok(());
        }
        self.finished = true;
        let result = ACTIVE_TRACE.with(|state| {
            if let Some(mut writer) = state.borrow_mut().take() {
                writer.write(&json!({"event":"trace_complete","schema_version":1,"elapsed_ns":nanoseconds(self.started),
                    "exit_code":exit_code,"status":if exit_code == 0 {"success"} else {"failure"}}));
                writer.output.sync_all()?;
            }
            Ok::<_, Error>(())
        });
        fs::remove_file(self.directory.join(".active"))?;
        result
    }
}

impl Drop for TraceSession {
    fn drop(&mut self) {
        let _result = self.finish(1);
    }
}

/// # Errors
/// Returns the operation error. The trace contains operation names and timings, without argument or result values.
pub fn trace_operation<T>(
    function: &'static str,
    stage: Option<&'static str>,
    operation: impl FnOnce() -> Result<T>,
) -> Result<T> {
    let id = ACTIVE_TRACE.with(|state| {
        state
            .borrow_mut()
            .as_mut()
            .and_then(|writer| writer.begin(function, stage))
    });
    let started = Instant::now();
    let result = operation();
    if let Some(id) = id {
        ACTIVE_TRACE.with(|state| {
            if let Some(writer) = state.borrow_mut().as_mut() {
                writer.end(id, started, result.is_err());
            }
        });
    }
    result
}

fn nanoseconds(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

fn create_directory(root: &Path) -> Result<PathBuf> {
    let prefix = format!(
        "{}-{}",
        chrono::Utc::now().format("%Y%m%dT%H%M%S.%6fZ"),
        std::process::id()
    );
    for collision in 0..1000 {
        let name = if collision == 0 {
            prefix.clone()
        } else {
            format!("{prefix}-{collision}")
        };
        let directory = root.join(name);
        match fs::create_dir(&directory) {
            Ok(()) => {
                fs::write(directory.join(".active"), std::process::id().to_string())?;
                return Ok(directory);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
            Err(error) => return Err(error.into()),
        }
    }
    Err(Error::new("Cannot allocate an execution trace directory"))
}

fn prune_completed(root: &Path) -> Result<()> {
    let mut candidates = Vec::new();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        let Some((timestamp, process)) = name.split_once("Z-") else {
            continue;
        };
        let valid = chrono::NaiveDateTime::parse_from_str(timestamp, "%Y%m%dT%H%M%S.%f").is_ok()
            && process
                .split('-')
                .all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()));
        let path = entry.path();
        if valid
            && entry.file_type()?.is_dir()
            && !path.join(".active").try_exists()?
            && fs::symlink_metadata(path.join("trace.jsonl"))
                .is_ok_and(|metadata| metadata.file_type().is_file())
        {
            candidates.push(path);
        }
    }
    candidates.sort();
    let remove = candidates.len().saturating_sub(2);
    for path in candidates.into_iter().take(remove) {
        fs::remove_dir_all(path)?;
    }
    Ok(())
}
