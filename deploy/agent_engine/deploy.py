"""Deploy OpsAgent to Google Cloud Vertex AI Agent Engine (Reasoning Engine).

Wraps OpsAgent in vertexai.preview.reasoning_engines.AdkApp with native
Google Cloud Trace enabled (`enable_tracing=True`), performs a pre-deployment
smoke test, and deploys to Vertex AI Agent Engine.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PROJECT_ID = os.environ.get(
    "GOOGLE_CLOUD_PROJECT", "adk-enterprise-observability"
)
DEFAULT_LOCATION = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "us-central1")
DEFAULT_MODEL = os.environ.get("ADK_VERTEX_MODEL", "gemini-3.5-flash")
DEFAULT_STAGING_BUCKET = os.environ.get(
    "STAGING_BUCKET", f"gs://{DEFAULT_PROJECT_ID}-staging"
)
DEFAULT_SERVICE_ACCOUNT = os.environ.get(
    "AGENT_ENGINE_SA",
    f"adk-agent-engine-sa@{DEFAULT_PROJECT_ID}.iam.gserviceaccount.com",
)

# Set Vertex AI global model routing before importing OpsAgent
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = DEFAULT_PROJECT_ID
os.environ["ADK_VERTEX_LOCATION"] = "global"
os.environ["ADK_MODEL"] = DEFAULT_MODEL

import vertexai
from vertexai import agent_engines
from agents.ops_agent.agent import root_agent


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Deploy OpsAgent to Vertex AI Agent Engine (Reasoning Engine)"
  )
  parser.add_argument("--project", default=DEFAULT_PROJECT_ID)
  parser.add_argument("--location", default=DEFAULT_LOCATION)
  parser.add_argument("--staging-bucket", default=DEFAULT_STAGING_BUCKET)
  parser.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT)
  parser.add_argument(
      "--smoke-test-only",
      action="store_true",
      help="Run local AdkApp smoke test with Vertex AI without deploying container",
  )
  parser.add_argument(
      "--skip-smoke-test",
      action="store_true",
      help="Skip local smoke test and deploy directly to Vertex AI Agent Engine",
  )
  parser.add_argument(
      "--update",
      help="Update an existing AgentEngine resource name in place instead of creating a new one",
  )
  parser.add_argument(
      "--delete",
      action="store_true",
      help="Delete all deployed AgentEngine instances in the project/region to stop billing",
  )
  args = parser.parse_args()

  # Force Vertex AI backend with global Gemini endpoint while hosting Agent Engine in args.location
  os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
  os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
  os.environ["ADK_VERTEX_LOCATION"] = "global"
  os.environ["GOOGLE_CLOUD_AGENT_ENGINE_LOCATION"] = args.location

  print("=" * 72)
  print(" Vertex AI Agent Engine Deployment (OpsAgent SRE Copilot)")
  print(f" Project ID     : {args.project}")
  print(f" Engine Region  : {args.location}")
  print(f" Gemini Model   : {DEFAULT_MODEL} (global endpoint)")
  print(f" Staging Bucket : {args.staging_bucket}")
  print(f" Service Account: {args.service_account}")
  print("=" * 72)

  vertexai.init(
      project=args.project,
      location=args.location,
      staging_bucket=args.staging_bucket,
  )

  if args.delete:
    for engine in agent_engines.list():
      print(f"Deleting AgentEngine: {engine.resource_name} ...")
      agent_engines.delete(engine.resource_name, force=True)
    print("All AgentEngine instances deleted.")
    return

  # Wrap OpsAgent in AdkApp with Cloud Trace telemetry enabled
  adk_app = agent_engines.AdkApp(
      agent=root_agent,
      enable_tracing=True,
  )

  if not args.skip_smoke_test:
    print("\n[1/2] Running Local AdkApp Pre-Deployment Smoke Test (via Vertex AI)...")
    session = adk_app.create_session(user_id="sre-smoke-test")
    response_text = ""
    for event in adk_app.stream_query(
        user_id="sre-smoke-test",
        session_id=session.id,
        message="Hi, I am Naveen! Explain the tokens telemetry metric.",
    ):
      content = event.get("content") if isinstance(event, dict) else None
      if content and "parts" in content:
        for part in content["parts"]:
          if "text" in part:
            response_text += part["text"]
    print(f"Smoke Test Response:\n  {response_text.strip()}\n")

  if args.smoke_test_only:
    print("Smoke test succeeded (--smoke-test-only specified). Skipping remote deployment.")
    return

  import importlib.metadata as metadata

  adk_ver = metadata.version("google-adk")
  genai_ver = metadata.version("google-genai")
  aiplatform_ver = metadata.version("google-cloud-aiplatform")

  common_kwargs = dict(
      agent_engine=adk_app,
      requirements=[
          f"google-adk=={adk_ver}",
          f"google-genai=={genai_ver}",
          f"google-cloud-aiplatform[adk,agent_engines]=={aiplatform_ver}",
          "opentelemetry-sdk>=1.28.0",
          "opentelemetry-exporter-gcp-trace>=1.7.0",
          "opentelemetry-instrumentation-google-genai",
          "truststore>=0.10.0",
      ],
      extra_packages=[
          "./agents",
      ],
      env_vars={
          "ADK_VERTEX_LOCATION": "global",
          "ADK_MODEL": DEFAULT_MODEL,
          "OTEL_SERVICE_NAME": "adk-ops-agent",
          "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
      },
      service_account=args.service_account,
      display_name="ops-agent-sre-copilot",
      description=(
          "OpsAgent: Google ADK SRE & Observability Copilot with OpenTelemetry Cloud Trace"
      ),
  )

  if args.update:
    print(f"[2/2] Updating existing Vertex AI Agent Engine ({args.update})...")
    remote_agent = agent_engines.update(
        resource_name=args.update,
        **common_kwargs,
    )
  else:
    print("[2/2] Deploying OpsAgent to Vertex AI Agent Engine (this takes ~3-5 minutes)...")
    remote_agent = agent_engines.create(**common_kwargs)

  print("\n" + "=" * 72)
  print(" DEPLOYMENT COMPLETE!")
  print(f" Resource Name: {remote_agent.resource_name}")
  print("=" * 72)


if __name__ == "__main__":
  main()
