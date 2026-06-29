use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, State};
use tokio::sync::Mutex as AsyncMutex;

mod terminal;

use reqwest::header::{HeaderMap, HeaderValue};
use terminal::{MgrClient, TerminalManager};

struct AppState {
    token: String,
    python_process: Mutex<Option<Child>>,
    /// 当前活跃的 Portal session 副本，供 terminal 模块与 logout 路径读取。
    /// 仅在登录成功 / session 恢复时写入；logout 清空。
    portal_session: Arc<AsyncMutex<Option<PortalSession>>>,
    /// 终端上报管理器单例，登录后构造，进程退出前 abort heartbeat。
    terminal_manager: Arc<AsyncMutex<Option<Arc<TerminalManager>>>>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct PortalUser {
    id: String,
    user_id: String,
    email: Option<String>,
    phone: String,
    name: String,
    role: String,
    tenant_id: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct PortalSession {
    access_token: String,
    user: PortalUser,
    saved_at: u64,
}

#[derive(Debug, Deserialize)]
struct PortalAuthResponse {
    access_token: String,
    user: Value,
}

#[derive(Debug, Serialize, Deserialize)]
struct SendCodeResponse {
    success: bool,
    message: String,
    code: Option<String>,
}

#[derive(Debug, Serialize)]
struct PortalCommandError {
    status: Option<u16>,
    code: String,
    message: String,
}

type PortalResult<T> = Result<T, PortalCommandError>;

fn portal_api_base() -> String {
    std::env::var("AISALES_PORTAL_API_BASE")
        .unwrap_or_else(|_| "http://aisales-portal.app.qa.internal.weimob.com/api/v1".to_string())
        .trim_end_matches('/')
        .to_string()
}

fn portal_client() -> PortalResult<reqwest::Client> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|err| PortalCommandError {
            status: None,
            code: "PORTAL_CLIENT_ERROR".to_string(),
            message: err.to_string(),
        })
}

fn portal_desktop_headers() -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert("x-aisales-client", HeaderValue::from_static("desktop"));
    headers.insert(
        "x-aisales-session-scope",
        HeaderValue::from_static("desktop"),
    );
    headers
}

fn session_path(app: &AppHandle) -> PortalResult<PathBuf> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|err| PortalCommandError {
            status: None,
            code: "SESSION_PATH_ERROR".to_string(),
            message: err.to_string(),
        })?;
    fs::create_dir_all(&dir).map_err(|err| PortalCommandError {
        status: None,
        code: "SESSION_CREATE_DIR_ERROR".to_string(),
        message: err.to_string(),
    })?;
    Ok(dir.join("portal-session.json"))
}

fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn value_to_string(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::String(text)) if !text.trim().is_empty() => Some(text.clone()),
        Some(Value::Number(number)) => Some(number.to_string()),
        _ => None,
    }
}

fn value_to_i64(value: Option<&Value>) -> Option<i64> {
    match value {
        Some(Value::Number(number)) => number.as_i64(),
        Some(Value::String(text)) => text.parse::<i64>().ok(),
        _ => None,
    }
}

fn normalize_portal_user(user: Value) -> PortalResult<PortalUser> {
    let object = user.as_object().ok_or_else(|| PortalCommandError {
        status: None,
        code: "INVALID_USER_PAYLOAD".to_string(),
        message: "Portal 返回的用户信息格式不正确".to_string(),
    })?;

    let id = value_to_string(object.get("id")).ok_or_else(|| PortalCommandError {
        status: None,
        code: "MISSING_USER_ID".to_string(),
        message: "Portal 返回缺少用户 ID".to_string(),
    })?;
    let user_id = value_to_string(object.get("user_id")).unwrap_or_else(|| id.clone());
    let phone = value_to_string(object.get("phone")).unwrap_or_default();
    let name = value_to_string(object.get("name")).unwrap_or_else(|| {
        if phone.is_empty() {
            "未命名用户".to_string()
        } else {
            phone.clone()
        }
    });
    let role = value_to_string(object.get("role")).unwrap_or_else(|| "sales".to_string());
    let tenant_id = value_to_i64(object.get("tenant_id")).ok_or_else(|| PortalCommandError {
        status: None,
        code: "MISSING_TENANT_ID".to_string(),
        message: "Portal 返回缺少租户 ID".to_string(),
    })?;
    let email = value_to_string(object.get("email"));

    Ok(PortalUser {
        id,
        user_id,
        email,
        phone,
        name,
        role,
        tenant_id,
    })
}

