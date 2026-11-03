"""Simulate multi-tool SRE traffic against the Cloud Run ADK Agent service.

Traffic flow:
    Client -> Cloud Run ADK Agent (Port 8000)
           -> OTLP HTTP (localhost:4318)
           -> OTel Collector Sidecar
           -> Dynatrace (/api/v2/otlp)
"""

from __future__ import annotations

import json
import time
import urllib.request

BASE_URL = "https://adk-ops-agent-981754278786.us-central1.run.app"
APP_NAME = "ops_agent"
USER_ID = "cloudrun-dynatrace-sim"

PROMPTS = [
    (
        "Check the service health of api-gateway and payment-service and"
        " search runbooks for 502 Bad Gateway."
    ),
    (
        "Simulate a latency incident on auth-service, check pipeline health,"
        " and explain the tokens telemetry metric."
    ),
    (
        "Get recent error logs for notification-worker, check all services"
        " health, and explain latency."
    ),
    (
        "Search runbooks for OTel collector memory pressure and explain the"
        " spans telemetry metric."
    ),
    (
        "Simulate a tool_error incident, check service health for all services,"
        " and summarize the findings."
    ),
]


def create_session() -> str:
  url = f"{BASE_URL}/apps/{APP_NAME}/users/{USER_ID}/sessions"
  req = urllib.request.Request(
      url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
  )
  with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    return data["id"]


def run_query(session_id: str, prompt: str) -> str:
  url = f"{BASE_URL}/run"
  body = json.dumps({
      "appName": APP_NAME,
      "userId": USER_ID,
      "sessionId": session_id,
      "newMessage": {
          "role": "user",
          "parts": [{"text": prompt}],
      },
  }).encode("utf-8")
  req = urllib.request.Request(
      url,
      data=body,
      headers={"Content-Type": "application/json"},
      method="POST",
  )
  with urllib.request.urlopen(req, timeout=30) as resp:
    events = json.loads(resp.read().decode("utf-8"))
    response_text = ""
    for ev in events:
      content = ev.get("content")
      if content and "parts" in content:
        for p in content["parts"]:
          if "text" in p and p["text"]:
            response_text += p["text"]
    return response_text


def main() -> None:
  print(f"Connecting to Cloud Run service: {BASE_URL}")
  sid = create_session()
  print(f"Created remote session: {sid}\n")

  for idx, p in enumerate(PROMPTS, 1):
    print(f"[{idx}/{len(PROMPTS)}] Prompt: {p[:65]}...", flush=True)
    ans = run_query(sid, p)
    print(f"  -> Agent reply ({len(ans)} chars): {ans[:100]}...\n", flush=True)
    if idx < len(PROMPTS):
      time.sleep(5)

  print(
      "Completed 5 multi-tool SRE queries on Cloud Run! All traces and metrics"
      " exported via OTel sidecar to Dynatrace."
  )


if __name__ == "__main__":
  main()
