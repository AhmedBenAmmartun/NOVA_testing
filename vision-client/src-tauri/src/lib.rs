use serde::{Deserialize, Serialize};
use std::{env, path::{Path, PathBuf}, process::Command};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct VisionConnection {
    server_url: String,
    participant_token: String,
    room_name: String,
    identity: String,
}

fn project_root() -> Result<PathBuf, String> {
    if let Ok(value) = env::var("NOVA_PROJECT_ROOT") {
        let path = PathBuf::from(value);
        if path.join("agent.py").is_file() && path.join("vision_token.py").is_file() {
            return Ok(path);
        }
    }

    let current = env::current_dir().map_err(|_| "Could not determine the current directory.".to_string())?;
    for ancestor in current.ancestors() {
        if ancestor.join("agent.py").is_file() && ancestor.join("vision_token.py").is_file() {
            return Ok(ancestor.to_path_buf());
        }
    }

    Err("NOVA project root is not configured.".to_string())
}

fn python_path(root: &Path) -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        return root.join("venv").join("Scripts").join("python.exe");
    }
    #[cfg(not(target_os = "windows"))]
    {
        root.join("venv").join("bin").join("python")
    }
}

#[tauri::command]
fn get_livekit_connection() -> Result<VisionConnection, String> {
    let root = project_root()?;
    let python = python_path(&root);
    let helper = root.join("vision_token.py");

    if !python.is_file() {
        return Err("NOVA Python environment was not found.".to_string());
    }
    if !helper.is_file() {
        return Err("NOVA Vision token helper was not found.".to_string());
    }

    let mut command = Command::new(&python);
    command.arg(&helper).arg("--json").current_dir(&root);

    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000); // CREATE_NO_WINDOW

    let output = command
        .output()
        .map_err(|_| "Could not start the NOVA Vision token helper.".to_string())?;

    if !output.status.success() {
        return Err("NOVA Vision could not create connection credentials.".to_string());
    }

    serde_json::from_slice::<VisionConnection>(&output.stdout)
        .map_err(|_| "NOVA Vision received an invalid credential response.".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_livekit_connection])
        .run(tauri::generate_context!())
        .expect("error while running NOVA Vision");
}
