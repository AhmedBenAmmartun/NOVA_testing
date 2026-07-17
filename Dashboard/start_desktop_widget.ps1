param(
    [ValidateSet("orb", "mini", "compact", "full", "minimal", "focus", "study", "system")]
    [string]$Mode = "focus",
    [switch]$NoTray
)

$DashboardRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $DashboardRoot
$Pythonw = Join-Path $ProjectRoot "venv\Scripts\pythonw.exe"
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$Widget = Join-Path $DashboardRoot "desktop_widget.py"

if (Test-Path $Pythonw) {
    $arguments = @("`"$Widget`"", "--mode", $Mode)
    if ($NoTray) { $arguments += "--no-tray" }
    Start-Process -FilePath $Pythonw -ArgumentList $arguments -WorkingDirectory $ProjectRoot
} elseif (Test-Path $Python) {
    $arguments = @("`"$Widget`"", "--mode", $Mode)
    if ($NoTray) { $arguments += "--no-tray" }
    Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $ProjectRoot
} else {
    Write-Error "Could not find the NOVA Python environment under $ProjectRoot\venv."
    exit 1
}
