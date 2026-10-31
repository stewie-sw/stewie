//! The numpy behaviour the twin's records depend on: float64 `sum` (pairwise, so a hashed volume matches
//! the Python's to the last bit), Python's `round(x, n)`, and the `.npy` / `.npz` files the Python twin
//! persists (zip of version 1 `.npy` arrays: `<f8`, `<i8`, `<u4`, `|u1` and 0-d `<U` strings; written
//! uncompressed, read stored or deflated, since `numpy.savez_compressed` deflates).

use std::collections::BTreeMap;
use std::io::{Read, Seek, Write};

use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

use crate::TwinError;

fn bad(m: impl Into<String>) -> TwinError {
    TwinError::Invalid(m.into())
}

/// numpy's float64 `add.reduce` over a contiguous array: pairwise summation in blocks of 128 with eight
/// accumulators (`pairwise_sum` in numpy's `loops_utils.h`), started from the identity 0.
#[must_use]
pub fn sum(a: &[f64]) -> f64 {
    0.0 + pairwise(a)
}

fn pairwise(a: &[f64]) -> f64 {
    let n = a.len();
    if n < 8 {
        a.iter().fold(0.0, |s, v| s + v)
    } else if n <= 128 {
        let mut r: [f64; 8] = a[..8].try_into().unwrap_or([0.0; 8]);
        let whole = n - n % 8;
        for chunk in a[8..whole].chunks_exact(8) {
            for (acc, v) in r.iter_mut().zip(chunk) {
                *acc += v;
            }
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for v in &a[whole..] {
            res += v;
        }
        res
    } else {
        let mut half = n / 2;
        half -= half % 8;
        pairwise(&a[..half]) + pairwise(&a[half..])
    }
}

/// Python's float floor division `a // b` (`CPython` `float_floor_div`): `fmod`, a sign fix, then the quotient
/// rounded so it lands on the integer `floor` would miss, e.g. `1 // 0.1 == 9` where `floor(1 / 0.1) == 10`.
#[must_use]
pub fn floordiv(a: f64, b: f64) -> f64 {
    let m = a % b;
    let mut div = (a - m) / b;
    if m != 0.0 && ((b < 0.0) != (m < 0.0)) {
        div -= 1.0;
    }
    if div == 0.0 {
        return 0.0f64.copysign(a / b);
    }
    let mut q = div.floor();
    if div - q > 0.5 {
        q += 1.0;
    }
    q
}

/// Python's `round(x, digits)`: the double nearest the decimal rounding of the exact value, ties to even.
#[must_use]
pub fn round(x: f64, digits: usize) -> f64 {
    format!("{x:.digits$}").parse().unwrap_or(x)
}

/// One array of an `.npz`.
#[derive(Debug, Clone, PartialEq)]
pub enum Array {
    F64 {
        shape: Vec<usize>,
        data: Vec<f64>,
    },
    I64 {
        shape: Vec<usize>,
        data: Vec<i64>,
    },
    U32 {
        shape: Vec<usize>,
        data: Vec<u32>,
    },
    U8 {
        shape: Vec<usize>,
        data: Vec<u8>,
    },
    /// A 0-d unicode string (`<U{n}`).
    Str(String),
}

/// The value of `key` in a numpy header dict (`'descr': '<f8', 'shape': (3, 4), ...`).
fn header_field<'a>(h: &'a str, key: &str) -> Result<&'a str, TwinError> {
    let at = h
        .find(&format!("'{key}':"))
        .ok_or_else(|| bad(format!("npy header without {key}: {h}")))?;
    Ok(h[at + key.len() + 3..].trim_start())
}

