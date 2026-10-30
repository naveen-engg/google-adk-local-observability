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
  from google.adk.telemetry.setup import maybe_set_otel_providers

  maybe_set_otel_providers()
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


