use deadlock_data::{Error, Result};

pub const MAX_BUILD_NAME_CHARACTERS: usize = 50;

/// Formats the visible Steam build name as `persona | build name`.
///
/// When the combined name exceeds the Steam limit, the build name stands alone.
///
/// # Errors
/// Returns an error when the persona or build name is empty, or the build name exceeds the limit.
pub fn format_build_name(persona: &str, build_name: &str) -> Result<String> {
    let persona = persona.split_whitespace().collect::<Vec<_>>().join(" ");
    if persona.is_empty() {
        return Err(Error::new("Persona must contain visible text"));
    }
    let build = build_name.trim();
    if build.is_empty() || build.chars().count() > MAX_BUILD_NAME_CHARACTERS {
        return Err(Error::new("Build name is empty or exceeds the title limit"));
    }
    let named = format!("{persona} | {build}");
    Ok(if named.chars().count() <= MAX_BUILD_NAME_CHARACTERS {
        named
    } else {
        build.into()
    })
}
