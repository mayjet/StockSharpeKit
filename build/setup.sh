#!/bin/zsh
# ローカル開発環境セットアップ（uv venv）
# 用途: Streamlit アプリ + Jupyter ノートブック
# Python: 3.11

PYTHON_VERSION="3.11"
VENV_DIR="./.venv"

# uv インストール確認
if ! command -v uv &> /dev/null; then
    echo "uv がインストールされていません。インストールします..."
    if ! command -v pipx &> /dev/null; then
        echo "pipx がインストールされていません。先にインストールしてください"
        echo "参考: https://pypa.github.io/pipx/installation/"
        exit 1
    fi
    pipx install uv
fi

# クリーン環境のため既存 .venv を削除
if [ -d "$VENV_DIR" ]; then
    echo "既存の仮想環境を削除します..."
    rm -rf "$VENV_DIR"
fi

# 仮想環境作成
uv venv --python "python$PYTHON_VERSION" "$VENV_DIR"

# アクティベート
source "$VENV_DIR/bin/activate"

# アプリ依存パッケージ（requirements.txt から）
uv pip install -r requirements.txt

# Jupyter 用追加パッケージ（ノートブックを使う場合）
uv pip install jupyter ipykernel scikit-learn

# Jupyter カーネル登録（オプション）
if command -v jupyter &> /dev/null; then
    KERNEL_NAME="${PWD##*/}_kernel"
    echo "カーネルを登録: $KERNEL_NAME"
    python -m ipykernel install --user --name "$KERNEL_NAME" --display-name "Python ($VENV_DIR)"
fi

echo ""
echo "✅ 環境構築完了"
echo "   アクティベート : source $VENV_DIR/bin/activate"
echo "   アプリ起動     : streamlit run app.py"
echo "   Jupyter 起動   : jupyter notebook"
