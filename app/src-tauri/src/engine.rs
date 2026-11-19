//! Cliente JSON-RPC 2.0 del engine Python (sidecar por stdio, sin red).
//!
//! El engine se lanza como `python.exe -I -m pstudio rpc` usando el runtime embebido que viaja en
//! los recursos del bundle (`engine/python/python.exe`, firmado por la PSF). Cada línea de stdout
//! es una respuesta (con `id`, se empareja con su petición) o una notificación del engine (sin
//! `id`, se entrega a `on_event`). Cerrar stdin apaga el engine. Si el proceso termina sin que lo
//! pidamos, las llamadas en curso fallan enseguida y se llama a `on_exit` (para relanzarlo).

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use serde_json::{Value, json};

type Pending = Arc<Mutex<HashMap<u64, Sender<Value>>>>;
pub type OnEvent = Arc<dyn Fn(Value) + Send + Sync>;
pub type OnExit = Box<dyn FnOnce() + Send>;

pub const RESTARTED: &str = "el motor se reinició: repetí la acción";

/// Error de una llamada, con el código JSON-RPC cuando lo dio el engine.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct EngineError {
    pub message: String,
    pub code: Option<i64>,
}

impl EngineError {
    fn local(message: impl Into<String>) -> Self {
        Self { message: message.into(), code: None }
    }
}

/// Cómo lanzar el engine (en tests, un script de Python que lo imita).
#[derive(Debug, Clone)]
pub struct EngineCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}

impl EngineCommand {
    pub fn python(python: PathBuf) -> Self {
        // -I: ignora PYTHONPATH y el site del usuario del sistema.
        let args = ["-I", "-m", "pstudio", "rpc"].map(OsString::from).to_vec();
        Self { program: python, args }
    }
}

pub struct Engine {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
    stopping: Arc<AtomicBool>,
}

