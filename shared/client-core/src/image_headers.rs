//! Allocation-free header bounds before an image reaches the webview decoder.
//! This is an early resource check, not a substitute for compute's full verifier.
pub const MAX_PIXELS: u64 = 40_000_000;
pub fn inspect(bytes: &[u8]) -> Result<(&'static str, u32, u32), String> {
    let invalid = || "Ảnh lỗi hoặc định dạng chưa hỗ trợ".to_owned();
    let le32 = |at: usize| -> Result<u32, String> {
        Ok(u32::from_le_bytes(
            bytes
                .get(at..at + 4)
                .ok_or_else(invalid)?
                .try_into()
                .map_err(|_| invalid())?,
        ))
    };
    let (media, width, height) = if bytes.starts_with(&[255, 216]) {
        let (w, h) = vietocr_contracts::mjpeg::dimensions(bytes).map_err(|_| invalid())?;
        ("image/jpeg", u32::from(w), u32::from(h))
    } else if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        if bytes.len() < 33 || bytes.get(8..16) != Some(b"\0\0\0\rIHDR") {
            return Err(invalid());
        }
        let width = u32::from_be_bytes(bytes[16..20].try_into().map_err(|_| invalid())?);
        let height = u32::from_be_bytes(bytes[20..24].try_into().map_err(|_| invalid())?);
        ("image/png", width, height)
    } else if bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP") {
        if u64::from(le32(4)?) + 8 > bytes.len() as u64 {
            return Err(invalid());
        }
        match bytes.get(12..16) {
            Some(b"VP8X") if bytes.len() >= 30 => {
                let width = 1 + u32::from_le_bytes([bytes[24], bytes[25], bytes[26], 0]);
                let height = 1 + u32::from_le_bytes([bytes[27], bytes[28], bytes[29], 0]);
                ("image/webp", width, height)
            }
            Some(b"VP8L") if bytes.len() >= 25 && bytes[20] == 0x2f => {
                let bits = le32(21)?;
                (
                    "image/webp",
                    1 + (bits & 0x3fff),
                    1 + ((bits >> 14) & 0x3fff),
                )
            }
            Some(b"VP8 ")
                if bytes.len() >= 30 && bytes.get(23..26) == Some(&[0x9d, 0x01, 0x2a]) =>
            {
                let width = u32::from(u16::from_le_bytes([bytes[26], bytes[27]]) & 0x3fff);
                let height = u32::from(u16::from_le_bytes([bytes[28], bytes[29]]) & 0x3fff);
                ("image/webp", width, height)
            }
            _ => return Err(invalid()),
        }
    } else {
        return Err(invalid());
    };
    if width < 2 || height < 2 || u64::from(width) * u64::from(height) > MAX_PIXELS {
        return Err(
            "Ảnh vượt 40 megapixel hoặc kích thước không hợp lệ. Hãy chọn vùng nhỏ hơn.".into(),
        );
    }
    Ok((media, width, height))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reads_native_jpeg_and_rejects_a_small_file_with_an_oversized_png_header() {
        assert_eq!(
            inspect(include_bytes!("../../contracts/fixtures/images/test.jpg"))
                .unwrap()
                .0,
            "image/jpeg"
        );
        let mut png = vec![0; 33];
        png[..16].copy_from_slice(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR");
        png[16..20].copy_from_slice(&100_000u32.to_be_bytes());
        png[20..24].copy_from_slice(&100_000u32.to_be_bytes());
        assert!(inspect(&png).is_err());
        for size in 0..png.len() {
            assert!(inspect(&png[..size]).is_err());
        }
    }
}
