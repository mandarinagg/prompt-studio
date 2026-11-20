mod engine;

use std::path::{Path, PathBuf};
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
    cache_dir: Mutex<Option<PathBuf>>,
    /// Motivo por el que el motor quedó caído del todo (la UI lo consulta al arrancar, por si
    /// el evento `engine-failed` salió antes de que escuchara).
    failure: Mutex<Option<String>>,
    metrics: Mutex<Metrics>,
}

fn elapsed_ms() -> f64 {
    PROCESS_START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}

fn engine_of(state: &AppState) -> Result<Arc<Engine>, EngineError> {
    state
        .engine
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| local_error("el motor no está disponible"))
}

// ------------------------------------------------------------------------- engine supervisado
/// Lanza el engine. Sus notificaciones salen como evento `engine-event {method, params}`; si
/// muere solo, se relanza (como mucho `MAX_RESTARTS` veces por minuto).
fn start_engine(app: &AppHandle) -> std::io::Result<Arc<Engine>> {
    let state = app.state::<AppState>();
    let command = state
        .command
        .lock()
        .unwrap()
        .clone()
        .expect("comando del engine");
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
        *state.failure.lock().unwrap() = Some(message.clone());
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
    let python = app
        .path()
        .resolve("engine/python/python.exe", BaseDirectory::Resource)?;
    Ok(EngineCommand::python(python))
}

// ------------------------------------------------------------------------- comandos
#[tauri::command]
async fn engine_call(
    state: tauri::State<'_, AppState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, EngineError> {
    let engine = engine_of(&state)?;
    let opens_project = matches!(method.as_str(), "project.open" | "project.create");
    if opens_project || method == "project.close" {
        // Hasta saber cuál queda abierto, `read_cache` no sirve la caché de ninguno.
        *state.cache_dir.lock().unwrap() = None;
    }
    let result = tauri::async_runtime::spawn_blocking(move || {
        engine.call(&method, params.unwrap_or_else(|| json!({})), CALL_TIMEOUT)
    })
    .await
    .map_err(|e| EngineError {
        message: e.to_string(),
        code: None,
    })??;
    if opens_project && let Some(dir) = result.get("cache_dir").and_then(Value::as_str) {
        // `read_cache` solo sirve archivos de esta carpeta (previews, miniaturas).
        *state.cache_dir.lock().unwrap() = Some(PathBuf::from(dir));
    }
    Ok(result)
}

fn local_error(message: impl Into<String>) -> EngineError {
    EngineError {
        message: message.into(),
        code: None,
    }
}

/// El archivo pedido, solo si está dentro de la caché del proyecto abierto. Se resuelven `..`
/// y enlaces antes de comparar: la UI nunca puede leer un original ni otra carpeta.
fn resolve_cache_file(cache_dir: Option<&Path>, path: &Path) -> Result<PathBuf, EngineError> {
    let cache_dir = cache_dir.ok_or_else(|| local_error("no hay un proyecto abierto"))?;
    let cache_dir = std::fs::canonicalize(cache_dir)
        .map_err(|_| local_error("la caché del proyecto no existe"))?;
    let file = std::fs::canonicalize(path)
        .map_err(|_| local_error("el archivo de la caché ya no existe"))?;
    if !file.starts_with(&cache_dir) || !file.is_file() {
        return Err(local_error(
            "solo se pueden leer archivos de la caché del proyecto",
        ));
    }
    Ok(file)
}

/// Preview o miniatura como bytes por IPC binario; la UI la muestra con un blob URL (ADR-0010:
/// mismo rendimiento que el protocolo de assets, sin abrir un protocolo de archivos).
#[tauri::command]
async fn read_cache(
    state: tauri::State<'_, AppState>,
    path: String,
) -> Result<tauri::ipc::Response, EngineError> {
    let cache_dir = state.cache_dir.lock().unwrap().clone();
    let file = resolve_cache_file(cache_dir.as_deref(), Path::new(&path))?;
    tauri::async_runtime::spawn_blocking(move || std::fs::read(file))
        .await
        .map_err(|e| local_error(e.to_string()))?
        .map(tauri::ipc::Response::new)
        .map_err(|e| local_error(format!("no se pudo leer la caché: {e}")))
}

#[tauri::command]
fn engine_failure(state: tauri::State<'_, AppState>) -> Option<String> {
    state.failure.lock().unwrap().clone()
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
    let dir = std::env::var("PSTUDIO_BENCH_DIR")
        .unwrap_or_else(|_| std::env::temp_dir().display().to_string());
    let restart = std::env::var_os("PSTUDIO_BENCH_RESTART").is_some();
    Some(json!({"photo": photo, "out": out, "dir": dir, "restart": restart}))
}

#[tauri::command]
fn bench_report(app: AppHandle, report: Value) -> Result<(), String> {
    let out =
        std::env::var("PSTUDIO_BENCH_OUT").map_err(|_| "sin PSTUDIO_BENCH_OUT".to_string())?;
    std::fs::write(out, serde_json::to_string_pretty(&report).unwrap())
        .map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    PROCESS_START.get_or_init(Instant::now);
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            engine: Mutex::new(None),
            command: Mutex::new(None),
            restarts: Mutex::new(Vec::new()),
            cache_dir: Mutex::new(None),
            failure: Mutex::new(None),
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
        .invoke_handler(tauri::generate_handler![
            engine_call,
            engine_failure,
            startup_metrics,
            read_cache,
            bench_config,
            bench_report
        ])
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

#[cfg(test)]
mod tests {
    use super::*;

    fn tree() -> (PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!("pstudio-cache-test-{}", std::process::id()));
        let cache = root.join("P.pstudio").join("cache");
        std::fs::create_dir_all(cache.join("preview")).unwrap();
        std::fs::write(cache.join("preview").join("a-1.jpg"), b"x").unwrap();
        std::fs::write(root.join("original.jpg"), b"y").unwrap();
        (root, cache)
    }

    #[test]
    fn cache_file_must_be_inside_the_open_project_cache() {
        let (root, cache) = tree();
        let ok = resolve_cache_file(Some(&cache), &cache.join("preview").join("a-1.jpg"));
        assert!(ok.is_ok(), "{ok:?}");
        let escape = cache
            .join("preview")
            .join("..")
            .join("..")
            .join("..")
            .join("original.jpg");
        assert!(resolve_cache_file(Some(&cache), &escape).is_err());
        assert!(resolve_cache_file(Some(&cache), &root.join("original.jpg")).is_err());
        assert!(resolve_cache_file(None, &cache.join("preview").join("a-1.jpg")).is_err());
        assert!(resolve_cache_file(Some(&cache), &cache.join("nada.jpg")).is_err());
        let _ = std::fs::remove_dir_all(root);
    }
}
