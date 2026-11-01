//! Python's `json.dumps(obj, sort_keys=True)` with its defaults (`ensure_ascii=True`, separators
//! `", "` and `": "`), byte for byte, so a sha256 over it matches the Python twin's. Floats use Python's
//! `repr`: the shortest round-trip digits, positional when the decimal exponent is in `[-4, 16)`, else
//! `d.ddde+XX`. Non-finite floats are refused (strict JSON).

use std::fmt::Write as _;

use serde_json::Value;

use crate::TwinError;

/// Serialise `v` exactly as Python's `json.dumps(v, sort_keys=True)`.
///
/// # Errors
/// A non-finite float (Python would write `NaN`/`Infinity`, which is not JSON).
pub fn dumps(v: &Value) -> Result<String, TwinError> {
    let mut out = String::new();
    write_value(&mut out, v, (", ", ": "))?;
    Ok(out)
}

/// [`dumps`] with `separators=(",", ":")`: Python's `json.dumps(v, sort_keys=True, separators=(",", ":"))`.
///
/// # Errors
/// A non-finite float.
pub fn dumps_compact(v: &Value) -> Result<String, TwinError> {
    let mut out = String::new();
    write_value(&mut out, v, (",", ":"))?;
    Ok(out)
}

fn write_value(out: &mut String, v: &Value, seps: (&str, &str)) -> Result<(), TwinError> {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                let _ = write!(out, "{i}");
            } else if let Some(u) = n.as_u64() {
                let _ = write!(out, "{u}");
            } else {
                let x = n
                    .as_f64()
                    .ok_or_else(|| TwinError::Invalid(format!("number {n}")))?;
                out.push_str(&float_repr(x)?);
            }
        }
        Value::String(s) => write_str(out, s),
        Value::Array(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push_str(seps.0);
                }
                write_value(out, x, seps)?;
            }
            out.push(']');
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            out.push('{');
            for (i, k) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.push_str(seps.0);
                }
                write_str(out, k);
                out.push_str(seps.1);
                write_value(out, &m[k], seps)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

/// A JSON string literal as Python's `json.dumps` writes it (`ensure_ascii=True`).
pub fn write_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    let _ = write!(out, "\\u{unit:04x}");
                }
            }
        }
    }
    out.push('"');
}

/// Python `repr(float)`.
///
/// # Errors
/// A NaN or infinite value.
pub fn float_repr(x: f64) -> Result<String, TwinError> {
    if !x.is_finite() {
        return Err(TwinError::Invalid(format!(
            "non-finite float {x} has no JSON form"
        )));
    }
    // Rust's `{:e}` is the shortest round-trip form: "-1.2345e-7"
    let sci = format!("{x:e}");
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let (sign, mant) = mant.strip_prefix('-').map_or(("", mant), |m| ("-", m));
    let digits: String = mant.chars().filter(char::is_ascii_digit).collect();
    let exp: i32 = exp.parse().map_err(|_| TwinError::Invalid(sci.clone()))?;
    let decpt = exp + 1; // x = 0.d1d2... * 10^decpt
    let n = i32::try_from(digits.len()).map_err(|_| TwinError::Invalid(sci.clone()))?;
    let body = if (-3..=16).contains(&decpt) {
        if decpt <= 0 {
            format!(
                "0.{}{digits}",
                "0".repeat(usize::try_from(-decpt).unwrap_or(0))
            )
        } else if decpt >= n {
            format!(
                "{digits}{}.0",
                "0".repeat(usize::try_from(decpt - n).unwrap_or(0))
            )
        } else {
            let (a, b) = digits.split_at(usize::try_from(decpt).unwrap_or(0));
            format!("{a}.{b}")
        }
    } else {
        let (first, rest) = digits.split_at(1);
        let e = decpt - 1;
        let frac = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        format!(
            "{first}{frac}e{}{:02}",
            if e < 0 { '-' } else { '+' },
            e.abs()
        )
    };
    Ok(format!("{sign}{body}"))
}

/// Python's `repr` of a string: single quotes unless the text holds a single quote and no double quote, with
/// Python's escapes for backslash, the control characters and the chosen quote.
#[must_use]
pub fn repr_str(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                let _ = write!(out, "\\x{:02x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push(q);
    out
}

/// Python's `repr` of the value `json.loads` makes from `v` (objects with this crate's sorted keys).
#[must_use]
pub fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".to_owned(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_owned(),
        Value::Number(n) => n
            .as_i64()
            .map(|i| i.to_string())
            .or_else(|| n.as_u64().map(|u| u.to_string()))
            .unwrap_or_else(|| {
                n.as_f64()
                    .and_then(|x| float_repr(x).ok())
                    .unwrap_or_else(|| n.to_string())
            }),
        Value::String(s) => repr_str(s),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, x)| format!("{}: {}", repr_str(k), repr(x)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// Python's `repr` of a list of strings (`['a', 'b']`).
#[must_use]
pub fn repr_list<S: AsRef<str>>(items: &[S]) -> String {
    format!(
        "[{}]",
        items
            .iter()
            .map(|s| repr_str(s.as_ref()))
            .collect::<Vec<_>>()
            .join(", ")
    )
}
