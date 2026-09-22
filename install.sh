#!/usr/bin/env bash
# One-Line Automated Installer for Agent Comms (macOS & Linux)
set -e

echo "=================================================================="
echo "  Agent Comms: Automated One-Line Installer (macOS / Linux)"
echo "=================================================================="

# 1. Detect Python
PYTHON_BIN=""
if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "[-] Error: Python 3.9+ is required. Please install Python first."
    exit 1
fi

echo "[+] Using Python: $($PYTHON_BIN --version) at $(which $PYTHON_BIN)"

# 2. Install package from GitHub
echo "[+] Installing agent-comms..."
$PYTHON_BIN -m pip install --upgrade --quiet "git+https://github.com/BlahBlah23406/agent-comms.git"

# 3. Run automated MCP and environment setup
echo "[+] Configuring AI assistant integrations (Claude Desktop, Claude Code, Antigravity, Cursor)..."
$PYTHON_BIN -m agent_comms.cli setup "$@"

echo ""
echo "=================================================================="
echo "  Installation Successful! Try running:"
echo "    agent-comms demo"
echo "=================================================================="