impl Engine {
    pub fn spawn(command: &EngineCommand, on_event: OnEvent, on_exit: OnExit) -> std::io::Result<Self> {
        let mut cmd = Command::new(&command.program);
        cmd.args(&command.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd.spawn()?;
        let stdin = child.stdin.take();
        let stdout = child.stdout.take().expect("stdout con pipe");
        let pending: Pending = Arc::default();
        let stopping = Arc::new(AtomicBool::new(false));

        let reader_pending = Arc::clone(&pending);
        let reader_stopping = Arc::clone(&stopping);
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let Ok(msg) = serde_json::from_str::<Value>(&line) else {
                    eprintln!("[engine] línea no JSON en stdout: {line}");
                    continue;
                };
                match msg.get("id").and_then(Value::as_u64) {
                    Some(id) => {
                        if let Some(tx) = reader_pending.lock().unwrap().remove(&id) {
                            let _ = tx.send(msg);
                        }
                    }
                    None if msg.get("method").is_some() => on_event(msg),
                    None => eprintln!("[engine] respuesta sin id: {line}"),
                }
            }
            // EOF: el engine terminó. Quien siga esperando recibe el error ya, no tras el timeout.
            for (_, tx) in reader_pending.lock().unwrap().drain() {
                let _ = tx.send(json!({"error": {"message": RESTARTED}}));
            }
            if !reader_stopping.load(Ordering::SeqCst) {
                on_exit();
            }
        });

        Ok(Self {
            child: Mutex::new(Some(child)),
            stdin: Mutex::new(stdin),
            pending,
            next_id: AtomicU64::new(1),
            stopping,
        })
    }

    /// Llamada bloqueante; usar desde un hilo de trabajo, nunca desde el hilo de UI.
    pub fn call(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, EngineError> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = mpsc::channel();
        self.pending.lock().unwrap().insert(id, tx);
        let req = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        {
            let mut guard = self.stdin.lock().unwrap();
            let Some(stdin) = guard.as_mut() else {
                self.pending.lock().unwrap().remove(&id);
                return Err(EngineError::local("engine detenido"));
            };
            if let Err(e) = writeln!(stdin, "{req}").and_then(|_| stdin.flush()) {
                self.pending.lock().unwrap().remove(&id);
                return Err(EngineError::local(format!("no se pudo escribir al engine: {e}")));
            }
        }
        let msg = rx.recv_timeout(timeout).map_err(|_| {
            self.pending.lock().unwrap().remove(&id);
            EngineError::local(format!("sin respuesta del engine a '{method}'"))
        })?;
        match (msg.get("result"), msg.get("error")) {
            (Some(result), _) => Ok(result.clone()),
            (_, Some(err)) => Err(EngineError {
                message: err["message"].as_str().unwrap_or("error del engine").to_string(),
                code: err["code"].as_i64(),
            }),
            _ => Err(EngineError::local("respuesta inválida del engine")),
        }
    }

    /// Apagado ordenado: cerrar stdin (el engine sale en EOF); si no sale, matarlo.
    pub fn shutdown(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        self.stdin.lock().unwrap().take();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            for _ in 0..20 {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    return;
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::channel;

    /// Python para los engines falsos: `PSTUDIO_TEST_PYTHON` o `python` del PATH.
    fn fake(script: &str) -> Option<EngineCommand> {
        let python = std::env::var_os("PSTUDIO_TEST_PYTHON").unwrap_or_else(|| "python".into());
        let ok = Command::new(&python).arg("--version").output().is_ok_and(|o| o.status.success());
        if !ok {
            eprintln!("sin Python: se saltea el test");
            return None;
        }
        let args = vec!["-u".into(), "-c".into(), script.into()];
        Some(EngineCommand { program: python.into(), args })
    }

    // Lee una petición, emite una notificación, responde y termina (como si se cayera).
    const NOTIFY_AND_DIE: &str = r#"
import json, sys
req = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "method": "thumbnail.ready", "params": {"asset": "a"}}))
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": "pong"}))
"#;

    #[test]
    fn forwards_events_and_reports_exit() {
        let Some(cmd) = fake(NOTIFY_AND_DIE) else { return };
        let (ev_tx, ev_rx) = channel();
        let ev_tx = Mutex::new(ev_tx);
        let (exit_tx, exit_rx) = channel();
        let engine = Engine::spawn(
            &cmd,
            Arc::new(move |msg| ev_tx.lock().unwrap().send(msg).unwrap()),
            Box::new(move || exit_tx.send(()).unwrap()),
        )
        .unwrap();
        let r = engine.call("ping", json!({}), Duration::from_secs(20)).unwrap();
        assert_eq!(r, json!("pong"));
        let ev = ev_rx.recv_timeout(Duration::from_secs(20)).unwrap();
        assert_eq!(ev["method"], "thumbnail.ready");
        assert_eq!(ev["params"]["asset"], "a");
        exit_rx.recv_timeout(Duration::from_secs(20)).expect("on_exit al morir el engine");
    }

    #[test]
    fn pending_call_fails_fast_when_engine_dies() {
        let Some(cmd) = fake("import sys; sys.stdin.readline()") else { return };
        let engine = Engine::spawn(&cmd, Arc::new(|_| {}), Box::new(|| {})).unwrap();
        let start = std::time::Instant::now();
        let err = engine.call("ping", json!({}), Duration::from_secs(30)).unwrap_err();
        assert_eq!(err.message, RESTARTED);
        assert!(start.elapsed() < Duration::from_secs(15), "no debe esperar al timeout");
    }

    #[test]
    fn engine_errors_keep_their_code() {
        let script = r#"
import json, sys
req = json.loads(sys.stdin.readline())
err = {"code": -32001, "message": "no hay un proyecto abierto"}
print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": err}))
sys.stdin.readline()
"#;
        let Some(cmd) = fake(script) else { return };
        let engine = Engine::spawn(&cmd, Arc::new(|_| {}), Box::new(|| {})).unwrap();
        let err = engine.call("asset.state", json!({}), Duration::from_secs(20)).unwrap_err();
        assert_eq!(err, EngineError { message: "no hay un proyecto abierto".into(), code: Some(-32001) });
    }

    #[test]
    fn shutdown_does_not_call_on_exit() {
        let Some(cmd) = fake("import sys; sys.stdin.read()") else { return };
        let (exit_tx, exit_rx) = channel();
        let engine = Engine::spawn(&cmd, Arc::new(|_| {}), Box::new(move || exit_tx.send(()).unwrap())).unwrap();
        engine.shutdown();
        assert!(exit_rx.recv_timeout(Duration::from_secs(2)).is_err());
    }
}
