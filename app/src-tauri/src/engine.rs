//! Cliente JSON-RPC 2.0 del engine Python (sidecar por stdio, sin red).
//!
//! El engine se lanza como `python.exe -m pstudio rpc` usando el runtime embebido que viaja en
//! los recursos del bundle (`engine/python/python.exe`, firmado por la PSF). Cada línea de stdout
//! es una respuesta; se empareja con su petición por `id`. Cerrar stdin apaga el engine.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{Value, json};

type Pending = Arc<Mutex<HashMap<u64, Sender<Value>>>>;

pub struct Engine {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: Pending,
    next_id: AtomicU64,
}

impl Engine {
    pub fn spawn(python: &Path) -> std::io::Result<Self> {
        let mut cmd = Command::new(python);
        cmd.args(["-I", "-m", "pstudio", "rpc"]) // -I: ignora PYTHONPATH/usuario del sistema
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

        let reader_pending = Arc::clone(&pending);
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let Ok(msg) = serde_json::from_str::<Value>(&line) else {
                    eprintln!("[engine] línea no JSON en stdout: {line}");
                    continue;
                };
                let Some(id) = msg.get("id").and_then(Value::as_u64) else {
                    continue;
                };
                if let Some(tx) = reader_pending.lock().unwrap().remove(&id) {
                    let _ = tx.send(msg);
                }
            }
            // EOF: el engine terminó; despertar a quien siga esperando.
            reader_pending.lock().unwrap().clear();
        });

        Ok(Self {
            child: Mutex::new(Some(child)),
            stdin: Mutex::new(stdin),
            pending,
            next_id: AtomicU64::new(1),
        })
    }

    /// Llamada bloqueante; usar desde un hilo de trabajo, nunca desde el hilo de UI.
    pub fn call(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = mpsc::channel();
        self.pending.lock().unwrap().insert(id, tx);
        let req = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        {
            let mut guard = self.stdin.lock().unwrap();
            let stdin = guard.as_mut().ok_or("engine detenido")?;
            writeln!(stdin, "{req}")
                .and_then(|_| stdin.flush())
                .map_err(|e| {
                    self.pending.lock().unwrap().remove(&id);
                    format!("no se pudo escribir al engine: {e}")
                })?;
        }
        let msg = rx.recv_timeout(timeout).map_err(|_| {
            self.pending.lock().unwrap().remove(&id);
            format!("sin respuesta del engine a '{method}'")
        })?;
        match (msg.get("result"), msg.get("error")) {
            (Some(result), _) => Ok(result.clone()),
            (_, Some(err)) => Err(err["message"]
                .as_str()
                .unwrap_or("error del engine")
                .to_string()),
            _ => Err("respuesta inválida del engine".into()),
        }
    }

    /// Apagado ordenado: cerrar stdin (el engine sale en EOF); si no sale, matarlo.
    pub fn shutdown(&self) {
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
