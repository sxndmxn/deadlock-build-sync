use serde_json::{Map, Value};

#[must_use]
pub fn is_populated(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
        Value::Bool(_) | Value::Number(_) => true,
    }
}

#[must_use]
pub fn clean_mechanical_text(value: &Value) -> String {
    value.as_str().map_or_else(String::new, clean_text)
}

#[must_use]
pub fn clean_text(text: &str) -> String {
    let compatible = remove_invalid_numeric_references(text);
    let decoded = htmlize::unescape(compatible);
    let without_markup = replace_delimited(&decoded, '<', '>', |_| true);
    let without_tokens = replace_delimited(&without_markup, '{', '}', |token| {
        token
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_.:-".contains(&byte))
    });
    without_tokens
        .split(is_text_space)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn is_text_space(character: char) -> bool {
    character.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&character)
}

fn remove_invalid_numeric_references(text: &str) -> String {
    let mut remaining = text;
    let mut output = String::with_capacity(text.len());
    while let Some(position) = remaining.find("&#") {
        output.push_str(&remaining[..position]);
        let reference = &remaining[position..];
        let length = numeric_reference_length(reference);
        let encoded = &reference[..length];
        let decoded = htmlize::unescape(encoded);
        if !decoded.chars().any(is_invalid_numeric_character) {
            output.push_str(encoded);
        }
        remaining = &reference[length..];
    }
    output.push_str(remaining);
    output
}

fn numeric_reference_length(reference: &str) -> usize {
    let digits = &reference[2..];
    let hexadecimal = digits.starts_with(['x', 'X']);
    let prefix = if hexadecimal { 3 } else { 2 };
    let count = reference[prefix..]
        .bytes()
        .take_while(|byte| {
            if hexadecimal {
                byte.is_ascii_hexdigit()
            } else {
                byte.is_ascii_digit()
            }
        })
        .count();
    let length = prefix + count;
    length + usize::from(reference.as_bytes().get(length) == Some(&b';'))
}

fn is_invalid_numeric_character(character: char) -> bool {
    let value = u32::from(character);
    matches!(value, 1..=8 | 11 | 14..=31 | 127 | 0xfdd0..=0xfdef) || value & 0xffff >= 0xfffe
}

fn replace_delimited(text: &str, start: char, end: char, matches: impl Fn(&str) -> bool) -> String {
    let mut output = String::with_capacity(text.len());
    let mut remaining = text;
    while let Some(position) = remaining.find(start) {
        let (prefix, suffix) = remaining.split_at(position);
        output.push_str(prefix);
        let content = &suffix[start.len_utf8()..];
        if let Some(end_position) = content.find(end)
            && end_position > 0
            && matches(&content[..end_position])
        {
            output.push(' ');
            remaining = &content[end_position + end.len_utf8()..];
        } else {
            output.push(start);
            remaining = content;
        }
    }
    output.push_str(remaining);
    output
}

#[must_use]
pub fn normalize_mechanical_value(value: &Value) -> Value {
    match value {
        Value::Object(values) => values
            .iter()
            .filter(|(_, value)| is_populated(value))
            .map(|(key, value)| (key.clone(), normalize_mechanical_value(value)))
            .collect(),
        Value::Array(values) => values.iter().map(normalize_mechanical_value).collect(),
        Value::String(text) => {
            let cleaned = clean_text(text);
            if cleaned.is_empty() {
                text.trim_matches(is_text_space).into()
            } else {
                cleaned.into()
            }
        }
        value => value.clone(),
    }
}

#[must_use]
pub fn normalize_hero_description(value: &Value) -> Map<String, Value> {
    if let Some(text) = value.as_str() {
        let cleaned = clean_text(text);
        return if cleaned.is_empty() {
            Map::new()
        } else {
            Map::from_iter([("summary".into(), cleaned.into())])
        };
    }
    value.as_object().map_or_else(Map::new, |values| {
        values
            .iter()
            .filter_map(|(key, value)| {
                let cleaned = clean_mechanical_text(value);
                (!cleaned.is_empty()).then(|| (key.clone(), cleaned.into()))
            })
            .collect()
    })
}
