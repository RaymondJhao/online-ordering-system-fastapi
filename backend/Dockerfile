# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# 多階段建置：builder 安裝相依套件，runtime 只帶走裝好的環境。
# 好處是最終映像不含編譯工具鏈，體積更小、攻擊面也更小。
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先只複製相依定義：只要 pyproject.toml 沒變，這一層的快取就能重用，
# 改程式碼時不必重裝所有套件。
COPY pyproject.toml ./
COPY app/__init__.py ./app/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && pip install .

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# 不以 root 執行：容器內若有漏洞被利用，非特權使用者能造成的損害小得多
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# 以 uvicorn 直接啟動。舊版是 `gunicorn run:app`（WSGI），
# ASGI 應用必須改用 uvicorn，或 gunicorn 搭配 UvicornWorker。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
