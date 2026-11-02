//! The length-prefixed framing of the localhost seam between the stream server and Godot (Python
//! `stewie.stream.framing`): both directions carry a 4-byte big-endian length, then that many payload bytes (JPEG
//! frames from Godot, UTF-8 JSON commands to it).

/// The prefix length.
pub const HEADER_LEN: usize = 4;
/// The ceiling on one frame's payload (a 1280 x 720 JPEG is well under 1 MB).
pub const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;

/// `payload` behind its 4-byte big-endian length.
///
/// # Errors
/// A payload over [`MAX_FRAME_BYTES`].
pub fn pack_frame(payload: &[u8]) -> Result<Vec<u8>, String> {
    let n = payload.len();
    if n > MAX_FRAME_BYTES {
        return Err(format!(
            "frame payload {n} bytes exceeds MAX_FRAME_BYTES {MAX_FRAME_BYTES}"
        ));
    }
    let mut out = Vec::with_capacity(HEADER_LEN + n);
    out.extend_from_slice(&u32::try_from(n).map_err(|e| e.to_string())?.to_be_bytes());
    out.extend_from_slice(payload);
    Ok(out)
}

/// The incremental, sans-I/O parser: feed byte chunks as they arrive, get every complete payload so far; a partial
/// tail is kept for the next feed.
#[derive(Debug, Default)]
pub struct FrameDecoder {
    buf: Vec<u8>,
}

impl FrameDecoder {
    /// The complete payloads `data` finishes.
    ///
    /// # Errors
    /// A declared length over [`MAX_FRAME_BYTES`].
    pub fn feed(&mut self, data: &[u8]) -> Result<Vec<Vec<u8>>, String> {
        self.buf.extend_from_slice(data);
        let mut out = Vec::new();
        while self.buf.len() >= HEADER_LEN {
            let n =
                u32::from_be_bytes([self.buf[0], self.buf[1], self.buf[2], self.buf[3]]) as usize;
            if n > MAX_FRAME_BYTES {
                return Err(format!("declared frame length {n} exceeds MAX_FRAME_BYTES"));
            }
            if self.buf.len() < HEADER_LEN + n {
                break;
            }
            out.push(self.buf[HEADER_LEN..HEADER_LEN + n].to_vec());
            self.buf.drain(..HEADER_LEN + n);
        }
        Ok(out)
    }

    /// Bytes buffered short of a complete frame.
    #[must_use]
    pub fn pending(&self) -> usize {
        self.buf.len()
    }
}
