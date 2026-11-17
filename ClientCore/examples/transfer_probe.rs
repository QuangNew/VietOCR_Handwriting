//! Local-only optimisation measurements; never uploads images or prints OCR text.
use serde_json::json;
use std::{path::PathBuf, time::Instant};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = PathBuf::from(std::env::args().nth(1).ok_or("output directory required")?);
    std::fs::create_dir_all(&output)?;
    let mut rows = Vec::new();
    for input in std::env::args().skip(2).map(PathBuf::from) {
        let bytes = std::fs::read(&input)?;
        let (_, width, height) = vietocr_client_core::image_headers::inspect(&bytes)?;
        let began = Instant::now();
        let optimized = vietocr_client_core::image_transfer::optimize(&bytes)?;
        let elapsed = began.elapsed().as_secs_f64() * 1000.0;
        let result = if let Some(candidate) = optimized {
            let source = image::load_from_memory(&bytes)?.into_rgb8();
            let decoded = image::load_from_memory(&candidate.bytes)?.into_rgb8();
            let mse = source
                .as_raw()
                .iter()
                .zip(decoded.as_raw())
                .map(|(a, b)| {
                    let d = f64::from(*a) - f64::from(*b);
                    d * d
                })
                .sum::<f64>()
                / source.as_raw().len() as f64;
            let psnr = if mse > 0.0 {
                Some(10.0 * (255.0_f64 * 255.0 / mse).log10())
            } else {
                None
            };
            let name = format!(
                "{}.{}",
                input.file_name().unwrap().to_string_lossy(),
                if candidate.media == "image/png" {
                    "png"
                } else {
                    "jpg"
                }
            );
            std::fs::write(output.join(&name), &candidate.bytes)?;
            json!({"candidate":name,"bytes":candidate.bytes.len(),"lossless":candidate.lossless,"psnrDb":psnr,"sameDecodedDimensions":source.dimensions()==decoded.dimensions()})
        } else {
            json!({"keptOriginal":true,"bytes":bytes.len()})
        };
        rows.push(json!({"file":input.file_name().unwrap().to_string_lossy(),"originalBytes":bytes.len(),"width":width,"height":height,"encodeMs":elapsed,"result":result}));
    }
    println!("{}", serde_json::to_string_pretty(&rows)?);
    Ok(())
}
