FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt

# Non-root runtime user (defense-in-depth; UID 1000), created after the dep layers so the
# cached pip install is preserved. PYTHONDONTWRITEBYTECODE keeps a non-root uid from trying
# to write __pycache__ under the dev `.:/app` bind-mount.
RUN useradd --create-home --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1

COPY . .

# App dir owned by the non-root user. Matters for prod/offline (image-only /app); the dev
# `.:/app` bind-mount overlays host ownership instead, covered by PYTHONDONTWRITEBYTECODE.
RUN chown -R appuser:appuser /app

# Commit-binding for the offline bundle: the built image records the exact source
# commit so install-offline.sh can assert image == repo-snapshot == manifest and
# close the "bind-mounted code vs. baked image" gap. Defaults to "unknown" for
# ordinary (non-bundle) builds that do not pass --build-arg GIT_COMMIT.
ARG GIT_COMMIT=unknown
LABEL org.tess.commit=$GIT_COMMIT

EXPOSE 8000

# Drop root for the runtime (covers web, web-standby, worker — same image, USER applies to
# every compose `command:` override). uvicorn :8000 and worker metrics :9109 are >1024.
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
