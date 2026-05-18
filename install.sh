#!/usr/bin/env bash
# Optima — macOS / Linux installer
#
# Run from the project root once after unzipping:
#     bash install.sh
#
# What it does:
#   1. Confirms Python 3.11+ is available
#   2. Creates a virtual environment in .venv/
#   3. Installs Flask, pywebview, python-docx into the venv
#   4. Writes a launcher script Optima.command on your desktop (macOS)
#      or ~/.local/bin/optima (Linux) so you can launch with a double-click
#
# Re-running this script is safe — every step is idempotent.

set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "==> Optima installer"
echo "    Project directory: $PROJECT_DIR"

# ---- 1. Python check ------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is not on your PATH."
    echo "       Install Python 3.11 or newer from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PYTHON_MAJOR="$(python3 -c 'import sys; print(sys.version_info[0])')"
PYTHON_MINOR="$(python3 -c 'import sys; print(sys.version_info[1])')"

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python $PYTHON_VERSION found, but Optima needs 3.11 or newer."
    exit 1
fi
echo "    Python $PYTHON_VERSION — OK"

# ---- 2. Virtual environment ----------------------------------------------
if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment in .venv/"
    python3 -m venv .venv
else
    echo "    Virtual environment already exists — reusing"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ---- 3. Dependencies -----------------------------------------------------
echo "==> Installing dependencies (this takes 30–60 seconds first run)"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ---- 4. Desktop launcher -------------------------------------------------
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    LAUNCHER="$HOME/Desktop/Optima.command"
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
cd "$PROJECT_DIR"
source .venv/bin/activate
python run.py
EOF
    chmod +x "$LAUNCHER"
    echo "==> Wrote macOS launcher → $LAUNCHER"
    echo "    Double-click that file to launch Optima."
elif [ "$OS" = "Linux" ]; then
    mkdir -p "$HOME/.local/bin"
    LAUNCHER="$HOME/.local/bin/optima"
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
cd "$PROJECT_DIR"
source .venv/bin/activate
python run.py "\$@"
EOF
    chmod +x "$LAUNCHER"
    echo "==> Wrote Linux launcher → $LAUNCHER"
    echo "    Make sure $HOME/.local/bin is on your PATH, then run: optima"
else
    echo "==> Skipping launcher creation — unknown OS '$OS'."
fi

echo
echo "==> Done. Launch Optima with:"
echo "        cd \"$PROJECT_DIR\""
echo "        source .venv/bin/activate"
echo "        python run.py"
echo
echo "    Or use the launcher created above."
