FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Commit-binding for the offline bundle: the built image records the exact source
# commit so install-offline.sh can assert image == repo-snapshot == manifest and
# close the "bind-mounted code vs. baked image" gap. Defaults to "unknown" for
# ordinary (non-bundle) builds that do not pass --build-arg GIT_COMMIT.
ARG GIT_COMMIT=unknown
LABEL org.tess.commit=$GIT_COMMIT

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
