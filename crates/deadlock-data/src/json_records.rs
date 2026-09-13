use std::fmt;
use std::sync::mpsc::sync_channel;
use std::thread;

use serde::Deserializer as _;
use serde::de::{DeserializeSeed, Error as _, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};
use sha2::{Digest as _, Sha256};

use crate::json::format_sha256;
use crate::{Error, Result, canonical_json, object};

#[derive(Debug)]
pub struct JsonRecordDocument<'source> {
    header: Value,
    bytes: &'source [u8],
    records_field: &'source str,
    records_field_count: usize,
}

impl<'source> JsonRecordDocument<'source> {
    /// # Errors
    /// Returns an error if the JSON root is not an object or the records field is absent.
    pub fn parse(bytes: &'source [u8], records_field: &'source str) -> Result<Self> {
        let mut deserializer = serde_json::Deserializer::from_slice(bytes);
        let (header, records_field_count) =
            deserializer.deserialize_map(HeaderVisitor(records_field))?;
        deserializer.end()?;
        Ok(Self {
            header: header.into(),
            bytes,
            records_field,
            records_field_count,
        })
    }

    #[must_use]
    pub const fn header(&self) -> &Value {
        &self.header
    }

    #[must_use]
    pub fn into_header(self) -> Value {
        self.header
    }

    /// # Errors
    /// Returns an error if the records are not a JSON array or a record operation fails.
    pub fn visit_records(&self, mut visit: impl FnMut(&Value) -> Result<()>) -> Result<()> {
        self.visit_record_values(|record| visit(&record))
    }

    fn visit_record_values(&self, visit: impl FnMut(Value) -> Result<()>) -> Result<()> {
        // Parse from the original root to preserve the JSON nesting limit.
        let mut deserializer = serde_json::Deserializer::from_slice(self.bytes);
        deserializer.deserialize_map(DocumentVisitor {
            records_field: self.records_field,
            records_field_count: self.records_field_count,
            visit,
        })?;
        deserializer.end()?;
        Ok(())
    }

    /// Calculates the canonical document fingerprint while it processes each record.
    /// Omits only the named root field from the fingerprint.
    /// # Errors
    /// Returns an error for invalid records, serialization failure, or a failed record operation.
    pub fn fingerprint(
        &self,
        excluded_field: &str,
        visit: impl FnMut(&Value) -> Result<()>,
    ) -> Result<String> {
        if excluded_field == self.records_field {
            return Err(Error::new("The fingerprint must include the records field"));
        }
        let mut keys = object(&self.header)?
            .keys()
            .map(String::as_str)
            .filter(|key| *key != excluded_field)
            .chain([self.records_field])
            .collect::<Vec<_>>();
        keys.sort_unstable();
        let mut digest = Sha256::new();
        digest.update(b"{");
        let mut visit = visit;
        for (index, key) in keys.into_iter().enumerate() {
            if index != 0 {
                digest.update(b",");
            }
            digest.update(serde_json::to_vec(key)?);
            digest.update(b":");
            if key == self.records_field {
                self.hash_records(&mut digest, &mut visit)?;
            } else {
                digest.update(canonical_json(&self.header[key])?);
            }
        }
        digest.update(b"}");
        Ok(format_sha256(&digest.finalize()))
    }

    fn hash_records(
        &self,
        digest: &mut Sha256,
        mut visit: impl FnMut(&Value) -> Result<()>,
    ) -> Result<()> {
        digest.update(b"[");
        let mut first = true;
        thread::scope(|scope| {
            // Keep at most one pending record outside validation.
            let (sender, records) = sync_channel(0);
            let reader = scope.spawn(move || {
                self.visit_record_values(|record| {
                    sender
                        .send(record)
                        .map_err(|_| Error::new("JSON record processing stopped"))
                })
            });
            let result = records.iter().try_for_each(|record| {
                if !first {
                    digest.update(b",");
                }
                first = false;
                digest.update(canonical_json(&record)?);
                visit(&record)
            });
            drop(records);
            let read_result = reader
                .join()
                .map_err(|_| Error::new("JSON record reader failed"));
            result?;
            read_result?
        })?;
        digest.update(b"]");
        Ok(())
    }
}

struct HeaderVisitor<'field>(&'field str);

impl<'de> Visitor<'de> for HeaderVisitor<'_> {
    type Value = (Map<String, Value>, usize);

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON object")
    }

    fn visit_map<Fields: MapAccess<'de>>(
        self,
        mut fields: Fields,
    ) -> std::result::Result<Self::Value, Fields::Error> {
        let mut header = Map::new();
        let mut records_field_count = 0;
        while let Some(name) = fields.next_key::<String>()? {
            if name == self.0 {
                records_field_count += 1;
                fields.next_value::<IgnoredAny>()?;
            } else {
                header.insert(name, fields.next_value::<Value>()?);
            }
        }
        if records_field_count == 0 {
            return Err(Fields::Error::custom(format!(
                "JSON records field is missing: {}",
                self.0
            )));
        }
        Ok((header, records_field_count))
    }
}

struct DocumentVisitor<'field, Operation> {
    records_field: &'field str,
    records_field_count: usize,
    visit: Operation,
}

impl<'de, Operation: FnMut(Value) -> Result<()>> Visitor<'de> for DocumentVisitor<'_, Operation> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON object")
    }

    fn visit_map<Fields: MapAccess<'de>>(
        mut self,
        mut fields: Fields,
    ) -> std::result::Result<(), Fields::Error> {
        let mut records_field_count = 0;
        while let Some(name) = fields.next_key::<String>()? {
            if name == self.records_field {
                records_field_count += 1;
                if records_field_count == self.records_field_count {
                    fields.next_value_seed(RecordVisitor(&mut self.visit))?;
                } else {
                    // Validate earlier duplicate fields before processing the final value.
                    fields.next_value::<Value>()?;
                }
            } else {
                fields.next_value::<IgnoredAny>()?;
            }
        }
        Ok(())
    }
}

struct RecordVisitor<Operation>(Operation);

impl<'de, Operation: FnMut(Value) -> Result<()>> DeserializeSeed<'de> for RecordVisitor<Operation> {
    type Value = ();

    fn deserialize<Deserializer: serde::Deserializer<'de>>(
        self,
        deserializer: Deserializer,
    ) -> std::result::Result<(), Deserializer::Error> {
        deserializer.deserialize_seq(self)
    }
}

impl<'de, Operation: FnMut(Value) -> Result<()>> Visitor<'de> for RecordVisitor<Operation> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON array")
    }

    fn visit_seq<Sequence: SeqAccess<'de>>(
        mut self,
        mut sequence: Sequence,
    ) -> std::result::Result<(), Sequence::Error> {
        while let Some(record) = sequence.next_element::<Value>()? {
            (self.0)(record).map_err(Sequence::Error::custom)?;
        }
        Ok(())
    }
}
