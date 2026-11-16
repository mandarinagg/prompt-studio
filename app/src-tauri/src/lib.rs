mod engine;

use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use engine::Engine;
use serde_json::{Value, json};
use tauri::{Manager, path::BaseDirectory};

const CALL_TIMEOUT: Duration = Duration::from_secs(30);

/// Instante de arranque del proceso (para medir el spike #3).
static PROCESS_START: OnceLock<Instant> = OnceLock::new();

#[derive(Default)]
struct Metrics {
    engine_spawn_ms: Option<f64>,
    engine_ready_ms: Option<f64>,
    ui_ready_ms: Option<f64>,
}

struct AppState {
    engine: Mutex<Option<Arc<Engine>>>,
    metrics: Mutex<Metrics>,
}

fn elapsed_ms() -> f64 {
    PROCESS_START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}

fn engine_of(state: &AppState) -> Result<Arc<Engine>, String> {
    state
        .engine
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "engine no iniciado".to_string())
}

#[tauri::command]
async fn engine_call(
    state: tauri::State<'_, AppState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let engine = engine_of(&state)?;
    tauri::async_runtime::spawn_blocking(move || {
        engine.call(&method, params.unwrap_or_else(|| json!({})), CALL_TIMEOUT)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// La UI lo llama al montarse; devuelve las métricas de arranque.
#[tauri::command]
fn startup_metrics(app: tauri::AppHandle, state: tauri::State<'_, AppState>) -> Value {
    let mut m = state.metrics.lock().unwrap();
    m.ui_ready_ms.get_or_insert_with(elapsed_ms);
    let report = json!({
        "engine_spawn_ms": m.engine_spawn_ms,
        "engine_ready_ms": m.engine_ready_ms,
        "ui_ready_ms": m.ui_ready_ms,
    });
    maybe_finish_spike(&app, &m, &report);
    report
}

/// Modo de medición: con PSTUDIO_SPIKE_METRICS=<archivo>, al tener UI y engine listos se
/// escriben las métricas y la app se cierra sola.
fn maybe_finish_spike(app: &tauri::AppHandle, m: &Metrics, report: &Value) {
    let Ok(path) = std::env::var("PSTUDIO_SPIKE_METRICS") else {
        return;
    };
    if m.ui_ready_ms.is_some() && m.engine_ready_ms.is_some() {
        let _ = std::fs::write(path, report.to_string());
        app.exit(0);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    PROCESS_START.get_or_init(Instant::now);
    tauri::Builder::default()
        .manage(AppState {
            engine: Mutex::new(None),
            metrics: Mutex::new(Metrics::default()),
        })
        .setup(|app| {
            let python = app
                .path()
                .resolve("engine/python/python.exe", BaseDirectory::Resource)?;
            let engine = Arc::new(Engine::spawn(&python)?);
            let state = app.state::<AppState>();
            state.metrics.lock().unwrap().engine_spawn_ms = Some(elapsed_ms());
            *state.engine.lock().unwrap() = Some(Arc::clone(&engine));

            // Ping inicial en segundo plano: mide cuándo el engine está listo.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ok = engine.call("ping", json!({}), CALL_TIMEOUT).is_ok();
                let state = handle.state::<AppState>();
                let mut m = state.metrics.lock().unwrap();
                if ok {
                    m.engine_ready_ms = Some(elapsed_ms());
                } else {
                    eprintln!("[engine] no respondió al ping inicial");
                }
                let report = json!({
                    "engine_spawn_ms": m.engine_spawn_ms,
                    "engine_ready_ms": m.engine_ready_ms,
                    "ui_ready_ms": m.ui_ready_ms,
                });
                maybe_finish_spike(&handle, &m, &report);
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_call, startup_metrics])
        .build(tauri::generate_context!())
        .expect("error al construir la app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event
                && let Some(engine) = app.state::<AppState>().engine.lock().unwrap().take()
            {
                engine.shutdown();
            }
        });
}
