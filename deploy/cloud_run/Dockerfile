FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    GOOGLE_GENAI_USE_VERTEXAI="1" \
    GOOGLE_CLOUD_PROJECT="adk-enterprise-observability" \
    GOOGLE_CLOUD_LOCATION="global" \
    ADK_VERTEX_LOCATION="global" \
    ADK_MODEL="gemini-3.5-flash" \
    OTEL_SERVICE_NAME="adk-ops-agent" \
    OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf" \
    OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318" \
    OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta" \
    OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental" \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY" \
    OTEL_METRIC_EXPORT_INTERVAL="3000"

RUN pip install --no-cache-dir \
    "google-adk[otel]==2.13.0" \
    "google-genai>=2.34.0" \
    "opentelemetry-sdk>=1.39.0" \
    "opentelemetry-exporter-otlp-proto-http>=1.39.0" \
    "opentelemetry-instrumentation-google-genai>=0.7b0" \
    "truststore>=0.10.0"

COPY agents ./agents
COPY deploy/cloud_run/server.py ./server.py

EXPOSE 8000

CMD ["python", "server.py"]
