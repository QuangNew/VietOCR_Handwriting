//! Optional, one-pass transfer derivative. Original remains unchanged. No resize,
//! no sharpening and no OCR/preprocessing change. Default client profile is original.
use image::{
    DynamicImage, ImageDecoder, ImageEncoder, ImageReader,
    codecs::{
        jpeg::JpegEncoder,
        png::{CompressionType, FilterType, PngEncoder},
    },
};
use std::io::Cursor;

pub struct Optimized {
    pub bytes: Vec<u8>,
    pub media: &'static str,
    pub lossless: bool,
}
pub fn optimize(bytes: &[u8]) -> Result<Option<Optimized>, String> {
    crate::image_headers::inspect(bytes)?;
    let mut reader = ImageReader::new(Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|_| "Định dạng ảnh lỗi")?;
    let mut limits = image::Limits::default();
    limits.max_alloc = Some(256 * 1024 * 1024);
    reader.limits(limits);
    let mut decoder = reader
        .into_decoder()
        .map_err(|_| "Không giải mã được ảnh")?;
    // Avoid silently changing a non-sRGB photograph's colours. Keep that original.
    if decoder
        .icc_profile()
        .map_err(|_| "ICC profile lỗi")?
        .is_some()
    {
        return Ok(None);
    }
    let orientation = decoder.orientation().map_err(|_| "EXIF orientation lỗi")?;
    let mut decoded = DynamicImage::from_decoder(decoder).map_err(|_| "Không giải mã được ảnh")?;
    decoded.apply_orientation(orientation);
    if decoded.has_alpha() {
        let mut rgba = decoded.into_rgba8();
        for pixel in rgba.pixels_mut() {
            let alpha = u16::from(pixel[3]);
            for channel in &mut pixel.0[..3] {
                *channel = ((u16::from(*channel) * alpha + 255 * (255 - alpha) + 127) / 255) as u8;
            }
            pixel[3] = 255;
        }
        decoded = DynamicImage::ImageRgba8(rgba);
    }
    let rgb = decoded.into_rgb8();
    let (width, height) = rgb.dimensions();
    let mut png = Vec::new();
    PngEncoder::new_with_quality(&mut png, CompressionType::Default, FilterType::Adaptive)
        .write_image(rgb.as_raw(), width, height, image::ExtendedColorType::Rgb8)
        .map_err(|_| "Không mã hoá PNG")?;
    let mut jpeg = Vec::new();
    JpegEncoder::new_with_quality(&mut jpeg, 95)
        .encode(rgb.as_raw(), width, height, image::ExtendedColorType::Rgb8)
        .map_err(|_| "Không mã hoá JPEG")?;
    let candidate = if png.len() <= jpeg.len() {
        Optimized {
            bytes: png,
            media: "image/png",
            lossless: true,
        }
    } else {
        Optimized {
            bytes: jpeg,
            media: "image/jpeg",
            lossless: false,
        }
    };
    if candidate.bytes.len() + 1024 >= bytes.len() {
        return Ok(None);
    }
    Ok(Some(candidate))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn transfer_never_resizes_and_preserves_the_source() {
        let image = image::RgbImage::from_fn(512, 256, |x, y| {
            image::Rgb([if y % 30 < 5 { 30 } else { 250 }, (x % 255) as u8, 150])
        });
        let mut source = Cursor::new(Vec::new());
        DynamicImage::ImageRgb8(image)
            .write_to(&mut source, image::ImageFormat::Png)
            .unwrap();
        let bytes = source.into_inner();
        let original = bytes.clone();
        if let Some(candidate) = optimize(&bytes).unwrap() {
            assert!(candidate.bytes.len() < bytes.len());
            assert_eq!(
                image::load_from_memory(&candidate.bytes).unwrap().width(),
                512
            );
            assert_eq!(
                image::load_from_memory(&candidate.bytes).unwrap().height(),
                256
            );
        }
        assert_eq!(bytes, original);
    }
}
