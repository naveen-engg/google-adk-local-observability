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
  import os
  from google.adk.telemetry.setup import maybe_set_otel_providers

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


