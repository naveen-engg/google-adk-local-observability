# Option 1: Deploying `OpsAgent` to Vertex AI Agent Engine (Reasoning Engine)

**Vertex AI Agent Engine** (formerly **Vertex AI Reasoning Engine**) is Google Cloud's fully managed runtime for **Google Agent Development Kit (ADK)** agents. It provides serverless execution, managed conversation session history (`VertexAiSessionService`), and built-in **Google Cloud Trace** integration without managing Docker containers or Kubernetes clusters.

---

## Architecture Overview

```mermaid
flowchart LR
    Client["Client App / CLI / Slack Bot"] -->|Vertex AI SDK\nIAM Auth| AE["Vertex AI Agent Engine\n(AdkApp wrapping OpsAgent)"]
    
    subgraph Runtime["Managed Agent Engine Container"]
        AE --> Root["OpsAgent (gemini-2.5-flash)"]
        Root --> Tools["SRE Diagnostic Tools\n(check_service_health,\nget_error_logs, etc.)"]
        Root --> OTel["OpenTelemetry SDK\n(enable_tracing=True +\nCloudMonitoringMetricsExporter)"]
    end

    OTel -->|Spans: invoke_agent,\ncall_llm, execute_tool| CT["Google Cloud Trace"]
    OTel -->|Metrics: gen_ai.client.token.usage,\ngen_ai.client.operation.duration| CM["Google Cloud Monitoring\n& Managed Prometheus"]
    Runtime -->|Correlated JSON Logs| CL["Google Cloud Logging"]
    CL -->|Log Sink| BQ["BigQuery\n(Token Cost & Audit Analytics)"]
```

---

## 1. Required GCP APIs to Enable

Run the following `gcloud` commands to enable all APIs required for Vertex AI Agent Engine and its OpenTelemetry observability stack:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export STAGING_BUCKET="gs://${PROJECT_ID}-adk-staging"

gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  aiplatform.googleapis.com \
  storage.googleapis.com \
  cloudtrace.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com
```

### Why Each API is Required
| API | Service Name | Purpose |
| :--- | :--- | :--- |
| **Vertex AI API** | `aiplatform.googleapis.com` | Hosts the Reasoning Engine / Agent Engine runtime and provides access to `gemini-2.5-flash` |
| **Cloud Storage API** | `storage.googleapis.com` | Stages the serialized `AdkApp` bundle and local Python packages (`agents/`, `observability/`) |
| **Cloud Trace API** | `cloudtrace.googleapis.com` | Ingests OpenTelemetry distributed trace spans (`invoke_agent`, `call_llm`, `execute_tool`) |
| **Cloud Monitoring API** | `monitoring.googleapis.com` | Ingests `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` metrics |
| **Cloud Logging API** | `logging.googleapis.com` | Collects structured agent logs correlated with Cloud Trace span IDs |

---

## 2. Create Staging Bucket & Configure IAM Permissions

### 2.1 Create the GCS Staging Bucket
Vertex AI Agent Engine requires a Regional Cloud Storage bucket in the same region (`us-central1`) to upload your agent code during deployment:

```bash
gcloud storage buckets create "${STAGING_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

### 2.2 Grant Telemetry & Vertex AI Permissions to the Reasoning Engine Service Agent
By default, Vertex AI Reasoning Engine executes under the **AI Platform Reasoning Engine Service Agent** (`service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`) or a custom Service Account you specify:

```bash
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
RE_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

# Grant permissions to invoke Gemini models, write traces, metrics, and logs
for ROLE in \
  roles/aiplatform.user \
  roles/cloudtrace.agent \
  roles/monitoring.metricWriter \
  roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RE_SA}" \
    --role="${ROLE}"
done
```

---

## 3. Step-by-Step Implementation

### Step 3.1: Install Vertex AI Agent Engine & ADK OpenTelemetry Dependencies
In your virtual environment, install `google-adk[otel]>=2.13.0` along with the Vertex AI Agent Engine SDK and OTLP HTTP exporter:

```bash
pip install \
  "google-adk[otel]>=2.13.0" \
  "google-cloud-aiplatform[adk,agent_engines]>=2.7.0" \
  "opentelemetry-exporter-otlp-proto-http>=1.39.0" \
  "opentelemetry-instrumentation-google-genai>=0.7b0"
```

### Step 3.2: Enable ADK Built-In Agent Engine Telemetry (`prometheus.googleapis.com/gen_ai.*/histogram`)
With `google-adk[otel]>=2.13.0`, ADK's built-in `google.adk.telemetry` (`get_gcp_exporters` + `get_gcp_resource`) pushes OpenTelemetry histograms over OTLP HTTP to Google Cloud Telemetry API (`https://telemetry.googleapis.com/v1/metrics`), which automatically populates **all 7 `prometheus.googleapis.com/gen_ai.*/histogram` metrics** in Google Cloud Managed Service for Prometheus (GMP) with zero custom metric code in `agent.py`:

1. `prometheus.googleapis.com/gen_ai.client.operation.duration/histogram`
2. `prometheus.googleapis.com/gen_ai.client.token.usage/histogram`
3. `prometheus.googleapis.com/gen_ai.execute_tool.duration/histogram`
4. `prometheus.googleapis.com/gen_ai.invoke_agent.duration/histogram`
5. `prometheus.googleapis.com/gen_ai.invoke_agent.inference_calls/histogram`
6. `prometheus.googleapis.com/gen_ai.invoke_agent.tool_calls/histogram`
7. `prometheus.googleapis.com/gen_ai.invoke_workflow.duration/histogram`

