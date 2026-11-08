//! Length-framed native JPEG parser. Never decode/re-encode, never search EOI inside APP segments.
use bytes::{Buf, Bytes, BytesMut};

const MAX_HEADERS: usize = 16 * 1024;
pub struct MjpegParser {
    data: BytesMut,
    length: Option<usize>,
    online: bool,
    max_frame: usize,
}
impl MjpegParser {
    pub fn new(max_frame: usize) -> Self {
        Self {
            data: BytesMut::new(),
            length: None,
            online: true,
            max_frame,
        }
    }
    pub fn push(&mut self, part: &[u8]) -> Result<(), &'static str> {
        if part.len() > (self.max_frame + MAX_HEADERS).saturating_sub(self.data.len()) {
            return Err("camera_buffer_limit");
        }
        self.data.extend_from_slice(part);
        Ok(())
    }
    pub fn frame(&mut self) -> Result<Option<Bytes>, &'static str> {
        if self.length.is_none() {
            let end = self.data.windows(4).position(|p| p == b"\r\n\r\n");
            let Some(end) = end else {
                return if self.data.len() > MAX_HEADERS {
                    Err("camera_headers_limit")
                } else {
                    Ok(None)
                };
            };
            if end > MAX_HEADERS {
                return Err("camera_headers_limit");
            }
            let headers =
                std::str::from_utf8(&self.data[..end]).map_err(|_| "camera_headers_invalid")?;
            let mut length = None;
            let mut jpeg = false;
            let mut online = true;
            for line in headers.split("\r\n") {
                let Some((name, value)) = line.split_once(':') else {
                    continue;
                };
                if name.eq_ignore_ascii_case("content-length") {
                    if length.is_some() {
                        return Err("camera_length_ambiguous");
                    }
                    length = Some(
                        value
                            .trim()
                            .parse::<usize>()
                            .map_err(|_| "camera_length_invalid")?,
                    );
                }
                if name.eq_ignore_ascii_case("content-type") {
                    jpeg = value.trim().eq_ignore_ascii_case("image/jpeg");
                }
                if name.eq_ignore_ascii_case("x-ustreamer-online") {
                    online = !matches!(value.trim(), "false" | "0");
                }
            }
            let length = length
                .filter(|n| (16..=self.max_frame).contains(n))
                .ok_or("camera_length_invalid")?;
            if !jpeg {
                return Err("camera_media_type");
            }
            self.data.advance(end + 4);
            self.length = Some(length);
            self.online = online;
        }
        let length = self.length.unwrap();
        if self.data.len() < length {
            return Ok(None);
        }
        let jpeg = self.data.split_to(length).freeze();
        self.length = None;
        // uStreamer may send an offline placeholder; it is never a valid user capture.
        if !self.online {
            return Err("camera_offline_placeholder");
        }
        dimensions(&jpeg)?;
        Ok(Some(jpeg))
    }
}

/// SOF inspection only; server still validates/decodes images before model execution.
pub fn dimensions(jpeg: &[u8]) -> Result<(u16, u16), &'static str> {
    // Real UVC MJPEG frames can contain USB/DMA zero padding after EOI (observed on rasp4gb).
    // Keep the original bytes/hash, but do not mistake this padding for a broken JPEG.
    let end = jpeg
        .iter()
        .rposition(|b| *b != 0 && *b != 0xff)
        .map_or(0, |at| at + 1);
    if !jpeg.starts_with(&[0xff, 0xd8])
        || !jpeg[..end].ends_with(&[0xff, 0xd9])
        || jpeg.len() - end > 65536
    {
        return Err("camera_jpeg_invalid");
    }
    let mut at = 2;
    while at + 1 < jpeg.len() {
        if jpeg[at] != 0xff {
            return Err("camera_jpeg_invalid");
        }
        while at < jpeg.len() && jpeg[at] == 0xff {
            at += 1;
        }
        let marker = *jpeg.get(at).ok_or("camera_jpeg_invalid")?;
        at += 1;
        if marker == 0xda || marker == 0xd9 {
            break;
        }
        if (0xd0..=0xd7).contains(&marker) || marker == 0x01 {
            continue;
        }
        if at + 2 > jpeg.len() {
            return Err("camera_jpeg_invalid");
        }
        let len = usize::from(u16::from_be_bytes([jpeg[at], jpeg[at + 1]]));
        if len < 2 || at + len > jpeg.len() {
            return Err("camera_jpeg_invalid");
        }
        if [0xc0, 0xc1, 0xc2].contains(&marker) {
            if len < 8 {
                return Err("camera_jpeg_invalid");
            }
            let h = u16::from_be_bytes([jpeg[at + 3], jpeg[at + 4]]);
            let w = u16::from_be_bytes([jpeg[at + 5], jpeg[at + 6]]);
            if w == 0 || h == 0 || u64::from(w) * u64::from(h) > 40_000_000 {
                return Err("camera_pixels_limit");
            }
            return Ok((w, h));
        }
        at += len;
    }
    Err("camera_dimensions_missing")
}

