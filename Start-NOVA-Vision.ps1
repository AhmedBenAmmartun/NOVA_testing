param(
    [string]$ProjectRoot = "C:\Projects\AI Agent"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

Write-Host "=== NOVA Vision Phase 1 ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Camera and microphone will start OFF." -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { Fail "Project folder not found." }

$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$Agent = Join-Path $ProjectRoot "agent.py"
$VisionClient = Join-Path $ProjectRoot "vision-client"
$TokenHelper = Join-Path $ProjectRoot "vision_token.py"

foreach ($Path in @($Python, $Agent, $VisionClient, $TokenHelper)) {
    if (-not (Test-Path -LiteralPath $Path)) { Fail "Required NOVA Vision component is missing: $Path" }
}

$Node = Get-Command node -ErrorAction SilentlyContinue
$Npm = Get-Command npm -ErrorAction SilentlyContinue
$Cargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $Node) { Fail "Node.js is not installed or not on PATH." }
if (-not $Npm) { Fail "npm is not installed or not on PATH." }
if (-not $Cargo) { Fail "Rust/Cargo is not installed or not on PATH." }

# Tauri on Windows needs the MSVC C++ build tools. Check with vswhere when available.
$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$HasMsvc = $false
if (Test-Path -LiteralPath $VsWhere) {
    $InstallPath = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    $HasMsvc = -not [string]::IsNullOrWhiteSpace(($InstallPath | Select-Object -First 1))
}
if (-not $HasMsvc -and (Get-Command cl.exe -ErrorAction SilentlyContinue)) { $HasMsvc = $true }
if (-not $HasMsvc) {
    Fail "Microsoft C++ Build Tools were not detected. Install the Tauri Windows prerequisites (Desktop development with C++) and run this launcher again."
}

$env:NOVA_PROJECT_ROOT = $ProjectRoot
$StartedWorker = $null

try {
    # Reuse a live 'agent.py dev' worker when one already exists.
    $ExistingWorker = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -like "*agent.py*" -and
            $_.CommandLine -match '(?i)(^|\s)dev(\s|$)'
        } |
        Select-Object -First 1

    if ($ExistingWorker) {
        Write-Host "Using existing NOVA LiveKit worker (PID $($ExistingWorker.ProcessId))." -ForegroundColor Green
    } else {
        Write-Host "Starting NOVA LiveKit worker in dev mode..."
        $StartedWorker = Start-Process -FilePath $Python -ArgumentList @("agent.py", "dev") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 2
        if ($StartedWorker.HasExited) {
            Fail ('The NOVA LiveKit worker exited during startup. Run: Set-Location "{0}"; & "{1}" agent.py dev' -f $ProjectRoot, $Python)
        }
        Write-Host "NOVA worker started (PID $($StartedWorker.Id))." -ForegroundColor Green
    }

    Set-Location -LiteralPath $VisionClient
    if (-not (Test-Path -LiteralPath (Join-Path $VisionClient "node_modules"))) {
        Write-Host "Installing NOVA Vision JavaScript dependencies (first run only)..."
        & npm install
        if ($LASTEXITCODE -ne 0) { Fail "npm install failed." }
    }

    Write-Host "Opening NOVA Vision..." -ForegroundColor Cyan
    & npm run tauri:dev
    if ($LASTEXITCODE -ne 0) { Fail "NOVA Vision Tauri development run failed." }
}
finally {
    if ($StartedWorker -and -not $StartedWorker.HasExited) {
        Write-Host "Stopping the NOVA worker started by this launcher..."
        Stop-Process -Id $StartedWorker.Id -Force -ErrorAction SilentlyContinue
    }
    Set-Location -LiteralPath $ProjectRoot
}