fn parse_npy(bytes: &[u8]) -> Result<Array, TwinError> {
    if bytes.len() < 10 || &bytes[..6] != b"\x93NUMPY" {
        return Err(bad("not an .npy array"));
    }
    let (hlen, start) = match bytes[6] {
        1 => (usize::from(u16::from_le_bytes([bytes[8], bytes[9]])), 10),
        2 | 3 if bytes.len() >= 12 => (
            usize::try_from(u32::from_le_bytes([
                bytes[8], bytes[9], bytes[10], bytes[11],
            ]))
            .map_err(|e| bad(e.to_string()))?,
            12,
        ),
        v => return Err(bad(format!("npy version {v}"))),
    };
    let header = std::str::from_utf8(
        bytes
            .get(start..start + hlen)
            .ok_or_else(|| bad("short npy header"))?,
    )
    .map_err(|e| bad(e.to_string()))?;
    let descr = header_field(header, "descr")?
        .trim_start_matches('\'')
        .split('\'')
        .next()
        .unwrap_or("");
    if header_field(header, "fortran_order")?.starts_with("True") {
        return Err(bad("fortran-order arrays are not written by the twin"));
    }
    let shape_txt = header_field(header, "shape")?;
    let shape: Vec<usize> = shape_txt[1..shape_txt.find(')').unwrap_or(1)]
        .split(',')
        .filter(|t| !t.trim().is_empty())
        .map(|t| {
            t.trim()
                .parse()
                .map_err(|_| bad(format!("shape {shape_txt}")))
        })
        .collect::<Result<_, _>>()?;
    let count: usize = shape.iter().product();
    let data = &bytes[start + hlen..];
    let words = |width: usize| -> Result<std::slice::ChunksExact<'_, u8>, TwinError> {
        if data.len() != count * width {
            return Err(bad(format!("{descr} {shape:?}: {} data bytes", data.len())));
        }
        Ok(data.chunks_exact(width))
    };
    let eight = |c: &[u8]| -> [u8; 8] { c.try_into().unwrap_or([0; 8]) };
    match descr {
        "<f8" => Ok(Array::F64 {
            data: words(8)?.map(|c| f64::from_le_bytes(eight(c))).collect(),
            shape,
        }),
        "<i8" => Ok(Array::I64 {
            data: words(8)?.map(|c| i64::from_le_bytes(eight(c))).collect(),
            shape,
        }),
        "|u1" => Ok(Array::U8 {
            data: words(1)?.map(|c| c[0]).collect(),
            shape,
        }),
        "<u4" => Ok(Array::U32 {
            data: words(4)?
                .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                .collect(),
            shape,
        }),
        u if u.starts_with("<U") && shape.is_empty() => {
            let n: usize = u[2..].parse().map_err(|_| bad(format!("descr {u}")))?;
            if data.len() != 4 * n {
                return Err(bad(format!("{u}: {} data bytes", data.len())));
            }
            data.chunks_exact(4)
                .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                .take_while(|&c| c != 0)
                .map(|c| char::from_u32(c).ok_or_else(|| bad("invalid code point")))
                .collect::<Result<String, _>>()
                .map(Array::Str)
        }
        other => Err(bad(format!(
            "unsupported npy dtype {other} with shape {shape:?}"
        ))),
    }
}

fn npy_bytes(a: &Array) -> Vec<u8> {
    let shape = |s: &[usize]| match s {
        [] => "()".to_owned(),
        [n] => format!("({n},)"),
        _ => format!(
            "({})",
            s.iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>()
                .join(", ")
        ),
    };
    let (descr, dims, body): (String, String, Vec<u8>) = match a {
        Array::F64 { shape: s, data } => (
            "<f8".into(),
            shape(s),
            data.iter().flat_map(|v| v.to_le_bytes()).collect(),
        ),
        Array::I64 { shape: s, data } => (
            "<i8".into(),
            shape(s),
            data.iter().flat_map(|v| v.to_le_bytes()).collect(),
        ),
        Array::U8 { shape: s, data } => ("|u1".into(), shape(s), data.clone()),
        Array::U32 { shape: s, data } => (
            "<u4".into(),
            shape(s),
            data.iter().flat_map(|v| v.to_le_bytes()).collect(),
        ),
        Array::Str(text) => {
            let n = text.chars().count().max(1);
            let mut b: Vec<u8> = text
                .chars()
                .flat_map(|c| u32::from(c).to_le_bytes())
                .collect();
            b.resize(4 * n, 0);
            (format!("<U{n}"), "()".into(), b)
        }
    };
    let mut header = format!("{{'descr': '{descr}', 'fortran_order': False, 'shape': {dims}, }}");
    // numpy pads the header with spaces so the data starts on a 64-byte boundary, ending in a newline
    while (10 + header.len() + 1) % 64 != 0 {
        header.push(' ');
    }
    header.push('\n');
    let mut out = b"\x93NUMPY\x01\x00".to_vec();
    out.extend_from_slice(
        &u16::try_from(header.len())
            .unwrap_or(u16::MAX)
            .to_le_bytes(),
    );
    out.extend_from_slice(header.as_bytes());
    out.extend_from_slice(&body);
    out
}

