mod engine;

use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use engine::{Engine, EngineCommand, EngineError, OnEvent, OnExit};
use serde_json::{Value, json};
use tauri::{AppHandle, Emitter, Manager, path::BaseDirectory};

const CALL_TIMEOUT: Duration = Duration::from_secs(120); // plan con LLM local, import grande
const MAX_RESTARTS: usize = 3;
const RESTART_WINDOW: Duration = Duration::from_secs(60);

/// Instante de arranque del proceso (presupuesto de arranque, diseño M3 §8).
static PROCESS_START: OnceLock<Instant> = OnceLock::new();

#[derive(Default)]
struct Metrics {
    engine_spawn_ms: Option<f64>,
    engine_ready_ms: Option<f64>,
    ui_ready_ms: Option<f64>,
}

struct AppState {
    engine: Mutex<Option<Arc<Engine>>>,
    command: Mutex<Option<EngineCommand>>,
    restarts: Mutex<Vec<Instant>>,
    metrics: Mutex<Metrics>,
}

fn elapsed_ms() -> f64 {
    PROCESS_START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}

fn engine_of(state: &AppState) -> Result<Arc<Engine>, EngineError> {
    state.engine.lock().unwrap().clone().ok_or_else(|| EngineError {
        message: "el motor no está disponible".into(),
        code: None,
    })
}

// ------------------------------------------------------------------------- engine supervisado
/// Lanza el engine. Sus notificaciones salen como evento `engine-event {method, params}`; si
/// muere solo, se relanza (como mucho `MAX_RESTARTS` veces por minuto).
fn start_engine(app: &AppHandle) -> std::io::Result<Arc<Engine>> {
    let state = app.state::<AppState>();
    let command = state.command.lock().unwrap().clone().expect("comando del engine");
    let events = app.clone();
    let on_event: OnEvent = Arc::new(move |msg: Value| {
        let payload = json!({"method": msg["method"], "params": msg.get("params").cloned().unwrap_or(json!({}))});
        let _ = events.emit("engine-event", payload);
    });
    let exits = app.clone();
    let on_exit: OnExit = Box::new(move || restart_engine(&exits));
    let engine = Arc::new(Engine::spawn(&command, on_event, on_exit)?);
    *state.engine.lock().unwrap() = Some(Arc::clone(&engine));
    Ok(engine)
}

fn restart_engine(app: &AppHandle) {
    let state = app.state::<AppState>();
    let attempt = {
        let mut times = state.restarts.lock().unwrap();
        let now = Instant::now();
        times.retain(|t| now.duration_since(*t) < RESTART_WINDOW);
        (times.len() < MAX_RESTARTS).then(|| {
            times.push(now);
            times.len()
        })
    };
    eprintln!("[engine] terminó inesperadamente; relanzamiento: {attempt:?}");
    let failed = |message: String| {
        *state.engine.lock().unwrap() = None;
        let _ = app.emit("engine-failed", json!({ "message": message }));
    };
    match attempt {
        None => failed("el motor se cerró varias veces seguidas: reiniciá la app".into()),
        Some(n) => match start_engine(app) {
            Ok(_) => {
                let _ = app.emit("engine-restarted", json!({ "attempt": n }));
            }
            Err(e) => failed(format!("no se pudo relanzar el motor: {e}")),
        },
    }
}

fn engine_command(app: &AppHandle) -> tauri::Result<EngineCommand> {
    // En desarrollo se puede usar el Python del venv del engine (código al día, sin rearmar el
    // bundle embebido): PSTUDIO_ENGINE_PYTHON=engine/.venv/Scripts/python.exe
    #[cfg(debug_assertions)]
    if let Some(python) = std::env::var_os("PSTUDIO_ENGINE_PYTHON") {
        return Ok(EngineCommand::python(PathBuf::from(python)));
    }
    let python = app.path().resolve("engine/python/python.exe", BaseDirectory::Resource)?;
    Ok(EngineCommand::python(python))
}

