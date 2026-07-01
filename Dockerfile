FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY aab_framework /app/aab_framework
COPY bin /app/bin
COPY docs /app/docs

RUN pip install --no-cache-dir -e .

ENV AAB_UI_HOST=0.0.0.0
ENV AAB_UI_PORT=8080
ENV AAB_UI_FALLBACK_PORT=8080

EXPOSE 8080

CMD ["python3", "-m", "aab_framework.dashboard", "--project-root", "/app", "--host", "0.0.0.0", "--port", "8080", "--fallback-port", "8080"]
