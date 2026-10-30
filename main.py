"""Interactive terminal runner for OpsAgent (SRE & Observability Copilot).

Loads environment variables from .env, explicitly initializes ADK OpenTelemetry
telemetry export, creates an in-memory session, and executes a terminal chat loop.
Flushes and shuts down telemetry providers cleanly on exit.
"""

from __future__ import annotations

import atexit
import asyncio
import logging
import os
import sys

# Ensure ops_agent package is imported first so truststore is injected
import agents.ops_agent  # noqa: F401
from dotenv import load_dotenv

# Load local environment settings before configuring telemetry
load_dotenv()

# Configure minimal console logging for the terminal runner
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s]: %(message)s",
)
logger = logging.getLogger("main")

# Explicitly initialize ADK OpenTelemetry providers
try:
  from google.adk.telemetry.setup import maybe_set_otel_providers

  maybe_set_otel_providers()
except Exception as e:
  logger.warning("Failed to initialize ADK OpenTelemetry providers: %s", e)


def shutdown_telemetry() -> None:
  """Shuts down and flushes OpenTelemetry tracer and meter providers."""
  try:
    from opentelemetry import metrics, trace

    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
      tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
      meter_provider.shutdown()
  except Exception as e:
    logger.debug("Error shutting down telemetry providers: %s", e)


# Register clean telemetry shutdown on process exit
atexit.register(shutdown_telemetry)


def main() -> None:
  """Main entry point for interactive terminal chat."""
  from google.adk.runners import InMemoryRunner
  from google.genai import types
  from agents.ops_agent.agent import OpsAgent

  user_id = "local_user"
  app_name = "adk-otel"

  # Initialize runner with in-memory services
  runner = InMemoryRunner(agent=OpsAgent, app_name=app_name)

  # Create an in-memory session
  session = asyncio.run(
      runner.session_service.create_session(user_id=user_id, app_name=app_name)
  )

  model_display = os.environ.get("ADK_MODEL", "gemini-2.5-flash")
  print("=" * 68)
  print(f" OpsAgent Terminal Chat (ADK Observability Demo)")
  print(f" Role: SRE & Observability Copilot")
  print(f" Model: {model_display}")
  print(f" Telemetry Target: {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://127.0.0.1:4318')}")
  print(" Available Tools: health check, metrics explain, PromQL query, incident simulation")
  print(" Type 'exit' or 'quit' to end session.")
  print("=" * 68)

  while True:
    try:
      user_input = input("\nYou: ").strip()
    except (KeyboardInterrupt, EOFError):
      print("\nSession ended by user.")
      break

    if not user_input:
      continue

    if user_input.lower() in ("exit", "quit", "q", ":q"):
      print("Exiting OpsAgent. Telemetry flushed. Goodbye!")
      break

    content = types.Content(parts=[types.Part(text=user_input)])

    final_response_text = ""
    try:
      for event in runner.run(
          user_id=user_id,
          session_id=session.id,
          new_message=content,
      ):
        # Accumulate only text parts for the final agent response
        if event.content and event.content.parts:
          for part in event.content.parts:
            if hasattr(part, "text") and part.text:
              final_response_text += part.text

      if final_response_text:
        print(f"\nOpsAgent: {final_response_text.strip()}")
      else:
        print("\nOpsAgent: (No text response returned)")
    except Exception as err:
      print(f"\n[Error executing request]: {err}")
      logger.exception("Agent execution exception")


if __name__ == "__main__":
  main()