Configure the standard Agent Engine telemetry environment variables:
```bash
# Same telemetry settings the ADK team uses on Agent Engine
GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true
ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN=1
OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY
```
> **Note on `gen_ai.invoke_workflow.duration`:** When running an `LlmAgent` directly (without an outer `Workflow` wrapper), leaving `ADK_TELEMETRY_SCHEMA_VERSION_OPT_IN` at its default (`2`) emits all 7 metrics including `gen_ai.invoke_workflow.duration/histogram` on every invocation.

In [`agents/ops_agent/__init__.py`](../../agents/ops_agent/__init__.py), ADK's built-in telemetry providers are initialized automatically when `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`:

```python
import os
import google.auth
from google.adk.telemetry.setup import maybe_set_otel_providers
from google.adk.telemetry.google_cloud import (
    _CLOUD_PLATFORM_SCOPE,
    get_gcp_exporters,
    get_gcp_resource,
)

credentials, project_id = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
os.environ.setdefault("OTEL_RESOURCE_ATTRIBUTES", "cloud.region=us-central1")

maybe_set_otel_providers(
    otel_hooks_to_setup=[
        get_gcp_exporters(
            enable_cloud_tracing=True,
            enable_cloud_metrics=True,
            enable_cloud_logging=True,
            google_auth=(credentials, project_id),
        )
    ],
    otel_resource=get_gcp_resource(project_id),
)
```

### Step 3.3: Create the Deployment Script (`deploy/agent_engine/deploy.py`)
Create a deployment script that wraps `root_agent` from `agents.ops_agent.agent` inside `reasoning_engines.AdkApp` with `enable_tracing=True`:

```python
import os
import vertexai
from vertexai.preview import reasoning_engines
from agents.ops_agent.agent import root_agent

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ["STAGING_BUCKET"]  # e.g., gs://my-project-adk-staging

# 1. Initialize Vertex AI SDK
vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
    staging_bucket=STAGING_BUCKET,
)

# 2. Wrap OpsAgent in AdkApp with native OpenTelemetry Cloud Trace enabled
adk_app = reasoning_engines.AdkApp(
    agent=root_agent,
    enable_tracing=True,
)

# 3. Test locally before cloud deployment
print("--- Running Local Pre-Deployment Smoke Test ---")
session = adk_app.create_session(user_id="sre-smoke-test")
for event in adk_app.stream_query(
    user_id="sre-smoke-test",
    session_id=session.id,
    message="Check the health status of payment-service and summarize.",
):
    print(event)

# 4. Deploy to Vertex AI Agent Engine
print("--- Deploying OpsAgent to Vertex AI Agent Engine ---")
remote_agent = reasoning_engines.ReasoningEngine.create(
    adk_app,
    requirements=[
        "google-adk>=1.0.0",
        "google-cloud-aiplatform[adk,agent_engines]>=1.88.0",
        "opentelemetry-sdk>=1.28.0",
        "opentelemetry-exporter-gcp-trace>=1.7.0",
        "opentelemetry-exporter-gcp-monitoring>=1.7.0",
    ],
    extra_packages=[
        "./agents",
        "./observability",
    ],
    env_vars={
        "GOOGLE_GENAI_USE_VERTEXAI": "True",
        "ADK_MODEL": "gemini-2.5-flash",
        "OTEL_SERVICE_NAME": "adk-ops-agent",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
    },
    display_name="ops-agent-sre-copilot",
    description="Google ADK SRE Copilot with OpenTelemetry GenAI Observability",
)

print(f"Successfully deployed! Resource Name: {remote_agent.resource_name}")
```

### Step 3.4: Alternative One-Command ADK CLI Deployment
Google ADK also includes a built-in CLI command to deploy an agent folder directly to Vertex AI Agent Engine:

```bash
adk deploy agent_engine \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --staging_bucket="${STAGING_BUCKET}" \
  --display_name="ops-agent-sre-copilot" \
  --trace_to_cloud \
  ./agents/ops_agent
```

---

## 4. Querying the Deployed Agent & Viewing Telemetry

### 4.1 Invoke the Remote Agent via Python SDK
Once deployed, query your Reasoning Engine endpoint from any authenticated service:

```python
import vertexai
from vertexai.preview import reasoning_engines

vertexai.init(project="your-gcp-project-id", location="us-central1")

# Connect using the resource name output during deployment
remote_agent = reasoning_engines.ReasoningEngine(
    "projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/YOUR_ENGINE_ID"
)

remote_session = remote_agent.create_session(user_id="oncall-engineer")
for event in remote_agent.stream_query(
    user_id="oncall-engineer",
    session_id=remote_session["id"],
    message="Investigate why payment-service has high latency, check error logs, and create an incident ticket.",
):
    print(event)
```

### 4.2 Inspect Traces & Metrics in Google Cloud Console
1. **Cloud Trace Waterfall**:
   - Open **Google Cloud Console → Trace → Trace Explorer**.
   - Filter by Span Name `invoke_agent`, `call_llm`, or `execute_tool`.
   - Click any trace to inspect the full waterfall (`OpsAgent` → `gemini-2.5-flash` → `check_service_health` → `get_error_logs` → `create_incident_ticket`) along with `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` attributes.
2. **Cloud Monitoring / Managed Prometheus (GMP)**:
   - Open **Cloud Monitoring → Metrics Explorer → PromQL**.
   - Query token consumption:
     ```promql
     sum by (gen_ai_token_type, gen_ai_request_model) (rate(gen_ai_client_token_usage_sum[5m]))
     ```

---

## 5. Clean Up (Avoid Ongoing Charges)

Vertex AI Agent Engine bills for active runtime instances. To delete a deployed Reasoning Engine instance when not in use:

```python
remote_agent.delete(force=True)
```
Or via `gcloud`:
```bash
gcloud ai reasoning-engines delete YOUR_ENGINE_ID --region="${REGION}" --project="${PROJECT_ID}"
```
