"""ADK Server entrypoint for Cloud Run container."""

import os
import uvicorn
from google.adk.cli.fast_api import get_fast_api_app

# Ensure agents package initializes OS truststore and OpenTelemetry
import agents.ops_agent

app = get_fast_api_app(
    agents_dir="agents",
    web=True,
    allow_origins=["*"],
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
)

if __name__ == "__main__":
  port = int(os.environ.get("PORT", 8000))
  uvicorn.run(app, host="0.0.0.0", port=port)
