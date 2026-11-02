//! The few Python value semantics the stream's contracts lean on: `float(v)`, `int(v)`, truthiness, `str(v)` and
//! float `%`.

use serde_json::Value;

/// Python's digit-group underscores (`1_000`) dropped, when every one sits between two digits.
fn ungroup(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let ok = b.iter().enumerate().all(|(i, c)| {
        *c != b'_'
            || (i > 0 && i + 1 < b.len() && b[i - 1].is_ascii_digit() && b[i + 1].is_ascii_digit())
    });
    ok.then(|| s.replace('_', ""))
}

/// Python's `float(v)`; `None` where it raises (`TypeError`, `ValueError`).
#[must_use]
pub fn float(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::String(s) => ungroup(s.trim()).and_then(|t| t.parse().ok()),
        _ => None,
    }
}

/// Python's `int(v)` (a float truncated toward zero); `None` where it raises.
#[must_use]
#[allow(clippy::cast_possible_truncation)] // Python's int() truncates; beyond i64 saturates
pub fn int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|x| x.is_finite())
                .map(|x| x.trunc() as i64)
        }),
        Value::Bool(b) => Some(i64::from(*b)),
        Value::String(s) => ungroup(s.trim()).and_then(|t| t.parse().ok()),
        _ => None,
    }
}

/// Python's `bool(v)`.
#[must_use]
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|x| x != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

/// Python's `str(v)` of a JSON value.
#[must_use]
pub fn str_of(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => stewie_twin::pyjson::repr(other),
    }
}

/// Python's float `x % m` for `m > 0`: the result takes the divisor's sign, and a zero is `+0.0`.
#[must_use]
pub fn fmod(x: f64, m: f64) -> f64 {
    let r = x % m;
    if r == 0.0 {
        0.0
    } else if r < 0.0 {
        r + m
    } else {
        r
    }
}
