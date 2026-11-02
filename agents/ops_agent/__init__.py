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
  if os.environ.get("AGENT_ENGINE_TELEMETRY", "").lower() in ("true", "1", "yes"):
    from google.adk.telemetry.google_cloud import get_gcp_exporters

    otel_hooks.append(
        get_gcp_exporters(
            enable_cloud_tracing=True,
            enable_cloud_metrics=True,
            enable_cloud_logging=True,
        )
    )

  maybe_set_otel_providers(otel_hooks_to_setup=otel_hooks)
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


