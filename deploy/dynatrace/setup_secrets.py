"""Store Dynatrace Environment URL and API Token in Google Cloud Secret Manager.

Usage:
    py -3.13 deploy/dynatrace/setup_secrets.py \
        --project adk-enterprise-observability \
        --url "https://<env-id>.live.dynatrace.com" \
        --token "dt0c01...."
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
import google.auth
from google.auth.transport.requests import Request


def upsert_secret(project_id: str, secret_id: str, secret_value: str, token: str) -> None:
  """Create secret if it does not exist, then add a new secret version."""
  base_url = f"https://secretmanager.googleapis.com/v1/projects/{project_id}/secrets"
  headers = {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
  }

  # 1. Create secret container if needed
  create_body = json.dumps({"replication": {"automatic": {}}}).encode("utf-8")
  req = urllib.request.Request(
      f"{base_url}?secretId={secret_id}",
      data=create_body,
      headers=headers,
      method="POST",
  )
  try:
    urllib.request.urlopen(req, timeout=15)
    print(f"[+] Created secret container: projects/{project_id}/secrets/{secret_id}")
  except urllib.error.HTTPError as e:
    if e.code == 409:
      print(f"[=] Secret container already exists: projects/{project_id}/secrets/{secret_id}")
    else:
      raise RuntimeError(f"Failed creating secret {secret_id}: {e.read().decode()}") from e

  # 2. Add new secret version
  b64_val = base64.b64encode(secret_value.strip().encode("utf-8")).decode("ascii")
  ver_body = json.dumps({"payload": {"data": b64_val}}).encode("utf-8")
  ver_req = urllib.request.Request(
      f"{base_url}/{secret_id}:addVersion",
      data=ver_body,
      headers=headers,
      method="POST",
  )
  with urllib.request.urlopen(ver_req, timeout=15) as resp:
    res = json.loads(resp.read().decode("utf-8"))
    print(f"[+] Added secret version: {res['name']}")


def main() -> None:
  parser = argparse.ArgumentParser(description="Store Dynatrace URL and API token in GCP Secret Manager.")
  parser.add_argument(
      "--project",
      default=os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-enterprise-observability"),
      help="GCP Project ID",
  )
  parser.add_argument("--url", required=True, help="Dynatrace Environment URL (e.g. https://abc12345.live.dynatrace.com)")
  parser.add_argument("--token", required=True, help="Dynatrace Access / API Token (dt0c01...)")
  parser.add_argument("--url-secret-name", default="dynatrace-env-url", help="Secret name for Dynatrace URL")
  parser.add_argument("--token-secret-name", default="dynatrace-api-token", help="Secret name for Dynatrace API Token")
  args = parser.parse_args()

  creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  creds.refresh(Request())

  upsert_secret(args.project, args.url_secret_name, args.url, creds.token)
  upsert_secret(args.project, args.token_secret_name, args.token, creds.token)
  print("\nSuccessfully stored Dynatrace credentials in Google Cloud Secret Manager!")


if __name__ == "__main__":
  main()
