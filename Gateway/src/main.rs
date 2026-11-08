use std::path::Path;
use tokio::sync::watch;
use vietocr_gateway::{
    App,
    config::Config,
    panel, router,
    telemetry::{self, PanelUpdate},
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "vietocr_gateway=info".into()),
        )
        .init();
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let path = args
        .first()
        .map_or("Gateway/config.local.json", String::as_str);
    let config = Config::load(Path::new(path)).map_err(std::io::Error::other)?;
    if args.iter().any(|s| s == "--check-config") {
        println!("Gateway configuration valid; no devices opened, no requests sent.");
        return Ok(());
    }
    let (tx, rx) = watch::channel(PanelUpdate::default());
    let app = App::new(&config, rx.clone())?;
    let _panel = panel::spawn(config.panel.clone(), rx);
    tokio::spawn(telemetry::monitor(config.telemetry.clone(), tx));
    app.start_capture();
    let listener = tokio::net::TcpListener::bind(config.listen).await?;
    tracing::info!(address = %config.listen, "Gateway v2 camera/status foundation listening; OCR v2 admission is not activated yet");
    axum::serve(listener, router(app))
        .with_graceful_shutdown(shutdown())
        .await?;
    Ok(())
}
async fn shutdown() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("install SIGTERM handler");
        tokio::select! { _ = tokio::signal::ctrl_c() => (), _ = terminate.recv() => () }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}
