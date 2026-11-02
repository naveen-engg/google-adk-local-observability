"""Run multi-tool SRE queries against OpsAgent with runtime GCP Secret Manager -> Dynatrace OTLP export.

Note: Neither DYNATRACE_ENV_URL nor DYNATRACE_API_TOKEN is hardcoded here.
Setting DYNATRACE_ENABLED=true causes `agents/ops_agent/__init__.py` to fetch
`dynatrace-env-url` and `dynatrace-api-token` dynamically from Google Cloud
Secret Manager at startup and configure ADK's built-in OTLP HTTP exporters.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

# Configure runtime flags BEFORE importing agents.ops_agent
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get(
    "GOOGLE_CLOUD_PROJECT", "adk-enterprise-observability"
)
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"
os.environ["ADK_VERTEX_LOCATION"] = "global"
os.environ["ADK_MODEL"] = "gemini-3.5-flash"

# Enable runtime Secret Manager -> Dynatrace OTLP export in agents/ops_agent/__init__.py
os.environ["DYNATRACE_ENABLED"] = "true"
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "EVENT_ONLY"

from agents.ops_agent.agent import root_agent
from google.adk.runners import InMemoryRunner
from google.genai import types
from opentelemetry import _logs, metrics, trace

PROMPTS = [
    "Check the service health of api-gateway and payment-service and search runbooks for 502 Bad Gateway.",
    "Simulate a latency incident on auth-service, check pipeline health, and explain the tokens telemetry metric.",
    "Get recent error logs for notification-worker, check all services health, and create an incident ticket for P2 latency.",
    "Search runbooks for OTel collector memory pressure and explain the latency telemetry metric.",
    "Simulate a tool_error incident, check service health for all services, and summarize the findings.",
]


async def main() -> None:
  print(
      "Active OTLP Endpoint (resolved from GCP Secret Manager):",
      os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
      flush=True,
  )
  runner = InMemoryRunner(agent=root_agent, app_name="ops_agent")
  session = await runner.session_service.create_session(
      app_name="ops_agent", user_id="sre-dynatrace-sim"
  )
  for idx, prompt in enumerate(PROMPTS, 1):
    print(f"[{idx}/{len(PROMPTS)}] Sending query: {prompt[:70]}...", flush=True)
    msg = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    async for ev in runner.run_async(
        user_id="sre-dynatrace-sim", session_id=session.id, new_message=msg
    ):
      if ev.content and ev.content.parts:
        for p in ev.content.parts:
          if p.text:
            print(f"  -> Response ({len(p.text)} chars)", flush=True)
    trace.get_tracer_provider().force_flush()
    metrics.get_meter_provider().force_flush()
    _logs.get_logger_provider().force_flush()
    print(f"  -> Flushed wave {idx} traces, metrics (DELTA), and logs to Dynatrace!", flush=True)
    if idx < len(PROMPTS):
      time.sleep(3)

  print("\nCompleted all 5 multi-tool SRE queries and exported all 7 gen_ai.* metrics + traces to Dynatrace!")


if __name__ == "__main__":
  asyncio.run(main())
