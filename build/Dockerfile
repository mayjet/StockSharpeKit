FROM python:3.11-slim

WORKDIR /app

# uv インストール
RUN pip install --no-cache-dir uv

# 依存パッケージ（キャッシュ活用のため先にコピー）
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# アプリ本体をコピー
COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]