fn save_session(app: &AppHandle, session: &PortalSession) -> PortalResult<()> {
    let path = session_path(app)?;
    let payload = serde_json::to_string_pretty(session).map_err(|err| PortalCommandError {
        status: None,
        code: "SESSION_SERIALIZE_ERROR".to_string(),
        message: err.to_string(),
    })?;
    fs::write(path, payload).map_err(|err| PortalCommandError {
        status: None,
        code: "SESSION_WRITE_ERROR".to_string(),
        message: err.to_string(),
    })
}

fn read_session(app: &AppHandle) -> PortalResult<Option<PortalSession>> {
    let path = session_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let payload = fs::read_to_string(path).map_err(|err| PortalCommandError {
        status: None,
        code: "SESSION_READ_ERROR".to_string(),
        message: err.to_string(),
    })?;
    serde_json::from_str::<PortalSession>(&payload)
        .map(Some)
        .map_err(|err| PortalCommandError {
            status: None,
            code: "SESSION_PARSE_ERROR".to_string(),
            message: err.to_string(),
        })
}

fn clear_session(app: &AppHandle) -> PortalResult<()> {
    let path = session_path(app)?;
    if path.exists() {
        fs::remove_file(path).map_err(|err| PortalCommandError {
            status: None,
            code: "SESSION_DELETE_ERROR".to_string(),
            message: err.to_string(),
        })?;
    }
    Ok(())
}

async fn parse_portal_response<T: for<'de> Deserialize<'de>>(
    response: reqwest::Response,
) -> PortalResult<T> {
    let status = response.status();
    if status.is_success() {
        return response
            .json::<T>()
            .await
            .map_err(|err| PortalCommandError {
                status: Some(status.as_u16()),
                code: "PORTAL_RESPONSE_PARSE_ERROR".to_string(),
                message: err.to_string(),
            });
    }

    let fallback = format!("Portal 请求失败 ({})", status.as_u16());
    let body = response.text().await.unwrap_or_default();
    let message = serde_json::from_str::<Value>(&body)
        .ok()
        .and_then(|value| value.get("message").cloned())
        .and_then(|message| match message {
            Value::String(text) => Some(text),
            Value::Array(items) => Some(
                items
                    .into_iter()
                    .filter_map(|item| item.as_str().map(ToOwned::to_owned))
                    .collect::<Vec<_>>()
                    .join("；"),
            ),
            _ => None,
        })
        .filter(|text| !text.trim().is_empty())
        .unwrap_or(fallback);

    Err(PortalCommandError {
        status: Some(status.as_u16()),
        code: if status.as_u16() == 401 {
            "UNAUTHORIZED".to_string()
        } else {
            "PORTAL_REQUEST_ERROR".to_string()
        },
        message,
    })
}

async fn portal_login(app: AppHandle, payload: Value, path: &str) -> PortalResult<PortalSession> {
    let client = portal_client()?;
    let response = client
        .post(format!("{}/{}", portal_api_base(), path))
        .headers(portal_desktop_headers())
        .json(&payload)
        .send()
        .await
        .map_err(|err| PortalCommandError {
            status: None,
            code: "PORTAL_NETWORK_ERROR".to_string(),
            message: err.to_string(),
        })?;
    let raw = parse_portal_response::<PortalAuthResponse>(response).await?;
    let session = PortalSession {
        access_token: raw.access_token,
        user: normalize_portal_user(raw.user)?,
        saved_at: now_seconds(),
    };
    save_session(&app, &session)?;
    Ok(session)
}

#[cfg(target_os = "windows")]
fn kill_existing_backend_on_port(port: u16) {
    let output = Command::new("netstat").args(["-ano", "-p", "tcp"]).output();
    let Ok(output) = output else {
        return;
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut pids = std::collections::HashSet::new();
    let port_suffix = format!(":{port}");

    for line in stdout.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 5 {
            continue;
        }
        let local_addr = parts[1];
        let state = parts[3];
        let pid = parts[4];
        if state == "LISTENING" && local_addr.ends_with(&port_suffix) {
            pids.insert(pid.to_string());
        }
    }

    for pid in pids {
        let _ = Command::new("taskkill").args(["/PID", &pid, "/F"]).output();
    }
}

#[cfg(not(target_os = "windows"))]
fn kill_existing_backend_on_port(_port: u16) {}

#[tauri::command]
fn get_security_token(state: State<'_, AppState>) -> String {
    state.token.clone()
}

#[tauri::command]
async fn portal_login_password(
    app: AppHandle,
    phone: String,
    password: String,
) -> PortalResult<PortalSession> {
    portal_login(
        app,
        json!({ "phone": phone, "password": password }),
        "auth/login",
    )
    .await
}

