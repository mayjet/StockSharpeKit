#!/bin/bash
# ============================================
#  Local dev environment setup (uv venv)
#  Streamlit app + Jupyter notebook
# ============================================

set -euo pipefail

VENV_DIR="./.venv"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
echo "[setup] Project root: $PROJECT_ROOT"

# ============================================
#  Step 1: Check Python
# ============================================
echo ""
echo "[1/6] Checking Python..."

if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version 2>&1)
    echo "[setup] $PY_VERSION found."
elif command -v python &> /dev/null; then
    PY_VERSION=$(python --version 2>&1)
    echo "[setup] $PY_VERSION found."
else
    echo "[ERROR] Python is not installed."
    echo "        Install via Homebrew: brew install python"
    exit 1
fi

# ============================================
#  Step 2: Check / Install uv
# ============================================
echo ""
echo "[2/6] Checking uv..."

if command -v uv &> /dev/null; then
    echo "[setup] $(uv --version) found."
else
    echo "[setup] uv not found. Installing..."

    if command -v brew &> /dev/null; then
        echo "[setup] Installing uv via Homebrew..."
        brew install uv
    elif command -v pip3 &> /dev/null; then
        echo "[setup] Installing uv via pip3..."
        pip3 install uv
    elif command -v pip &> /dev/null; then
        echo "[setup] Installing uv via pip..."
        pip install uv
    else
        echo "[ERROR] No package manager available to install uv."
        echo "        Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    # Verify installation
    if ! command -v uv &> /dev/null; then
        echo "[ERROR] uv was installed but cannot be found in PATH."
        echo "        Close this terminal, open a new one, and try again."
        exit 1
    fi
    echo "[setup] uv installed."
fi

# ============================================
#  Step 3: Remove existing venv
# ============================================
echo ""
echo "[3/6] Preparing venv directory..."

if [ -d "$VENV_DIR" ]; then
    echo "[setup] Removing existing venv..."
    rm -rf "$VENV_DIR" 2>/dev/null || true
    if [ -d "$VENV_DIR" ]; then
        echo "[WARN]  Failed to remove .venv directory."
        echo "        A process may be using it (e.g. Jupyter, Python)."
        echo "        Close all related processes and try again."
        exit 1
    fi
    echo "[setup] Old venv removed."
else
    echo "[setup] No existing venv. Clean start."
fi

# ============================================
#  Step 4: Create venv
# ============================================
echo ""
echo "[4/6] Creating virtual environment..."

if ! uv venv "$VENV_DIR"; then
    echo "[ERROR] Failed to create venv."
    echo "        Possible causes:"
    echo "          - No internet connection (uv may need to download Python)"
    echo "          - Disk full"
    exit 1
fi

# Verify activate script exists
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[ERROR] venv was created but activate script is missing."
    echo "        The venv may be corrupted. Delete .venv and try again."
    exit 1
fi

source "$VENV_DIR/bin/activate"
echo "[setup] venv activated."

# ============================================
#  Step 5: Install app dependencies
# ============================================
echo ""
echo "[5/6] Installing app dependencies..."

if [ ! -f "build/requirements.txt" ]; then
    echo "[ERROR] build/requirements.txt not found in $PROJECT_ROOT"
    echo "        Make sure this script is located in build/"
    exit 1
fi

if ! uv pip install -r build/requirements.txt; then
    echo "[ERROR] Failed to install dependencies from requirements.txt."
    echo "        Possible causes:"
    echo "          - No internet connection"
    echo "          - Package version conflict"
    echo "        Check the error messages above."
    exit 1
fi
echo "[setup] App dependencies installed."

# ============================================
#  Step 6: Install Jupyter packages (optional)
# ============================================
echo ""
echo "[6/6] Installing Jupyter packages (optional)..."

if ! uv pip install jupyter ipykernel scikit-learn; then
    echo "[WARN]  Jupyter packages failed to install."
    echo "        The app will still work. Jupyter notebooks will not be available."
else
    echo "[setup] Jupyter packages installed."

    # Register Jupyter kernel
    if command -v jupyter &> /dev/null; then
        KERNEL_NAME="$(basename "$PROJECT_ROOT")_kernel"
        echo "[setup] Registering kernel: $KERNEL_NAME"
        if python -m ipykernel install --user --name "$KERNEL_NAME" --display-name "Python ($VENV_DIR)" > /dev/null 2>&1; then
            echo "[setup] Kernel registered: $KERNEL_NAME"
        else
            echo "[WARN]  Kernel registration failed. You can register manually later:"
            echo "        python -m ipykernel install --user --name \"$KERNEL_NAME\""
        fi
    else
        echo "[WARN]  jupyter command not found after install."
        echo "        Kernel registration skipped."
    fi
fi

# ============================================
#  Done
# ============================================
echo ""
echo "============================================"
echo " Setup complete!"
echo " Activate : source $VENV_DIR/bin/activate"
echo " Run app  : streamlit run app.py"
echo " Jupyter  : jupyter notebook"
echo "============================================"
