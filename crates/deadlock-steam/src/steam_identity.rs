use std::path::PathBuf;

use deadlock_data::{Error, Result};
use regex_lite::Regex;

use crate::cache_files::read_limited;

const STEAM_ID64_ACCOUNT_OFFSET: u64 = 76_561_197_960_265_728;

/// # Errors
/// Returns an error when the fixed persona matching expressions cannot be compiled.
pub fn local_steam_persona(account_id: u32, roots: &[PathBuf]) -> Result<Option<String>> {
    let identifier = STEAM_ID64_ACCOUNT_OFFSET + u64::from(account_id);
    let user = Regex::new(&format!(r#"(?ms)"{identifier}"\s*\{{(.*?)^\s*\}}"#))
        .map_err(|error| Error::new(format!("Invalid Steam account expression: {error}")))?;
    let persona = Regex::new(r#""PersonaName"\s*"((?:\\.|[^"\\])*)""#)
        .map_err(|error| Error::new(format!("Invalid Steam persona expression: {error}")))?;
    for root in roots {
        let Ok(bytes) = read_limited(&root.join("config/loginusers.vdf"), 8 * 1024 * 1024) else {
            continue;
        };
        let Ok(document) = std::str::from_utf8(&bytes) else {
            continue;
        };
        let Some(body) = user.captures(document).and_then(|captures| captures.get(1)) else {
            continue;
        };
        let Some(value) = persona
            .captures(body.as_str())
            .and_then(|captures| captures.get(1))
        else {
            continue;
        };
        let name = decode_name(value.as_str());
        if !name.is_empty() {
            return Ok(Some(name));
        }
    }
    Ok(None)
}

fn decode_name(value: &str) -> String {
    let mut output = String::new();
    let mut characters = value.chars().peekable();
    while let Some(character) = characters.next() {
        if character == '\\' && matches!(characters.peek(), Some('"' | '\\')) {
            if let Some(escaped) = characters.next() {
                output.push(escaped);
            }
        } else {
            output.push(character);
        }
    }
    output.trim().into()
}
