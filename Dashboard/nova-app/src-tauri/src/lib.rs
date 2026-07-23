//! NOVA Desktop — Tauri 2 shell around the existing NOVA dashboard.
//!
//! Responsibilities that belong on the native side:
//!   * spawn the existing Python data server (`Dashboard/server.py`) silently
//!     as a child process and shut it down on quit / restart it on demand,
//!   * a system-tray icon + menu,
//!   * close-to-tray, single-instance focus, window/desktop modes,
//!   * "Start with Windows" through the autostart plugin.
//!
//! The UI itself is the unchanged design shell in `Dashboard/web`, bundled as
//! the Tauri frontend; it talks to the Python server over the same WebSocket
//! (`ws://127.0.0.1:8787/ws`) it already uses in the browser.

use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    menu::{CheckMenuItemBuilder, MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, Position, Size, State,
    WebviewWindow, WindowEvent,
};

const BACKEND_ADDR: &str = "127.0.0.1:8787";

/// Native-side app state: the backend child process and the always-on-top flag.
struct AppState {
    backend: Mutex<Option<Child>>,
    always_on_top: Mutex<bool>,
}

// ---------------------------------------------------------------------------
// Backend (Python data server) lifecycle
// ---------------------------------------------------------------------------

fn is_backend_up() -> bool {
    match BACKEND_ADDR.parse::<SocketAddr>() {
        Ok(addr) => TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok(),
        Err(_) => false,
    }
}

fn is_project_root(dir: &Path) -> bool {
    dir.join("Dashboard").join("server.py").is_file()
        && dir.join("venv").join("Scripts").join("pythonw.exe").is_file()
}