#[tauri::command]
async fn portal_login_sms(
    app: AppHandle,
    phone: String,
    code: String,
) -> PortalResult<PortalSession> {
    portal_login(
        app,
        json!({ "phone": phone, "code": code }),
        "auth/login-by-sms",
    )
    .await
}

#[tauri::command]
async fn portal_send_sms_code(phone: String) -> PortalResult<SendCodeResponse> {
    let client = portal_client()?;
    let response = client
        .post(format!("{}/sms/send-code", portal_api_base()))
        .headers(portal_desktop_headers())
        .json(&json!({ "phone": phone, "type": "login" }))
        .send()
        .await
        .map_err(|err| PortalCommandError {
            status: None,
            code: "PORTAL_NETWORK_ERROR".to_string(),
            message: err.to_string(),
        })?;
    parse_portal_response::<SendCodeResponse>(response).await
}

#[tauri::command]
async fn portal_get_session(app: AppHandle) -> PortalResult<Option<PortalSession>> {
    let Some(current) = read_session(&app)? else {
        return Ok(None);
    };

    let client = portal_client()?;
    let response = client
        .get(format!("{}/auth/me", portal_api_base()))
        .headers(portal_desktop_headers())
        .bearer_auth(&current.access_token)
        .send()
        .await
        .map_err(|err| PortalCommandError {
            status: None,
            code: "PORTAL_NETWORK_ERROR".to_string(),
            message: err.to_string(),
        })?;

    match parse_portal_response::<Value>(response).await {
        Ok(user) => {
            let session = PortalSession {
                access_token: current.access_token,
                user: normalize_portal_user(user)?,
                saved_at: current.saved_at,
            };
            save_session(&app, &session)?;
            Ok(Some(session))
        }
        Err(err) if err.status == Some(401) => {
            clear_session(&app)?;
            Ok(None)
        }
        Err(err) => Err(err),
    }
}

#[tauri::command]
fn portal_logout(app: AppHandle) -> PortalResult<()> {
    clear_session(&app)?;
    // 异步：尽力上报 offline + abort heartbeat，整体 2s 超时不阻塞 UI。
    let state = app.state::<AppState>();
    let manager_slot = Arc::clone(&state.terminal_manager);
    let session_slot = Arc::clone(&state.portal_session);
    tauri::async_runtime::spawn(async move {
        let (manager, token, tenant_id) = {
            let mgr_guard = manager_slot.lock().await;
            let sess_guard = session_slot.lock().await;
            match (mgr_guard.as_ref(), sess_guard.as_ref()) {
                (Some(m), Some(s)) => (
                    Some(Arc::clone(m)),
                    Some(s.access_token.clone()),
                    Some(s.user.tenant_id),
                ),
                _ => (None, None, None),
            }
        };
        if let (Some(manager), Some(token), Some(tenant_id)) = (manager, token, tenant_id) {
            let _ = tokio::time::timeout(
                Duration::from_secs(2),
                manager.shutdown(token, tenant_id, "logout"),
            )
            .await;
        } else if let Some(manager) = manager_slot.lock().await.as_ref() {
            // session 已被清空但 manager 还在：至少 abort heartbeat
            manager.abort_heartbeat().await;
        }
        *manager_slot.lock().await = None;
        *session_slot.lock().await = None;
    });
    Ok(())
}

