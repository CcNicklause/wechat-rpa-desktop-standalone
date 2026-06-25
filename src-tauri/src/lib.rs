use std::sync::Mutex;
use std::process::{Child, Command};
use tauri::State;
use tauri::Manager;

struct AppState {
    token: String,
    python_process: Mutex<Option<Child>>,
}

#[tauri::command]
fn get_security_token(state: State<'_, AppState>) -> String {
    state.token.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Generate a random local security token
    let security_token = format!("local_tok_{}", uuid::Uuid::new_v4().to_string().replace("-", ""));
    let token_clone = security_token.clone();

    tauri::Builder::default()
        .manage(AppState {
            token: security_token,
            python_process: Mutex::new(None),
        })
        .setup(move |app| {
            // Set current directory to python backend
            let resource_dir = app.path().resource_dir().unwrap();
            let python_dir = resource_dir.join("python");

            let current_dir = std::env::current_dir().unwrap();
            println!("[DIAGNOSTIC] std::env::current_dir = {:?}", current_dir);

            // 选 python 源码目录：必须能看到 backend/__init__.py 才算数。
            // 仅看目录是否存在会误选打包用的空壳 src-tauri/python/（只装 sidecar exe，
            // 没有 backend 源码），导致 `uv run uvicorn backend.app.main:app` 报
            // ModuleNotFoundError: No module named 'backend'。
            let has_backend = |p: &std::path::Path| p.join("backend").join("__init__.py").exists();

            let dev_python_dir = if has_backend(&current_dir.join("python")) {
                current_dir.join("python")
            } else if let Some(parent) = current_dir.parent() {
                if has_backend(&parent.join("python")) {
                    parent.join("python")
                } else {
                    python_dir.clone()
                }
            } else {
                python_dir.clone()
            };

            let final_dir = if has_backend(&dev_python_dir) { dev_python_dir } else { python_dir };
            println!("[DIAGNOSTIC] final_dir resolved to = {:?}", final_dir);

            // Spin up Python development server natively in the background
            let mut cmd = Command::new("uv");
            cmd.args(&["run", "uvicorn", "backend.app.main:app", "--port", "8000", "--host", "127.0.0.1"]);
            cmd.current_dir(&final_dir);
            cmd.env("LOCAL_SECURITY_TOKEN", &token_clone);
            cmd.env("PYTHONPATH", &final_dir);
            
            let child = cmd.spawn().expect("failed to start Python sidecar backend");
            
            let state = app.state::<AppState>();
            *state.python_process.lock().unwrap() = Some(child);
            
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<AppState>();
                let mut process = state.python_process.lock().unwrap();
                if let Some(mut child) = process.take() {
                    let _ = child.kill();
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![get_security_token])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
