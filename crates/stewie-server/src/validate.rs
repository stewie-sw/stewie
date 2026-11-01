//! Request-body validation with the Python server's contract (`FastAPI` + Pydantic v2 in lax mode): the same
//! coercions and the same messages, so a client sees the identical `400` envelope. Field errors are reported in
//! model order, then extra keys (when forbidden) in input order; at most three, joined with `"; "`.

use serde_json::{Map, Value, json};

/// One field's type, constraints and default.
#[derive(Debug, Clone, Copy)]
pub enum Kind {
    /// A string of `min..=max` characters; `nullable` admits null. Without a default it is required, unless
    /// nullable (then it defaults to null).
    Str {
        min: usize,
        max: usize,
        nullable: bool,
        default: Option<&'static str>,
    },
    /// A number with `x > gt` and `x <= le` (bounds written as the Python wrote them).
    Float {
        gt: (f64, &'static str),
        le: (f64, &'static str),
        default: f64,
    },
    /// An integer with `ge <= x <= le`.
    Int { ge: i64, le: i64, default: i64 },
}

/// A field of a body model.
#[derive(Debug, Clone, Copy)]
pub struct Field(pub &'static str, pub Kind);

/// A body model: its fields and whether unknown keys are refused (`extra="forbid"`).
#[derive(Debug, Clone, Copy)]
pub struct Model {
    pub fields: &'static [Field],
    pub forbid_extra: bool,
}

fn plural(n: usize) -> &'static str {
    if n == 1 { "character" } else { "characters" }
}

/// A float the Pydantic way: a number, a bool (0/1), or a string that parses as one after trimming.
fn as_float(v: &Value) -> Result<f64, &'static str> {
    match v {
        Value::Number(n) => n.as_f64().ok_or("Input should be a valid number"),
        Value::Bool(b) => Ok(f64::from(u8::from(*b))),
        Value::String(s) => s
            .trim()
            .parse::<f64>()
            .map_err(|_| "Input should be a valid number, unable to parse string as a number"),
        _ => Err("Input should be a valid number"),
    }
}

/// An integer the Pydantic way: an integer, a whole float, a bool, or a string holding either.
fn as_int(v: &Value) -> Result<i64, &'static str> {
    const FRACTION: &str = "Input should be a valid integer, got a number with a fractional part";
    let whole = |x: f64, err: &'static str| -> Result<i64, &'static str> {
        if x.fract() != 0.0 || !x.is_finite() {
            return Err(err);
        }
        if x.abs() >= 9.223_372_036_854_775e18 {
            return Err("Unable to parse input string as an integer, exceeded maximum size");
        }
        #[allow(clippy::cast_possible_truncation)]
        Ok(x as i64)
    };
    match v {
        Value::Number(n) => n
            .as_i64()
            .map_or_else(|| whole(n.as_f64().unwrap_or(f64::NAN), FRACTION), Ok),
        Value::Bool(b) => Ok(i64::from(*b)),
        Value::String(s) => {
            const UNPARSED: &str =
                "Input should be a valid integer, unable to parse string as an integer";
            let t = s.trim();
            t.parse::<i64>().or_else(|_| {
                t.parse::<f64>()
                    .map_err(|_| UNPARSED)
                    .and_then(|x| whole(x, UNPARSED))
            })
        }
        _ => Err("Input should be a valid integer"),
    }
}

/// Validate one field's present value.
fn check(kind: Kind, v: &Value) -> Result<Value, String> {
    match kind {
        Kind::Str {
            min, max, nullable, ..
        } => match v {
            Value::Null if nullable => Ok(Value::Null),
            Value::String(s) => {
                let n = s.chars().count();
                if n < min {
                    Err(format!("String should have at least {min} {}", plural(min)))
                } else if n > max {
                    Err(format!("String should have at most {max} {}", plural(max)))
                } else {
                    Ok(json!(s))
                }
            }
            _ => Err("Input should be a valid string".to_owned()),
        },
        Kind::Float { gt, le, .. } => {
            let x = as_float(v).map_err(str::to_owned)?;
            if x.is_nan() || x > le.0 {
                Err(format!("Input should be less than or equal to {}", le.1))
            } else if x <= gt.0 {
                Err(format!("Input should be greater than {}", gt.1))
            } else {
                Ok(json!(x))
            }
        }
        Kind::Int { ge, le, .. } => {
            let x = as_int(v).map_err(str::to_owned)?;
            if x < ge {
                Err(format!("Input should be greater than or equal to {ge}"))
            } else if x > le {
                Err(format!("Input should be less than or equal to {le}"))
            } else {
                Ok(json!(x))
            }
        }
    }
}