#[cfg(test)]
pub fn jpeg_fixture() -> Vec<u8> {
    // Deliberately embeds an EOI in APP metadata: frame splitting must use Content-Length.
    vec![
        0xff, 0xd8, 0xff, 0xe0, 0, 6, 0xff, 0xd9, 0, 0, 0xff, 0xc0, 0, 11, 8, 4, 56, 7, 128, 1, 1,
        0x11, 0, 0xff, 0xd9,
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    fn part(jpeg: &[u8]) -> Vec<u8> {
        let mut p = format!(
            "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n",
            jpeg.len()
        )
        .into_bytes();
        p.extend_from_slice(jpeg);
        p.extend_from_slice(b"\r\n");
        p
    }
    #[test]
    fn arbitrary_chunk_boundaries_preserve_original_jpeg_and_dimensions() {
        let jpeg = jpeg_fixture();
        let mut wire = part(&jpeg);
        wire.extend(part(&jpeg));
        for split in 1..wire.len() {
            let mut parser = MjpegParser::new(1024);
            let mut frames = Vec::new();
            for p in wire.chunks(split) {
                parser.push(p).unwrap();
                while let Some(frame) = parser.frame().unwrap() {
                    frames.push(frame);
                }
            }
            assert_eq!(frames.len(), 2);
            assert!(frames.iter().all(|f| f.as_ref() == jpeg));
            assert_eq!(dimensions(&frames[0]), Ok((1920, 1080)));
        }
    }
    #[test]
    fn reject_missing_or_ambiguous_length_before_accumulating_body() {
        for header in [
            "Content-Length: 99999999",
            "Content-Length: 20\r\nContent-Length: 20",
            "X-Length: 20",
        ] {
            let mut p = MjpegParser::new(1024);
            p.push(format!("--x\r\nContent-Type: image/jpeg\r\n{header}\r\n\r\n").as_bytes())
                .unwrap();
            assert!(p.frame().is_err());
        }
    }
    #[test]
    fn enforce_bounds_without_trusting_length_or_offline_placeholder() {
        let mut p = MjpegParser::new(64);
        assert!(p.push(&vec![0; MAX_HEADERS + 65]).is_err());
        let jpeg = jpeg_fixture();
        let mut p = MjpegParser::new(1024);
        p.push(format!("--x\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\nX-UStreamer-Online: false\r\n\r\n", jpeg.len()).as_bytes()).unwrap();
        p.push(&jpeg).unwrap();
        assert_eq!(p.frame(), Err("camera_offline_placeholder"));
    }
    #[test]
    fn native_uvc_padding_is_preserved_without_rejecting_every_real_frame() {
        let mut jpeg = jpeg_fixture();
        jpeg.extend([0; 3548]);
        let mut parser = MjpegParser::new(8192);
        parser.push(&part(&jpeg)).unwrap();
        let image = parser.frame().unwrap().unwrap();
        assert_eq!(image.as_ref(), jpeg);
        assert_eq!(dimensions(&image), Ok((1920, 1080)));
        let mut bad = jpeg_fixture();
        bad.extend(b"not camera padding");
        assert!(dimensions(&bad).is_err());
    }
}
