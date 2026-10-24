# =============================================================================
# Single image that runs BOTH the Flask API (gunicorn) and the Streamlit UI.
# Processes are supervised by supervisord so one container = one ECS task.
#   - Flask API   -> 0.0.0.0:5000
#   - Streamlit UI -> 0.0.0.0:8501
# =============================================================================

# --- Build stage: install all Python deps into a clean prefix ----------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Combine backend + frontend requirements so everything lands in one image.
COPY requirements.txt ./requirements.txt
COPY frontend/requirements.txt ./frontend-requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install -r frontend-requirements.txt

# --- Runtime stage -----------------------------------------------------------
FROM python:3.12-slim

# supervisord manages the two long-running processes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy installed Python packages + console scripts from the build stage.
COPY --from=builder /install /usr/local

# Application source.
COPY app.py ./app.py
COPY frontend/streamlit_app.py ./streamlit_app.py

# Supervisor + entrypoint config.
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Streamlit needs a writable home/config dir for the non-root user.
RUN mkdir -p /app/.streamlit /var/log/supervisor \
    && chown -R appuser:appgroup /app /var/log/supervisor
ENV HOME=/app

# The frontend talks to the API inside the same container.
ENV API_BASE_URL=http://localhost:5000

USER appuser

EXPOSE 5000 8501

# Health check targets the Flask API (the backend the UI depends on).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
