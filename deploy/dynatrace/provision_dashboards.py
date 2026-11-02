"""Provision ADK GenAI Metrics and Distributed Traces Dashboards in Dynatrace.

Fetches the Dynatrace Environment URL and API Token at runtime from Google Cloud
Secret Manager (`dynatrace-env-url` and `dynatrace-api-token`) and creates or
updates the two ADK dashboards via the Dynatrace Configuration API
(`/api/config/v1/dashboards`).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import google.auth
from google.auth.transport.requests import Request


def read_gcp_secret(project_id: str, secret_id: str, token: str) -> str:
  url = (
      f"https://secretmanager.googleapis.com/v1/projects/{project_id}"
      f"/secrets/{secret_id}/versions/latest:access"
  )
  req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
  with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    return base64.b64decode(data["payload"]["data"]).decode("utf-8").strip()


def normalize_dt_api_base(dt_url: str) -> str:
  """Convert .apps.dynatrace.com or /api/v2/otlp URLs to the base .live.dynatrace.com URL."""
  base = dt_url.strip().rstrip("/")
  if base.endswith("/api/v2/otlp"):
    base = base[: -len("/api/v2/otlp")]
  base = base.replace(".apps.dynatrace.com", ".live.dynatrace.com")
  return base


def deploy_dashboard(dt_base_url: str, dt_token: str, dashboard_file: Path) -> dict:
  payload = json.loads(dashboard_file.read_text(encoding="utf-8"))
  payload.pop("id", None)
  api_url = f"{dt_base_url}/api/config/v1/dashboards"
  req = urllib.request.Request(
      api_url,
      data=json.dumps(payload).encode("utf-8"),
      headers={
          "Authorization": f"Api-Token {dt_token}",
          "Content-Type": "application/json; charset=utf-8",
      },
      method="POST",
  )
  try:
    with urllib.request.urlopen(req, timeout=20) as resp:
      return json.loads(resp.read().decode("utf-8"))
  except urllib.error.HTTPError as e:
    err_body = e.read().decode("utf-8", errors="replace")
    raise RuntimeError(
        f"Dynatrace API HTTP {e.code} for {dashboard_file.name}: {err_body}"
    ) from e


def main() -> None:
  parser = argparse.ArgumentParser(description="Provision ADK Dashboards in Dynatrace using GCP Secret Manager.")
  parser.add_argument(
      "--project",
      default=os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-enterprise-observability"),
      help="GCP Project ID hosting Secret Manager secrets",
  )
  parser.add_argument("--url-secret-name", default="dynatrace-env-url")
  parser.add_argument("--token-secret-name", default="dynatrace-api-token")
  args = parser.parse_args()

  creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  creds.refresh(Request())

  dt_url = read_gcp_secret(args.project, args.url_secret_name, creds.token)
  dt_token = read_gcp_secret(args.project, args.token_secret_name, creds.token)
  dt_base = normalize_dt_api_base(dt_url)

  dash_dir = Path(__file__).resolve().parent / "dashboards"
  files = [
      dash_dir / "adk-genai-metrics-dynatrace-dashboard.json",
      dash_dir / "adk-traces-logs-dynatrace-dashboard.json",
  ]

  print(f"Target Dynatrace Environment: {dt_base}")
  for f in files:
    res = deploy_dashboard(dt_base, dt_token, f)
    dash_id = res.get("id")
    print(f"[+] Deployed {f.name} -> ID: {dash_id}")
    print(f"    URL: {dt_base}/#dashboard;id={dash_id}")


if __name__ == "__main__":
  main()
