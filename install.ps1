# One-Line Automated Installer for Agent Comms (Windows PowerShell)
$ErrorActionPreference = "Stop"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Agent Comms: Automated One-Line Installer (Windows)" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Detect Python
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    $PythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $PythonCmd) {
    Write-Host "[-] Error: Python 3.9+ is required but not found in PATH." -ForegroundColor Red
    exit 1
}

Write-Host "[+] Using Python: $(python --version)" -ForegroundColor Green

# 2. Install package from GitHub
Write-Host "[+] Installing agent-comms from GitHub..." -ForegroundColor Green
python -m pip install --upgrade --quiet "git+https://github.com/BlahBlah23406/agent-comms.git"

# 3. Run automated setup
Write-Host "[+] Configuring AI assistant integrations..." -ForegroundColor Green
python -m agent_comms.cli setup

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Installation Successful! Try running:" -ForegroundColor Green
Write-Host "    agent-comms demo" -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Cyan
