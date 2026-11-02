//! RW-51d: the stream's browser contract and seam framing equal the Python's (`stream_protocol_cases`, SYNTHETIC
//! inputs labelled there): every normalized session config or its refusal, every relayed control frame, and the
//! framed stream decoded whole from every split point.

use serde_json::Value;
use stewie_stream::framing::{FrameDecoder, pack_frame};
use stewie_stream::protocol::{normalize_input, parse_config_text};

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn configs_and_control_frames_equal_the_pythons() {
    let fx = stewie_oracle::load("stream_protocol_cases")
        .unwrap()
        .payload;
    for c in fx["configs"].as_array().unwrap() {
        let text = c["text"].as_str().unwrap();
        let got = parse_config_text(text.as_bytes());
        if let Some(out) = c.get("out") {
            assert_eq!(&Value::Object(got.unwrap()), out, "{text}");
        } else if let Some(e) = c.get("error") {
            assert_eq!(got.unwrap_err(), e.as_str().unwrap(), "{text}");
        } else {
            // the parser's own words differ; the refusal is the same
            assert!(
                got.unwrap_err()
                    .starts_with(c["error_prefix"].as_str().unwrap()),
                "{text}"
            );
        }
    }
    for c in fx["inputs"].as_array().unwrap() {
        let text = c["text"].as_str().unwrap();
        let got = Value::Object(normalize_input(text.as_bytes()));
        assert_eq!(&got, &c["out"], "{text}");
        // as text too: a -0.0 equals 0.0 as a number but is not the byte Godot is sent
        assert_eq!(got.to_string(), c["out"].to_string(), "{text}");
    }
    assert_eq!(fx["configs"].as_array().unwrap().len(), 44, "vacuity");
}

#[test]
fn framing_equals_the_pythons_at_every_split() {
    let fx = stewie_oracle::load("stream_protocol_cases")
        .unwrap()
        .payload;
    let f = &fx["framing"];
    let payloads: Vec<Vec<u8>> = f["payloads_hex"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| unhex(p.as_str().unwrap()))
        .collect();
    let stream: Vec<u8> = payloads
        .iter()
        .flat_map(|p| pack_frame(p).unwrap())
        .collect();
    assert_eq!(stream, unhex(f["stream_hex"].as_str().unwrap()));
    for s in f["splits"].as_array().unwrap() {
        let cut = usize::try_from(s["cut"].as_u64().unwrap()).unwrap();
        let mut d = FrameDecoder::default();
        let first = d.feed(&stream[..cut]).unwrap();
        assert_eq!(
            first.len() as u64,
            s["frames"].as_u64().unwrap(),
            "cut {cut}"
        );
        assert_eq!(
            d.pending() as u64,
            s["pending"].as_u64().unwrap(),
            "cut {cut}"
        );
        let rest = d.feed(&stream[cut..]).unwrap();
        assert_eq!(rest.len() as u64, s["rest"].as_u64().unwrap(), "cut {cut}");
        assert_eq!(
            first.into_iter().chain(rest).collect::<Vec<_>>(),
            payloads,
            "cut {cut}"
        );
    }
    // an over-ceiling declared length is refused, not buffered
    assert!(
        FrameDecoder::default()
            .feed(&u32::MAX.to_be_bytes())
            .is_err()
    );
    assert!(pack_frame(&vec![0; stewie_stream::framing::MAX_FRAME_BYTES + 1]).is_err());
}
