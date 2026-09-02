# AI-Dev-Center core application image.
# Toolchains (ESPHome, PlatformIO, CMake) are NOT preinstalled.
# Verification reports TOOL_UNAVAILABLE; installation follows the
# SetupPlan–Human-Approval–Execution path, not verification.
FROM python:3.12-slim

RUN groupadd --system ai-dev && useradd --system --gid ai-dev --create-home ai-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "import fastapi, uvicorn, yaml"

COPY . .

RUN mkdir -p /data/workspace /app/.diagnostic-traces /app/.workflow-plans && \
    chown -R ai-dev:ai-dev /app /data

USER ai-dev

EXPOSE 8010

HEALTHCHECK --interval=15s --timeout=5s --retries=2 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8010/')" || exit 1

CMD ["python", "-m", "uvicorn", "app.web_api:app", "--host", "0.0.0.0", "--port", "8010"]