/// 由前端在登录成功 / session 恢复成功后调用一次。
/// 内部：写入 portal_session 副本 → 启动/重启 terminal manager 与 heartbeat。
/// 失败不阻塞登录链路；错误仅打日志。
#[tauri::command]
async fn terminal_initialize(app: AppHandle, session: PortalSession) -> Result<(), String> {
    eprintln!(
        "[terminal] terminal_initialize 命令收到 tenant_id={} user={}",
        session.user.tenant_id, session.user.phone
    );
    let state_arc = app.state::<AppState>();

    // 后端兜底去重：同 token + 同 manager 已存在，仅刷新 heartbeat，跳过 record/status=online。
    // 防御 React StrictMode 双触发、前端去重失效等情况，避免向 MGR 重复打 record。
    let already_initialized_for_same_token = {
        let sess_guard = state_arc.portal_session.lock().await;
        let mgr_guard = state_arc.terminal_manager.lock().await;
        sess_guard
            .as_ref()
            .map(|s| s.access_token == session.access_token)
            .unwrap_or(false)
            && mgr_guard.is_some()
    };
    if already_initialized_for_same_token {
        eprintln!("[terminal] terminal_initialize 跳过 (同 token 已初始化)");
        return Ok(());
    }

    {
        let mut guard = state_arc.portal_session.lock().await;
        *guard = Some(session.clone());
    }

    // 已存在 manager 则先 abort 旧 heartbeat（账号切换场景）
    {
        let guard = state_arc.terminal_manager.lock().await;
        if let Some(existing) = guard.as_ref() {
            existing.abort_heartbeat().await;
        }
    }

    let identity = terminal::load_or_create_identity(&app);
    let client = MgrClient::new(portal_api_base())?;
    let manager = Arc::new(TerminalManager::new(identity, client));
    {
        let mut guard = state_arc.terminal_manager.lock().await;
        *guard = Some(Arc::clone(&manager));
    }

    // 后台跑：不阻塞前端登录 await。
    let token = session.access_token.clone();
    let tenant_id = session.user.tenant_id;
    tauri::async_runtime::spawn(async move {
        manager.initialize(token, tenant_id).await;
    });

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Generate a random local security token
    let security_token = format!(
        "local_tok_{}",
        uuid::Uuid::new_v4().to_string().replace("-", "")
    );
    let token_clone = security_token.clone();

    tauri::Builder::default()
        .manage(AppState {
            token: security_token,
            python_process: Mutex::new(None),
            portal_session: Arc::new(AsyncMutex::new(None)),
            terminal_manager: Arc::new(AsyncMutex::new(None)),
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

            let final_dir = if has_backend(&dev_python_dir) {
                dev_python_dir
            } else {
                python_dir
            };
            println!("[DIAGNOSTIC] final_dir resolved to = {:?}", final_dir);

            // Spin up Python development server natively in the background
            kill_existing_backend_on_port(8000);
            let mut cmd = Command::new("uv");
            cmd.args(&[
                "run",
                "uvicorn",
                "backend.app.main:app",
                "--port",
                "8000",
                "--host",
                "127.0.0.1",
            ]);
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
                // 终端上报：尽力上报 offline + abort heartbeat，1.5s 超时不阻塞退出。
                let state = window.state::<AppState>();
                let manager_slot = Arc::clone(&state.terminal_manager);
                let session_slot = Arc::clone(&state.portal_session);
                tauri::async_runtime::block_on(async move {
                    let snapshot = {
                        let mgr = manager_slot.lock().await;
                        let sess = session_slot.lock().await;
                        match (mgr.as_ref(), sess.as_ref()) {
                            (Some(m), Some(s)) => {
                                Some((Arc::clone(m), s.access_token.clone(), s.user.tenant_id))
                            }
                            _ => None,
                        }
                    };
                    if let Some((manager, token, tenant_id)) = snapshot {
                        let _ = tokio::time::timeout(
                            Duration::from_secs_f32(1.5),
                            manager.shutdown(token, tenant_id, "app_exit"),
                        )
                        .await;
                    }
                });

                let state = window.state::<AppState>();
                let mut process = state.python_process.lock().unwrap();
                if let Some(mut child) = process.take() {
                    let _ = child.kill();
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            get_security_token,
            portal_login_password,
            portal_login_sms,
            portal_send_sms_code,
            portal_get_session,
            portal_logout,
            terminal_initialize,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_login_user_payload() {
        let user = normalize_portal_user(json!({
            "id": 12,
            "user_id": "u_abc",
            "email": null,
            "phone": "13800138000",
            "name": "测试用户",
            "role": "sales",
            "tenant_id": 100024
        }))
        .unwrap();

        assert_eq!(user.id, "12");
        assert_eq!(user.user_id, "u_abc");
        assert_eq!(user.tenant_id, 100024);
    }

    #[test]
    fn normalizes_me_user_payload_without_user_id() {
        let user = normalize_portal_user(json!({
            "id": "u_abc",
            "email": null,
            "phone": "13800138000",
            "name": "测试用户",
            "role": "sales",
            "tenant_id": "100024"
        }))
        .unwrap();

        assert_eq!(user.id, "u_abc");
        assert_eq!(user.user_id, "u_abc");
        assert_eq!(user.tenant_id, 100024);
    }

    #[test]
    fn portal_requests_are_tagged_as_desktop_client() {
        let headers = portal_desktop_headers();

        assert_eq!(
            headers
                .get("x-aisales-client")
                .and_then(|value| value.to_str().ok()),
            Some("desktop")
        );
        assert_eq!(
            headers
                .get("x-aisales-session-scope")
                .and_then(|value| value.to_str().ok()),
            Some("desktop")
        );
    }
}
