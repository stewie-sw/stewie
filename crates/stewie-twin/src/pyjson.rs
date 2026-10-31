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
    write_value(&mut out, v)?;
    Ok(out)
}

fn write_value(out: &mut String, v: &Value) -> Result<(), TwinError> {
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
                    out.push_str(", ");
                }
                write_value(out, x)?;
            }
            out.push(']');
        }
        Value::Object(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            out.push('{');
            for (i, k) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_str(out, k);
                out.push_str(": ");
                write_value(out, &m[k])?;
            }
            out.push('}');
        }
    }
    Ok(())
}

fn write_str(out: &mut String, s: &str) {
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
