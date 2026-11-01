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
    /// Any JSON array (a bare `list`); required.
    AnyList,
    /// A bare `list` defaulting to `[]`.
    AnyListDefault,
    /// A `tuple[int, int]`: exactly two integers; required.
    IntPair,
    /// A `tuple[float, float]`: exactly two numbers; required.
    FloatPair,
    /// A `list[tuple[float, float]]`, each pair reported at its index; required.
    FloatPairList,
    /// A required JSON object (a `dict` field without a default).
    DictRequired,
    /// A `list[dict]` of `min..=max` objects; required.
    DictList { min: usize, max: usize },
    /// `T | None` with a `None` default: null or absent is null, else the inner kind.
    Opt(&'static Kind),
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
pub(crate) fn as_float(v: &Value) -> Result<f64, &'static str> {
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
        Kind::Dict | Kind::DictRequired => match v {
            Value::Object(_) => Some(v.clone()),
            _ => fail("Input should be a valid dictionary".to_owned()),
        },
        Kind::AnyList | Kind::AnyListDefault => match v {
            Value::Array(_) => Some(v.clone()),
            _ => fail("Input should be a valid list".to_owned()),
        },
        Kind::IntPair => check_pair(v, path, errors, false),
        Kind::FloatPair => check_pair(v, path, errors, true),
        Kind::FloatPairList => match v {
            Value::Array(items) => {
                let before = errors.len();
                let out: Vec<Value> = items
                    .iter()
                    .enumerate()
                    .filter_map(|(i, x)| check_pair(x, &format!("{path}.{i}"), errors, true))
                    .collect();
                (errors.len() == before).then_some(Value::Array(out))
            }
            _ => fail("Input should be a valid list".to_owned()),
        },
        Kind::DictList { min, max } => check_dict_list(v, min, max, path, errors),
        Kind::Opt(inner) => match v {
            Value::Null => Some(Value::Null),
            _ => check(*inner, v, path, errors),
        },
        Kind::List { min, max, item } => check_list(v, min, max, item, path, errors),
    }
}

/// A `list[dict]` of `min..=max` objects: item errors first, then the length.
fn check_dict_list(
    v: &Value,
    min: usize,
    max: usize,
    path: &str,
    errors: &mut Vec<String>,
) -> Option<Value> {
    let Value::Array(items) = v else {
        errors.push(format!("{path}: Input should be a valid list"));
        return None;
    };
    let before = errors.len();
    for (i, x) in items.iter().enumerate() {
        if !x.is_object() {
            errors.push(format!("{path}.{i}: Input should be a valid dictionary"));
        }
    }
    let word = |n: usize| if n == 1 { "item" } else { "items" };
    if errors.len() > before {
        return None;
    }
    if items.len() < min {
        errors.push(format!(
            "{path}: List should have at least {min} {} after validation, not {}",
            word(min),
            items.len()
        ));
        return None;
    }
    if items.len() > max {
        errors.push(format!(
            "{path}: List should have at most {max} {} after validation, not {}",
            word(max),
            items.len()
        ));
        return None;
    }
    Some(v.clone())
}

/// A `tuple[int, int]` (or of floats): two values, each reported at its index.
fn check_pair(v: &Value, path: &str, errors: &mut Vec<String>, floats: bool) -> Option<Value> {
    let Value::Array(items) = v else {
        errors.push(format!("{path}: Input should be a valid tuple"));
        return None;
    };
    if items.len() > 2 {
        errors.push(format!(
            "{path}: Tuple should have at most 2 items after validation, not {}",
            items.len()
        ));
        return None;
    }
    let before = errors.len();
    let mut out = Vec::new();
    for i in 0..2 {
        let at = format!("{path}.{i}");
        let item = items.get(i).map(|x| {
            if floats {
                as_float(x).map(|f| json!(f))
            } else {
                as_int(x).map(|n| json!(n))
            }
        });
        match item {
            Some(Ok(x)) => out.push(x),
            Some(Err(e)) => errors.push(format!("{at}: {e}")),
            None => errors.push(format!("{at}: Field required")),
        }
    }
    (errors.len() == before).then_some(Value::Array(out))
}