/// Parse a JSON body; empty means absent.
///
/// # Errors
/// Malformed JSON, as the Python's message.
pub fn parse(bytes: &[u8]) -> Result<Option<Value>, String> {
    if bytes.is_empty() {
        return Ok(None);
    }
    serde_json::from_slice(bytes)
        .map(Some)
        .map_err(|_| "bad JSON: JSON decode error".to_owned())
}

/// Validate a parsed body against `model`, returning every field (defaults filled in).
///
/// # Errors
/// The joined messages of the first three errors.
pub fn model(body: Option<&Value>, model: Model) -> Result<Map<String, Value>, String> {
    let Some(body) = body else {
        return Err("body: Field required".to_owned());
    };
    let Some(obj) = body.as_object() else {
        return Err(
            "body: Input should be a valid dictionary or object to extract fields from".to_owned(),
        );
    };
    let mut out = Map::new();
    let mut errors = Vec::new();
    for Field(name, kind) in model.fields {
        match obj.get(*name) {
            Some(v) => match check(*kind, v) {
                Ok(x) => {
                    out.insert((*name).to_owned(), x);
                }
                Err(e) => errors.push(format!("{name}: {e}")),
            },
            None => match *kind {
                // an optional string defaults to null; any other string without a default is required
                Kind::Str {
                    default: None,
                    nullable: true,
                    ..
                } => {
                    out.insert((*name).to_owned(), Value::Null);
                }
                Kind::Str { default: None, .. } => errors.push(format!("{name}: Field required")),
                Kind::Str {
                    default: Some(d), ..
                } => {
                    out.insert((*name).to_owned(), json!(d));
                }
                Kind::Float { default, .. } => {
                    out.insert((*name).to_owned(), json!(default));
                }
                Kind::Int { default, .. } => {
                    out.insert((*name).to_owned(), json!(default));
                }
            },
        }
    }
    if model.forbid_extra {
        for k in obj
            .keys()
            .filter(|k| !model.fields.iter().any(|f| f.0 == k.as_str()))
        {
            errors.push(format!("{k}: Extra inputs are not permitted"));
        }
    }
    if errors.is_empty() {
        Ok(out)
    } else {
        Err(errors.into_iter().take(3).collect::<Vec<_>>().join("; "))
    }
}

/// A `body: dict` parameter: any JSON object.
///
/// # Errors
/// An absent body or a non-object.
pub fn dict(body: Option<&Value>) -> Result<&Map<String, Value>, String> {
    match body {
        None => Err("body: Field required".to_owned()),
        Some(Value::Object(m)) => Ok(m),
        Some(_) => Err("body: Input should be a valid dictionary".to_owned()),
    }
}

/// Python's `str()` of a JSON value: strings as they are, `None`/`True`/`False`, numbers as Python writes them,
/// containers as their `repr`.
#[must_use]
pub fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => py_repr_value(other),
    }
}

fn py_repr_value(v: &Value) -> String {
    match v {
        Value::Null => "None".to_owned(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_owned(),
        Value::Number(n) => n.as_i64().map_or_else(
            || {
                n.as_f64()
                    .and_then(|x| stewie_twin::pyjson::float_repr(x).ok())
                    .unwrap_or_else(|| n.to_string())
            },
            |i| i.to_string(),
        ),
        Value::String(s) => crate::operators::py_repr(s),
        Value::Array(a) => format!(
            "[{}]",
            a.iter().map(py_repr_value).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, x)| format!("{}: {}", crate::operators::py_repr(k), py_repr_value(x)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// `str(body.get(key, default))`.
#[must_use]
pub fn get_str(m: &Map<String, Value>, key: &str, default: &str) -> String {
    m.get(key).map_or_else(|| default.to_owned(), py_str)
}
