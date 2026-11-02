"""OpsAgent package.

Initializes the OS certificate truststore before any model clients are loaded.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("ops_agent")

try:
  import truststore

  truststore.inject_into_ssl()
  logger.debug("Successfully injected OS certificate store into ssl via truststore.")
except ImportError:
  logger.debug("truststore library not found; proceeding with default ssl settings.")
except Exception as e:
  logger.warning("Could not inject truststore into ssl: %s", e)

# Explicitly initialize ADK OpenTelemetry providers (traces, metrics, and logs)
try:
  import base64
  import json
  import os
  import urllib.request
  from google.adk.telemetry.setup import maybe_set_otel_providers

  def _load_gcp_secret(project_id: str, secret_id: str, credentials) -> str | None:
    """Fetch the latest secret version from Google Cloud Secret Manager via REST."""
    from google.auth.transport.requests import Request as GoogleAuthRequest

    if not credentials.valid:
      credentials.refresh(GoogleAuthRequest())
    url = (
        f"https://secretmanager.googleapis.com/v1/projects/{project_id}"
        f"/secrets/{secret_id}/versions/latest:access"
    )
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {credentials.token}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
      payload = json.loads(resp.read().decode("utf-8"))
      encoded = payload.get("payload", {}).get("data", "")
      return base64.b64decode(encoded).decode("utf-8").strip() if encoded else None

  otel_hooks = []
  otel_resource = None
  telemetry_enabled = os.environ.get(
      "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY",
      os.environ.get("AGENT_ENGINE_TELEMETRY", ""),
  ).lower() in ("true", "1", "yes")

  if telemetry_enabled:
    import google.auth
    from google.adk.telemetry.google_cloud import (
        _CLOUD_PLATFORM_SCOPE,
        get_gcp_exporters,
        get_gcp_resource,
    )

    credentials, project_id = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or project_id
    region = (
        os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or "us-central1"
    )
    existing_res_attrs = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    if "cloud.region=" not in existing_res_attrs:
      sep = "," if existing_res_attrs else ""
      os.environ["OTEL_RESOURCE_ATTRIBUTES"] = (
          f"{existing_res_attrs}{sep}cloud.region={region}"
      )

    otel_hooks.append(
        get_gcp_exporters(
            enable_cloud_tracing=True,
            enable_cloud_metrics=True,
            enable_cloud_logging=True,
            google_auth=(credentials, project_id),
        )
    )
    otel_resource = get_gcp_resource(project_id)

  # Optional runtime Dynatrace OTLP configuration via GCP Secret Manager
  # Configured after get_gcp_exporters() so GCP keeps CUMULATIVE temporality
  # while _get_otel_exporters() in maybe_set_otel_providers() uses DELTA for Dynatrace.
  dynatrace_enabled = os.environ.get("DYNATRACE_ENABLED", "").lower() in (
      "true",
      "1",
      "yes",
  )
  if dynatrace_enabled:
    import google.auth

    dt_creds, default_proj = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    dt_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or default_proj
    dt_url_secret = os.environ.get("DYNATRACE_URL_SECRET_NAME", "dynatrace-env-url")
    dt_token_secret = os.environ.get(
        "DYNATRACE_TOKEN_SECRET_NAME", "dynatrace-api-token"
    )
    dt_url = os.environ.get("DYNATRACE_ENV_URL") or _load_gcp_secret(
        dt_project, dt_url_secret, dt_creds
    )
    dt_token = os.environ.get("DYNATRACE_API_TOKEN") or _load_gcp_secret(
        dt_project, dt_token_secret, dt_creds
    )
    if dt_url and dt_token:
      clean_url = dt_url.rstrip("/").replace(
          ".apps.dynatrace.com", ".live.dynatrace.com"
      )
      if not clean_url.endswith("/api/v2/otlp"):
        clean_url = f"{clean_url}/api/v2/otlp"
      os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = clean_url
      os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Api-Token {dt_token}"
      os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
      os.environ["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] = "delta"
      os.environ.setdefault("OTEL_SERVICE_NAME", "adk-ops-agent")
      logger.debug("Configured Dynatrace OTLP endpoint from GCP Secret Manager: %s", clean_url)

  maybe_set_otel_providers(
      otel_hooks_to_setup=otel_hooks,
      otel_resource=otel_resource,
  )
  logger.debug("Successfully initialized ADK OpenTelemetry providers.")
except Exception as e:
  logger.debug("Could not initialize ADK OpenTelemetry providers: %s", e)

# Automatically instrument Google GenAI SDK for client token and duration metrics
try:
  from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor

  GoogleGenAiSdkInstrumentor().instrument()
  logger.debug("Successfully instrumented Google GenAI SDK.")
except Exception as e:
  logger.debug("Could not instrument Google GenAI SDK: %s", e)