/// Read every array of an `.npz`, keyed by name without the `.npy` suffix.
///
/// # Errors
/// A malformed zip or array, or an array type the twin does not write.
pub fn read_npz(r: impl Read + Seek) -> Result<BTreeMap<String, Array>, TwinError> {
    let mut z = ZipArchive::new(r).map_err(|e| bad(format!("npz: {e}")))?;
    let mut out = BTreeMap::new();
    for i in 0..z.len() {
        let mut f = z.by_index(i).map_err(|e| bad(format!("npz: {e}")))?;
        let name = f.name().trim_end_matches(".npy").to_owned();
        let mut bytes = Vec::new();
        f.read_to_end(&mut bytes).map_err(TwinError::Io)?;
        out.insert(name, parse_npy(&bytes)?);
    }
    Ok(out)
}

/// Write `arrays` as an uncompressed `.npz` (what `numpy.savez` writes), in the given order.
///
/// # Errors
/// An I/O failure.
pub fn write_npz(w: impl Write + Seek, arrays: &[(&str, Array)]) -> Result<(), TwinError> {
    let mut z = ZipWriter::new(w);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
    for (name, a) in arrays {
        z.start_file(format!("{name}.npy"), opts)
            .map_err(|e| bad(format!("npz: {e}")))?;
        z.write_all(&npy_bytes(a)).map_err(TwinError::Io)?;
    }
    z.finish().map_err(|e| bad(format!("npz: {e}")))?;
    Ok(())
}

/// Write `arrays` as an `.npz` at `path` atomically (see [`crate::write_atomic`]).
///
/// # Errors
/// An I/O failure.
pub fn save_npz(path: &std::path::Path, arrays: &[(&str, Array)]) -> Result<(), TwinError> {
    let mut buf = std::io::Cursor::new(Vec::new());
    write_npz(&mut buf, arrays)?;
    crate::write_atomic(path, &buf.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[allow(clippy::float_cmp)] // floor division returns exact integers
    fn floor_division_is_pythons() {
        // values from CPython: 1 // 0.1, 7 // 2, -7 // 2, 7.5 // -2, -0.0 // 3, 0.7 // 0.1, 1e-300 // 1e300
        for (a, b, q) in [
            (1.0, 0.1, 9.0),
            (7.0, 2.0, 3.0),
            (-7.0, 2.0, -4.0),
            (7.5, -2.0, -4.0),
            (-0.0, 3.0, -0.0),
            (0.7, 0.1, 6.0),
            (1e-300, 1e300, 0.0),
        ] {
            let got = floordiv(a, b);
            assert!(
                got == q && got.is_sign_negative() == q.is_sign_negative(),
                "{a} // {b} = {got}, want {q}"
            );
        }
    }

    #[test]
    fn arrays_round_trip_through_an_npz() {
        // SYNTHETIC arrays (labelled): every dtype and shape the twin writes
        let arrays = [
            (
                "delta",
                Array::F64 {
                    shape: vec![2, 3],
                    data: vec![0.5, -1.0, 0.0, 2.25, 1e-300, -0.0],
                },
            ),
            ("meta", Array::Str("{\"site\": \"haworth \u{e9}\"}".into())),
            (
                "hist_idx",
                Array::I64 {
                    shape: vec![0],
                    data: vec![],
                },
            ),
            (
                "hist_off",
                Array::I64 {
                    shape: vec![1],
                    data: vec![0],
                },
            ),
            (
                "passes",
                Array::U32 {
                    shape: vec![2, 2],
                    data: vec![0, 1, 3, u32::MAX],
                },
            ),
        ];
        let mut buf = std::io::Cursor::new(Vec::new());
        write_npz(&mut buf, &arrays).unwrap();
        let back = read_npz(std::io::Cursor::new(buf.into_inner())).unwrap();
        for (name, a) in &arrays {
            assert_eq!(&back[*name], a, "{name}");
        }
        assert!(parse_npy(b"\x93NUMPY\x01\x00").is_err());
    }
}
