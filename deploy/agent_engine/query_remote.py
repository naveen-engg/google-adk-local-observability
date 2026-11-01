"""Query a deployed OpsAgent instance on Vertex AI Agent Engine (Reasoning Engine)."""

from __future__ import annotations

import argparse
import os
import vertexai
from vertexai import agent_engines

DEFAULT_PROJECT_ID = os.environ.get(
    "GOOGLE_CLOUD_PROJECT", "adk-enterprise-observability"
)
DEFAULT_LOCATION = os.environ.get(
    "GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "us-central1"
)


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Query remote OpsAgent on Vertex AI Agent Engine"
  )
  parser.add_argument(
      "--resource-name",
      help="Full ReasoningEngine resource name (if omitted, uses the latest deployed engine)",
  )
  parser.add_argument("--project", default=DEFAULT_PROJECT_ID)
  parser.add_argument("--location", default=DEFAULT_LOCATION)
  parser.add_argument(
      "--prompt",
      default=(
          "Hi, I am Naveen! Simulate a latency incident, check pipeline health, "
          "and explain the latency telemetry metric."
      ),
  )
  args = parser.parse_args()

  vertexai.init(project=args.project, location=args.location)

  resource_name = args.resource_name
  if not resource_name:
    engines = list(agent_engines.list())
    if not engines:
      raise RuntimeError("No deployed AgentEngine instances found.")
    resource_name = engines[0].resource_name

  print(f"Connecting to remote Agent Engine: {resource_name}")
  remote_agent = agent_engines.get(resource_name)

  session = remote_agent.create_session(user_id="sre-oncall-user")
  session_id = session["id"] if isinstance(session, dict) else session.id
  print(f"Created remote session: {session_id}")
  print(f"Prompt: {args.prompt}\n")

  response_text = ""
  for event in remote_agent.stream_query(
      user_id="sre-oncall-user",
      session_id=session_id,
      message=args.prompt,
  ):
    if isinstance(event, dict) and "errorMessage" in event:
      print(f"[Remote Error]: {event}")
    content = event.get("content") if isinstance(event, dict) else None
    if content and "parts" in content:
      for part in content["parts"]:
        if "text" in part:
          response_text += part["text"]

  print("Remote OpsAgent Response:")
  print(f"  {response_text.strip()}")


if __name__ == "__main__":
  main()
