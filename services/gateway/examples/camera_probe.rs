//! SSH-only diagnostic: exercise the exact production capture broker, not an unauthenticated HTTP route.
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use vietocr_gateway::{camera::Camera, config::CameraConfig};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let origin = args.first().map_or("http://127.0.0.1:8080", String::as_str);
    let url = reqwest::Url::parse(origin)?;
    if url.scheme() != "http"
        || !matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
        || url.path() != "/"
        || url.query().is_some()
        || !url.username().is_empty()
    {
        return Err("probe accepts only the local trusted capture service".into());
    }
    let seconds = args
        .get(1)
        .map(|v| v.parse::<u64>())
        .transpose()?
        .unwrap_or(10)
        .clamp(1, 60);
    let camera = Camera::new(
        CameraConfig {
            id: "probe".into(),
            name: "Local UVC probe".into(),
            upstream: origin.into(),
        },
        4 * 1024 * 1024,
    );
    let mut frames = camera.subscribe();
    let producer = tokio::spawn(Arc::clone(&camera).run());
    let opened = Instant::now();
    let mut first = None;
    let mut last = 0;
    let mut count = 0u64;
    let mut bytes = 0u64;
    let mut width = 0;
    let mut height = 0;
    loop {
        tokio::time::timeout(Duration::from_secs(6), frames.changed()).await??;
        let state = frames.borrow().clone();
        if let Some(error) = state.error {
            return Err(format!("broker: {error}").into());
        }
        if let Some(frame) = state.frame.filter(|f| f.sequence != last) {
            first.get_or_insert_with(Instant::now);
            last = frame.sequence;
            count += 1;
            bytes += frame.jpeg.len() as u64;
            width = frame.width;
            height = frame.height;
        }
        if first.is_some_and(|t| t.elapsed() >= Duration::from_secs(seconds)) {
            break;
        }
    }
    let elapsed = first.unwrap().elapsed().as_secs_f64();
    println!(
        "{}",
        serde_json::json!({ "path": "native UVC -> uStreamer -> Rust broker", "width": width, "height": height,
        "frames": count, "seconds": elapsed, "fps": (count.saturating_sub(1)) as f64 / elapsed,
        "meanJpegBytes": bytes / count.max(1), "firstFrameMs": opened.elapsed().as_secs_f64() * 1000.0 - elapsed * 1000.0,
        "encodedAgain": false, "ocrRequests": 0 })
    );
    producer.abort();
    Ok(())
}