/// A list of `min..=max` items, each a nested model: item errors first, then the length.
fn check_list(
    v: &Value,
    min: usize,
    max: usize,
    item: &Model,
    path: &str,
    errors: &mut Vec<String>,
) -> Option<Value> {
    let Value::Array(items) = v else {
        errors.push(format!("{path}: Input should be a valid list"));
        return None;
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
    let word = |n: usize| if n == 1 { "item" } else { "items" };
    if errors.len() > before {
        None
    } else if items.len() < min {
        errors.push(format!(
            "{path}: List should have at least {min} {} after validation, not {}",
            word(min),
            items.len()
        ));
        None
    } else if items.len() > max {
        errors.push(format!(
            "{path}: List should have at most {max} {} after validation, not {}",
            word(max),
            items.len()
        ));
        None
    } else {
        Some(Value::Array(out))
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
                Kind::Float {
                    default: Some(d), ..
                },
            ) => Some(json!(d)),
            (None, Kind::Int { default, .. }) => Some(json!(default)),
            (None, Kind::Dict) => Some(json!({})),
            (None, Kind::AnyListDefault) => Some(json!([])),
            // an optional value (or an optional string) defaults to null
            (
                None,
                Kind::Opt(_)
                | Kind::Str {
                    default: None,
                    nullable: true,
                    ..
                },
            ) => Some(Value::Null),
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

/// A JSON value with every object's key order kept as the client sent it (the workspace's `serde_json` sorts
/// map keys), so the Python's `repr` of a request field can be reproduced exactly.
#[derive(Debug, Clone, PartialEq)]
pub enum Ordered {
    Null,
    Bool(bool),
    Number(serde_json::Number),
    String(String),
    Array(Vec<Ordered>),
    /// Keys in first-seen order; a repeated key keeps its first position and its last value (`json.loads`).
    Object(Vec<(String, Ordered)>),
}

impl<'de> serde::Deserialize<'de> for Ordered {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = Ordered;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("a JSON value")
            }
            fn visit_unit<E>(self) -> Result<Ordered, E> {
                Ok(Ordered::Null)
            }
            fn visit_bool<E>(self, b: bool) -> Result<Ordered, E> {
                Ok(Ordered::Bool(b))
            }
            fn visit_i64<E>(self, n: i64) -> Result<Ordered, E> {
                Ok(Ordered::Number(n.into()))
            }
            fn visit_u64<E>(self, n: u64) -> Result<Ordered, E> {
                Ok(Ordered::Number(n.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, x: f64) -> Result<Ordered, E> {
                serde_json::Number::from_f64(x)
                    .map(Ordered::Number)
                    .ok_or_else(|| E::custom("a non-finite number"))
            }
            fn visit_str<E>(self, s: &str) -> Result<Ordered, E> {
                Ok(Ordered::String(s.to_owned()))
            }
            fn visit_string<E>(self, s: String) -> Result<Ordered, E> {
                Ok(Ordered::String(s))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut a: A,
            ) -> Result<Ordered, A::Error> {
                let mut out = Vec::new();
                while let Some(x) = a.next_element()? {
                    out.push(x);
                }
                Ok(Ordered::Array(out))
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut a: A,
            ) -> Result<Ordered, A::Error> {
                let mut out: Vec<(String, Ordered)> = Vec::new();
                while let Some((k, v)) = a.next_entry::<String, Ordered>()? {
                    match out.iter_mut().find(|(n, _)| *n == k) {
                        Some(slot) => slot.1 = v,
                        None => out.push((k, v)),
                    }
                }
                Ok(Ordered::Object(out))
            }
        }
        d.deserialize_any(V)
    }
}

impl Ordered {
    /// A field of an object, by key.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&Ordered> {
        match self {
            Self::Object(m) => m.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// Python's `repr` of the value `json.loads` would have made.
    #[must_use]
    pub fn py_repr(&self) -> String {
        match self {
            Self::Null => "None".to_owned(),
            Self::Bool(b) => if *b { "True" } else { "False" }.to_owned(),
            Self::Number(n) => n
                .as_i64()
                .map(|i| i.to_string())
                .or_else(|| n.as_u64().map(|u| u.to_string()))
                .unwrap_or_else(|| {
                    n.as_f64()
                        .and_then(|x| stewie_twin::pyjson::float_repr(x).ok())
                        .unwrap_or_else(|| n.to_string())
                }),
            Self::String(s) => crate::operators::py_repr(s),
            Self::Array(a) => format!(
                "[{}]",
                a.iter().map(Self::py_repr).collect::<Vec<_>>().join(", ")
            ),
            Self::Object(m) => format!(
                "{{{}}}",
                m.iter()
                    .map(|(k, v)| format!("{}: {}", crate::operators::py_repr(k), v.py_repr()))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }
}
