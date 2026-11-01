//! Request-body validation with the Python server's contract (`FastAPI` + Pydantic v2 in lax mode): the same
//! coercions and the same messages, so a client sees the identical `400` envelope. Field errors are reported in
//! model order, then extra keys (when forbidden) in input order; at most three, joined with `"; "`.

use serde_json::{Map, Value, json};

/// A numeric bound as the Python wrote it: the value and how Pydantic prints it.
pub type Bound = Option<(f64, &'static str)>;

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
    /// A number within its bounds; required when there is no default.
    Float {
        gt: Bound,
        ge: Bound,
        le: Bound,
        default: Option<f64>,
    },
    /// An integer with `ge <= x <= le`.
    Int { ge: i64, le: i64, default: i64 },
    /// Any JSON object; `{}` when absent.
    Dict,
    /// A list of `min..=max` items, each validated against a nested model.
    List {
        min: usize,
        max: usize,
        item: &'static Model,
    },
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

/// Validate one field's present value, pushing `(path, message)` errors.
fn check(kind: Kind, v: &Value, path: &str, errors: &mut Vec<String>) -> Option<Value> {
    let mut fail = |m: String| {
        errors.push(format!("{path}: {m}"));
        None
    };
    match kind {
        Kind::Str {
            min, max, nullable, ..
        } => match v {
            Value::Null if nullable => Some(Value::Null),
            Value::String(s) => {
                let n = s.chars().count();
                if n < min {
                    fail(format!("String should have at least {min} {}", plural(min)))
                } else if n > max {
                    fail(format!("String should have at most {max} {}", plural(max)))
                } else {
                    Some(json!(s))
                }
            }
            _ => fail("Input should be a valid string".to_owned()),
        },
        Kind::Float { gt, ge, le, .. } => {
            let x = match as_float(v) {
                Ok(x) => x,
                Err(e) => return fail(e.to_owned()),
            };
            if let Some((b, shown)) = le
                && (x.is_nan() || x > b)
            {
                fail(format!("Input should be less than or equal to {shown}"))
            } else if let Some((b, shown)) = gt
                && x <= b
            {
                fail(format!("Input should be greater than {shown}"))
            } else if let Some((b, shown)) = ge
                && x < b
            {
                fail(format!("Input should be greater than or equal to {shown}"))
            } else {
                Some(json!(x))
            }
        }
        Kind::Int { ge, le, .. } => match as_int(v) {
            Err(e) => fail(e.to_owned()),
            Ok(x) if x < ge => fail(format!("Input should be greater than or equal to {ge}")),
            Ok(x) if x > le => fail(format!("Input should be less than or equal to {le}")),
            Ok(x) => Some(json!(x)),
        },
        Kind::Dict => match v {
            Value::Object(_) => Some(v.clone()),
            _ => fail("Input should be a valid dictionary".to_owned()),
        },
        Kind::List { min, max, item } => {
            let Value::Array(items) = v else {
                return fail("Input should be a valid list".to_owned());
            };
            let before = errors.len();
            let mut out = Vec::with_capacity(items.len());
            for (i, x) in items.iter().enumerate() {
                let at = format!("{path}.{i}");
                if let Value::Object(o) = x {
                    out.push(Value::Object(fields(o, *item, &at, errors)));
                } else {
                    errors.push(format!(
                        "{at}: Input should be a valid dictionary or object to extract fields from"
                    ));
                }
            }
            let items_word = |n: usize| if n == 1 { "item" } else { "items" };
            if errors.len() > before {
                None
            } else if items.len() < min {
                errors.push(format!(
                    "{path}: List should have at least {min} {} after validation, not {}",
                    items_word(min),
                    items.len()
                ));
                None
            } else if items.len() > max {
                errors.push(format!(
                    "{path}: List should have at most {max} {} after validation, not {}",
                    items_word(max),
                    items.len()
                ));
                None
            } else {
                Some(Value::Array(out))
            }
        }
    }
}

/// Validate an object's fields against `model`, prefixing error paths with `prefix` (empty at the top level).
fn fields(
    obj: &Map<String, Value>,
    model: Model,
    prefix: &str,
    errors: &mut Vec<String>,
) -> Map<String, Value> {
    let path = |name: &str| {
        if prefix.is_empty() {
            name.to_owned()
        } else {
            format!("{prefix}.{name}")
        }
    };
    let mut out = Map::new();
    for Field(name, kind) in model.fields {
        let at = path(name);
        let value = match (obj.get(*name), *kind) {
            (Some(v), k) => check(k, v, &at, errors),
            // an optional string defaults to null; any other string without a default is required
            (
                None,
                Kind::Str {
                    default: Some(d), ..
                },
            ) => Some(json!(d)),
            (
                None,
                Kind::Str {
                    default: None,
                    nullable: true,
                    ..
                },
            ) => Some(Value::Null),
            (
                None,
                Kind::Float {
                    default: Some(d), ..
                },
            ) => Some(json!(d)),
            (None, Kind::Int { default, .. }) => Some(json!(default)),
            (None, Kind::Dict) => Some(json!({})),
            (None, _) => {
                errors.push(format!("{at}: Field required"));
                None
            }
        };
        if let Some(v) = value {
            out.insert((*name).to_owned(), v);
        }
    }
    if model.forbid_extra {
        for k in obj
            .keys()
            .filter(|k| !model.fields.iter().any(|f| f.0 == k.as_str()))
        {
            errors.push(format!("{}: Extra inputs are not permitted", path(k)));
        }
    }
    out
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
    let mut errors = Vec::new();
    let out = fields(obj, model, "", &mut errors);
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
