use std::fmt::Write as _;

use serde_json::{Map, Value};
use sha2::{Digest as _, Sha256};

use crate::{Error, Result};

/// # Errors
/// Returns an error if the value is not an object.
pub fn object(value: &Value) -> Result<&Map<String, Value>> {
    value
        .as_object()
        .ok_or_else(|| Error::new("Expected a JSON object"))
}

/// # Errors
/// Returns an error if the value is not an array.
pub fn array(value: &Value) -> Result<&[Value]> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| Error::new("Expected a JSON array"))
}

/// # Errors
/// Returns an error if the field is absent.
pub fn field<'a>(value: &'a Value, name: &str) -> Result<&'a Value> {
    object(value)?
        .get(name)
        .ok_or_else(|| Error::new(format!("Missing field: {name}")))
}

/// # Errors
/// Returns an error if the field is not a string.
pub fn text<'a>(value: &'a Value, name: &str) -> Result<&'a str> {
    field(value, name)?
        .as_str()
        .ok_or_else(|| Error::new(format!("Invalid text field: {name}")))
}

/// # Errors
/// Returns an error if the field is not an unsigned integer.
pub fn integer(value: &Value, name: &str) -> Result<u64> {
    field(value, name)?
        .as_u64()
        .ok_or_else(|| Error::new(format!("Invalid integer field: {name}")))
}

/// # Errors
/// Returns an error if the field is not a finite number.
pub fn real(value: &Value, name: &str) -> Result<f64> {
    field(value, name)?
        .as_f64()
        .filter(|number| number.is_finite())
        .ok_or_else(|| Error::new(format!("Invalid numeric field: {name}")))
}

/// # Errors
/// Returns an error if JSON serialization fails.
pub fn canonical_json(value: &Value) -> Result<Vec<u8>> {
    let mut output = String::new();
    write_value(value, &mut output)?;
    Ok(output.into_bytes())
}

/// # Errors
/// Returns an error if JSON serialization fails.
pub fn fingerprint(value: &Value) -> Result<String> {
    Ok(sha256(&canonical_json(value)?))
}

#[must_use]
pub fn sha256(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in Sha256::digest(bytes) {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    output
}

fn write_value(value: &Value, output: &mut String) -> Result<()> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::Number(value) => {
            let encoded = value.to_string();
            if value.is_f64() {
                output.push_str(&python_float(&encoded)?);
            } else {
                output.push_str(&encoded);
            }
        }
        Value::String(value) => output.push_str(&serde_json::to_string(value)?),
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                write_value(value, output)?;
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            let mut entries: Vec<_> = values.iter().collect();
            entries.sort_by_key(|(key, _)| *key);
            for (index, (key, value)) in entries.into_iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key)?);
                output.push(':');
                write_value(value, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn python_float(encoded: &str) -> Result<String> {
    let (sign, unsigned) = encoded
        .strip_prefix('-')
        .map_or(("", encoded), |value| ("-", value));
    let (mantissa, exponent) =
        unsigned
            .split_once('e')
            .map_or(Ok((unsigned, 0_i32)), |(mantissa, exponent)| {
                exponent
                    .parse::<i32>()
                    .map(|exponent| (mantissa, exponent))
                    .map_err(|error| Error::new(error.to_string()))
            })?;
    let decimal = i32::try_from(mantissa.find('.').unwrap_or(mantissa.len()))?;
    let raw_digits: String = mantissa
        .chars()
        .filter(|character| *character != '.')
        .collect();
    let leading = raw_digits.len() - raw_digits.trim_start_matches('0').len();
    let digits = raw_digits.trim_start_matches('0').trim_end_matches('0');
    if digits.is_empty() {
        return Ok(format!("{sign}0.0"));
    }
    let scientific_exponent = decimal - i32::try_from(leading)? - 1 + exponent;
    if !(-4..16).contains(&scientific_exponent) {
        let mut characters = digits.chars();
        let first = characters
            .next()
            .ok_or_else(|| Error::new("Invalid floating point number"))?;
        let rest = characters.as_str();
        let decimal_part = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        return Ok(format!(
            "{sign}{first}{decimal_part}e{scientific_exponent:+03}"
        ));
    }
    let position = scientific_exponent + 1;
    let mut result = sign.to_owned();
    if position <= 0 {
        result.push_str("0.");
        result.extend(std::iter::repeat_n('0', usize::try_from(-position)?));
        result.push_str(digits);
    } else {
        let position = usize::try_from(position)?;
        if position >= digits.len() {
            result.push_str(digits);
            result.extend(std::iter::repeat_n('0', position - digits.len()));
            result.push_str(".0");
        } else {
            let (whole, fraction) = digits.split_at(position);
            write!(result, "{whole}.{fraction}").map_err(|error| Error::new(error.to_string()))?;
        }
    }
    Ok(result)
}