/// Locate the NOVA project so we can find the venv + server.py.
///
/// Priority: `NOVA_PROJECT_ROOT` env var, then the installed/dev exe's parent
/// chain, then the known default install location.
fn project_root() -> Option<PathBuf> {
    if let Ok(env_root) = std::env::var("NOVA_PROJECT_ROOT") {
        let candidate = PathBuf::from(env_root);
        if is_project_root(&candidate) {
            return Some(candidate);
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        for ancestor in exe.ancestors() {
            if is_project_root(ancestor) {
                return Some(ancestor.to_path_buf());
            }
        }
    }
    let fallback = PathBuf::from(r"C:\Users\ahmed\OneDrive\Desktop\AI Agent");
    if is_project_root(&fallback) {
        return Some(fallback);
    }
    None
}

/// Start `pythonw.exe Dashboard/server.py` with no console window.
fn spawn_backend() -> Option<Child> {
    let root = project_root()?;
    let pythonw = root.join("venv").join("Scripts").join("pythonw.exe");
    let server = root.join("Dashboard").join("server.py");

    let mut command = Command::new(pythonw);
    command.arg(server).current_dir(&root);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    command.spawn().ok()
}

/// Ensure the backend is running. If one is already listening (e.g. started
/// externally) we reuse it rather than starting a second instance.
fn ensure_backend(state: &AppState) {
    if is_backend_up() {
        return;
    }
    if let Some(child) = spawn_backend() {
        *state.backend.lock().unwrap() = Some(child);
    }
}

fn kill_backend(state: &AppState) {
    if let Some(mut child) = state.backend.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

// ---------------------------------------------------------------------------
// Window helpers
// ---------------------------------------------------------------------------

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn autostart_enabled(app: &AppHandle) -> bool {
    use tauri_plugin_autostart::ManagerExt;
    app.autolaunch().is_enabled().unwrap_or(false)
}

// ---------------------------------------------------------------------------
// Commands invoked from the dashboard frontend
// ---------------------------------------------------------------------------

#[tauri::command]
fn win_minimize(win: WebviewWindow) {
    let _ = win.minimize();
}

#[tauri::command]
fn win_toggle_maximize(win: WebviewWindow) {
    match win.is_maximized() {
        Ok(true) => {
            let _ = win.unmaximize();
        }
        _ => {
            let _ = win.maximize();
        }
    }
}

#[tauri::command]
fn win_hide(win: WebviewWindow) {
    let _ = win.hide();
}

#[tauri::command]
fn win_show(win: WebviewWindow) {
    let _ = win.show();
    let _ = win.unminimize();
    let _ = win.set_focus();
}

/// Rainmeter-like desktop mode: borderless, pinned to the bottom of the z-order,
/// no taskbar button, sized to the work area (which excludes the taskbar).
#[tauri::command]
fn enter_desktop_mode(win: WebviewWindow, x: f64, y: f64, w: f64, h: f64) {
    let _ = win.unmaximize();
    let _ = win.set_resizable(false);
    let _ = win.set_skip_taskbar(true);
    let _ = win.set_always_on_top(false);
    let _ = win.set_always_on_bottom(true);
    let _ = win.set_size(Size::Logical(LogicalSize::new(w, h)));
    let _ = win.set_position(Position::Logical(LogicalPosition::new(x, y)));
    let _ = win.show();
}

#[tauri::command]
fn enter_dashboard_mode(win: WebviewWindow) {
    let _ = win.set_always_on_bottom(false);
    let _ = win.set_skip_taskbar(false);
    let _ = win.set_ignore_cursor_events(false);
    let _ = win.set_resizable(true);
    let _ = win.show();
    let _ = win.set_focus();
}

#[tauri::command]
fn set_always_on_top(win: WebviewWindow, state: State<'_, AppState>, on: bool) {
    let _ = win.set_always_on_top(on);
    *state.always_on_top.lock().unwrap() = on;
}

#[tauri::command]
fn set_click_through(win: WebviewWindow, on: bool) {
    let _ = win.set_ignore_cursor_events(on);
}

#[tauri::command]
fn set_autostart(app: AppHandle, on: bool) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    let manager = app.autolaunch();
    if on {
        manager.enable().map_err(|e| e.to_string())?;
    } else {
        manager.disable().map_err(|e| e.to_string())?;
    }
    manager.is_enabled().map_err(|e| e.to_string())
}

#[tauri::command]
fn get_autostart(app: AppHandle) -> bool {
    autostart_enabled(&app)
}

#[tauri::command]
fn restart_backend(app: AppHandle) {
    let state = app.state::<AppState>();
    kill_backend(state.inner());
    std::thread::sleep(Duration::from_millis(600));
    if let Some(child) = spawn_backend() {
        *state.backend.lock().unwrap() = Some(child);
    }
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    let state = app.state::<AppState>();
    kill_backend(state.inner());
    app.exit(0);
}

// ---------------------------------------------------------------------------
// System tray
// ---------------------------------------------------------------------------

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItemBuilder::with_id("open", "Show NOVA Desktop").build(app)?;
    let hide = MenuItemBuilder::with_id("hide", "Hide NOVA Desktop").build(app)?;
    let desktop = MenuItemBuilder::with_id("desktop", "Return to Interactive Desktop").build(app)?;
    let edit = MenuItemBuilder::with_id("edit", "Toggle Edit Mode").build(app)?;
    let click_through = MenuItemBuilder::with_id("click-through", "Toggle Click-through").build(app)?;
    let aot = CheckMenuItemBuilder::with_id("aot", "Always on Top")
        .checked(false)
        .build(app)?;
    let autostart = CheckMenuItemBuilder::with_id("autostart", "Start with Windows")
        .checked(autostart_enabled(app))
        .build(app)?;
    let restart = MenuItemBuilder::with_id("restart", "Restart NOVA").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit NOVA").build(app)?;

    let menu = MenuBuilder::new(app)
        .items(&[&open, &hide, &desktop, &edit, &click_through])
        .separator()
        .items(&[&aot, &autostart])
        .separator()
        .items(&[&restart, &quit])
        .build()?;

    let aot_item = aot.clone();
    let autostart_item = autostart.clone();

    TrayIconBuilder::with_id("nova-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("NOVA")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "open" => {
                show_main(app);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://enter-desktop", ());
                }
            }
            "hide" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            "desktop" => {
                show_main(app);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://enter-desktop", ());
                }
            }
            "edit" => {
                show_main(app);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://toggle-edit", ());
                }
            }
            "click-through" => {
                show_main(app);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://toggle-click-through", ());
                }
            }
            "aot" => {
                let state = app.state::<AppState>();
                let next = {
                    let mut flag = state.always_on_top.lock().unwrap();
                    *flag = !*flag;
                    *flag
                };
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.set_always_on_top(next);
                }
                let _ = aot_item.set_checked(next);
            }
            "autostart" => {
                use tauri_plugin_autostart::ManagerExt;
                let manager = app.autolaunch();
                if manager.is_enabled().unwrap_or(false) {
                    let _ = manager.disable();
                } else {
                    let _ = manager.enable();
                }
                let _ = autostart_item.set_checked(manager.is_enabled().unwrap_or(false));
            }
            "restart" => {
                restart_backend(app.clone());
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://reconnect", ());
                }
            }
            "quit" => {
                let state = app.state::<AppState>();
                kill_backend(state.inner());
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let app = tray.app_handle();
                show_main(app);
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.emit("nova://enter-desktop", ());
                }
            }
        })
        .build(app)?;

    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // Second launch: focus the running instance instead of starting a new one.
            show_main(app);
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(AppState {
            backend: Mutex::new(None),
            always_on_top: Mutex::new(false),
        })
        .invoke_handler(tauri::generate_handler![
            win_minimize,
            win_toggle_maximize,
            win_hide,
            win_show,
            enter_desktop_mode,
            enter_dashboard_mode,
            set_always_on_top,
            set_click_through,
            set_autostart,
            get_autostart,
            restart_backend,
            quit_app
        ])
        .setup(|app| {
            let state = app.state::<AppState>();
            ensure_backend(state.inner());
            build_tray(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window hides it to the tray; NOVA keeps running.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the NOVA desktop app")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let state = app_handle.state::<AppState>();
                kill_backend(state.inner());
            }
        });
}