// ------------------------------------------------------------------------- comandos
#[tauri::command]
async fn engine_call(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, EngineError> {
    let engine = engine_of(&state)?;
    let opens_project = matches!(method.as_str(), "project.open" | "project.create");
    let result = tauri::async_runtime::spawn_blocking(move || {
        engine.call(&method, params.unwrap_or_else(|| json!({})), CALL_TIMEOUT)
    })
    .await
    .map_err(|e| EngineError { message: e.to_string(), code: None })??;
    if opens_project && let Some(dir) = result.get("cache_dir").and_then(Value::as_str) {
        // El protocolo de assets solo sirve la caché del proyecto abierto (previews, miniaturas),
        // nunca los originales ni otras carpetas.
        app.asset_protocol_scope()
            .allow_directory(dir, true)
            .map_err(|e| EngineError { message: format!("no se pudo habilitar la caché: {e}"), code: None })?;
    }
    Ok(result)
}

/// La UI lo llama al montarse; devuelve las métricas de arranque.
#[tauri::command]
fn startup_metrics(app: AppHandle, state: tauri::State<'_, AppState>) -> Value {
    let mut m = state.metrics.lock().unwrap();
    m.ui_ready_ms.get_or_insert_with(elapsed_ms);
    let report = metrics_json(&m);
    maybe_finish_spike(&app, &m, &report);
    report
}

fn metrics_json(m: &Metrics) -> Value {
    json!({
        "engine_spawn_ms": m.engine_spawn_ms,
        "engine_ready_ms": m.engine_ready_ms,
        "ui_ready_ms": m.ui_ready_ms,
    })
}

/// Modo de medición de arranque: con PSTUDIO_SPIKE_METRICS=<archivo>, al tener UI y engine
/// listos se escriben las métricas y la app se cierra sola.
fn maybe_finish_spike(app: &AppHandle, m: &Metrics, report: &Value) {
    let Ok(path) = std::env::var("PSTUDIO_SPIKE_METRICS") else {
        return;
    };
    if m.ui_ready_ms.is_some() && m.engine_ready_ms.is_some() {
        let _ = std::fs::write(path, report.to_string());
        app.exit(0);
    }
}

/// Banco de transporte de la preview (ADR-0010): con PSTUDIO_BENCH_PHOTO=<foto> y
/// PSTUDIO_BENCH_OUT=<json>, la UI mide y llama a `bench_report`, que guarda y cierra la app.
#[tauri::command]
fn bench_config() -> Option<Value> {
    let photo = std::env::var("PSTUDIO_BENCH_PHOTO").ok()?;
    let out = std::env::var("PSTUDIO_BENCH_OUT").ok()?;
    let dir = std::env::var("PSTUDIO_BENCH_DIR").unwrap_or_else(|_| std::env::temp_dir().display().to_string());
    Some(json!({"photo": photo, "out": out, "dir": dir}))
}

#[tauri::command]
fn bench_report(app: AppHandle, report: Value) -> Result<(), String> {
    let out = std::env::var("PSTUDIO_BENCH_OUT").map_err(|_| "sin PSTUDIO_BENCH_OUT".to_string())?;
    std::fs::write(out, serde_json::to_string_pretty(&report).unwrap()).map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    PROCESS_START.get_or_init(Instant::now);
    tauri::Builder::default()
        .manage(AppState {
            engine: Mutex::new(None),
            command: Mutex::new(None),
            restarts: Mutex::new(Vec::new()),
            metrics: Mutex::new(Metrics::default()),
        })
        .setup(|app| {
            let state = app.state::<AppState>();
            *state.command.lock().unwrap() = Some(engine_command(app.handle())?);
            let engine = start_engine(app.handle())?;
            state.metrics.lock().unwrap().engine_spawn_ms = Some(elapsed_ms());

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
                let report = metrics_json(&m);
                maybe_finish_spike(&handle, &m, &report);
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_call, startup_metrics, bench_config, bench_report])
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
