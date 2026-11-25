# Observability for GenAI Agents: From Zero-Docker Local Dev to Google Cloud Run, Vertex AI, and Dynatrace

### *How to instrument Google ADK Python agents with OpenTelemetry, conquer corporate TLS proxies, and scale from local Prometheus & Jaeger to Cloud Run sidecars and Dynatrace Grail.*

---

**By Naveen Kumar**  
*Published in Towards Data Science / DevOps / GenAI Engineering*  
*Reading Time: 8 min read*

---

## Introduction: The "Black Box" Agent Problem

AI agents powered by Large Language Models (LLMs) are no longer just demo scripts—they are making API calls, querying corporate databases, running multi-turn reasoning loops, and orchestrating critical workflows.

Yet, in most organizations, these agents remain **complete black boxes**:
* *Why did a single customer prompt take 12 seconds to resolve?* Was it LLM inference latency, tool execution, or a stalled retry loop?
* *How many tokens (input vs. output) are being consumed per turn across different models?*
* *How can developers debug agent behavior locally on Windows laptops behind corporate VPNs (Zscaler, Netskope) without wrestling with heavy Docker VMs?*
* *How do we scale telemetry seamlessly from local development into enterprise production on Google Cloud and Dynatrace?*

In this article, I will share the architectural blueprint and open-source implementation of **Google ADK Enterprise Observability**: an end-to-end telemetry system for Google Agent Development Kit (ADK) Python agents, scaling from a lightweight, zero-Docker local workstation stack to serverless Google Cloud Run, Vertex AI Agent Engine, and Dynatrace.

---

## Architecture: The Multi-Stage Observability Pipeline

Whether running locally on a developer laptop or in the cloud, our agent architecture adheres to a unified OpenTelemetry standard:

```
[ Developer / SRE User ]
         │
         ▼
[ Google ADK Agent: OpsAgent (gemini-3.5-flash) ]
         │  • Diagnostic Tools (check_pipeline_health, simulate_incident, etc.)
         │  • OpenTelemetry Instrumentation (Traces, Metrics, Logs)
         │  • Injected OS Truststore (Windows CryptoAPI)
         │
         ├─────────────────────────────────────────────┐
         ▼ (Local Dev / Zero-Docker)                   ▼ (Enterprise Production)
[ Local OTel Collector ]                       [ Cloud Run / Agent Engine ]
   ├── OTLP/HTTP :4318                            ├── Sidecar OTel Collector
   ├── Jaeger v2 (Traces :16686)                  ├── Google Cloud Trace
   ├── Prometheus (Metrics :9090)                 ├── Google Managed Prometheus (GMP)
   └── Grafana (Dashboards :3000)                 └── Dynatrace Grail (/api/v2/otlp)
```

Let’s walk through the four core pillars of this solution.

---

## 1. Zero-Docker Local Observability on Windows

When developing locally, spinning up heavy Docker Desktop containers just to test an agent creates massive friction—especially on corporate laptops with locked-down Hyper-V settings.

We built a **Windows-first, native-binary local stack**:
* **ADK Dev Web UI & CLI**: Runs natively on Python 3.13.
* **OpenTelemetry Collector Contrib**: Standalone Windows binary (`otelcol-contrib.exe`) listening on loopback (`127.0.0.1:4318`).
* **Jaeger v2**: In-memory distributed tracing storage with an instant UI on `127.0.0.1:16686`.
* **Prometheus**: Native Windows binary (`prometheus.exe`) scraping OpenMetrics with trace exemplar storage enabled.
* **Grafana Server**: Pre-provisioned dashboards visualizing GenAI throughput and latencies on `127.0.0.1:3000`.

A single PowerShell script (`.\scripts\start-stack.ps1`) verifies all dependencies, inspects local ports, and boots the entire observability pipeline in seconds.

![Grafana GenAI Observability Dashboard](https://raw.githubusercontent.com/naveen-engg/google-adk-local-observability/feat/enterprise-edition/docs/media/grafana_adk_genai.png)
*Figure 1: Pre-provisioned Grafana dashboard tracking agent throughput, token velocity, and p95 LLM operation latency.*

---

## 2. The Corporate TLS Breakthrough: Solving Zscaler & Netskope with `truststore`

One of the most pervasive hurdles in corporate environments is **TLS interception**. Corporate security appliances (Zscaler, Netskope, Palo Alto) decrypt outbound HTTPS traffic to inspect payloads, re-signing the connection with an internal private Root Certificate Authority (CA).

Standard Python distributions rely solely on Mozilla's public CA bundle (`certifi`) and completely ignore host OS certificate stores. The result?
```text
SSLCertVerificationError: certificate verify failed: self-signed certificate in certificate chain
```

Developers often resort to dangerous anti-patterns: passing `verify=False`, exporting unencrypted `.pem` files, or disabling SSL inspection.

### The Solution: Native OS Truststore Injection
In our agent bootstrap, we inject the operating system's native certificate store directly into Python's SSL layer:

```python
import truststore
truststore.inject_into_ssl()
```

### Real-World Corporate TLS Gotchas:
When testing this in production enterprise environments, two critical nuances emerged:
1. **gRPC vs. HTTP (`grpcio` bypasses `truststore`)**: `truststore.inject_into_ssl()` patches standard Python `ssl` sockets (covering `urllib`, `requests`, `httpx`, and Google GenAI REST calls). However, C-core `grpcio` (often used by default OpenTelemetry gRPC exporters) compiles its own embedded BoringSSL engine, completely ignoring Python's SSL context. **Standardizing on OTLP over HTTP (`http/protobuf` on port `4318`) guarantees seamless OS truststore inheritance.**
2. **Intermediate CA Chains**: If corporate proxies only push the Root CA to the Windows store while dynamically re-signing traffic with an intermediate CA, `CryptoAPI` validation can fail if outbound HTTP/80 is blocked (preventing AIA fetching). Ensuring enterprise intermediate CAs are installed in Windows `Intermediate Certification Authorities` completely eliminates handshake drops.

---

## 3. Serverless Cloud Run with an OpenTelemetry Sidecar

For production microservices and serverless webhooks, we package `OpsAgent` for **Google Cloud Run** using a **Multi-Container (Sidecar)** pattern:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Google Cloud Run Revision (Scale-to-Zero Pod)                          │
│                                                                        │
│  ┌──────────────────────────────┐     OTLP/HTTP      ┌───────────────┐ │
│  │ Container 1: adk-agent       │ ─────────────────> │ Container 2:  │ │
│  │ (FastAPI + ADK Web UI :8000) │   127.0.0.1:4318   │ otel-collector│ │
│  └──────────────────────────────┘                    │ (Sidecar)     │ │
│                                                      └───────┬───────┘ │
└──────────────────────────────────────────────────────────────┼─────────┘
                                                               │ OTLP /v1
                                                               ▼
                                                      Dynatrace / Cloud Trace
```

* **Container 1 (`adk-agent`)**: Hosts the ADK FastAPI server running `OpsAgent` (backed by Vertex AI Gemini `gemini-3.5-flash`). It exposes the full interactive Angular ADK Dev UI on `/` and dispatches telemetry over loopback (`127.0.0.1:4318`).
* **Container 2 (`otel-collector`)**: Runs `otelcol-contrib` inside the same pod. It reads its configuration and Dynatrace API tokens securely mounted from **Google Cloud Secret Manager**, batches spans, limits memory, and exports directly to Dynatrace (`/api/v2/otlp`).
* **FinOps Efficiency**: Configured with `minScale: 0`, the entire multi-container service scales down to zero active instances when idle—incurring **$0 idle runtime costs**.

![Google ADK Web UI on Cloud Run](https://raw.githubusercontent.com/naveen-engg/google-adk-local-observability/feat/enterprise-edition/docs/media/cloud_run_adk_web_ui.png)
*Figure 2: Live Google ADK Web Dev UI served from Google Cloud Run, streaming SRE diagnostics in real time.*

---

## 4. Full Enterprise Observability in Dynatrace

While cloud-native tools like Google Cloud Trace and Managed Prometheus are great, large enterprises standardize on unified APM platforms like **Dynatrace**.

With `google-adk[otel]>=2.13.0`, Google ADK natively emits **all 7 OpenTelemetry GenAI histogram metrics**:
1. `gen_ai.client.token.usage`: Input/output tokens split by model.
2. `gen_ai.client.operation.duration`: LLM inference latency.
3. `gen_ai.execute_tool.duration`: Latency breakdown per agent tool call (`check_pipeline_health`, `simulate_incident`).
4. `gen_ai.invoke_agent.duration`: Total duration per agent invocation turn.
5. `gen_ai.invoke_agent.inference_calls`: LLM calls required to satisfy the turn.
6. `gen_ai.invoke_agent.tool_calls`: Tool invocations executed per turn.
7. `gen_ai.invoke_workflow.duration`: End-to-end workflow invocation duration.

### Ingesting with `DELTA` Temporality
Dynatrace's OTLP metric ingestion requires `DELTA` metric temporality rather than `CUMULATIVE`. In our collector pipeline, setting:
```yaml
env:
  OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE: "delta"
```
allows Dynatrace to ingest rate and histogram data with zero drops.

![Dynatrace GenAI Metrics Dashboard](https://raw.githubusercontent.com/naveen-engg/google-adk-local-observability/feat/enterprise-edition/docs/media/dynatrace_genai_metrics_dashboard.png)
*Figure 3: Dynatrace dashboard visualizing all 7 native GenAI metrics in real time.*

### Nanosecond-Level Distributed Trace Waterfalls
Every agent interaction produces an end-to-end distributed trace. In Dynatrace's Distributed Tracing view, engineers can inspect the complete parent-child span hierarchy:
* `invoke_workflow OpsAgent` (5.32s)
  * `invoke_agent OpsAgent`
    * `generate_content gemini-3.5-flash` (Initial LLM reasoning & tool decision)
    * `execute_tool check_pipeline_health` (Executing SRE tool)
    * `generate_content gemini-3.5-flash` (Final response synthesis)

![Dynatrace Distributed Trace Waterfall](https://raw.githubusercontent.com/naveen-engg/google-adk-local-observability/feat/enterprise-edition/docs/media/dynatrace_distributed_trace_waterfall.png)
*Figure 4: Complete distributed trace waterfall mapping an agent turn from prompt entry to multi-tool execution.*

---

## Key Takeaways & Best Practices

1. **Standardize on OpenTelemetry Early**: Instrument using semantic conventions (`gen_ai.*`) so you never get locked into a single APM vendor. Your traces and metrics can flow to Jaeger, Prometheus, Google Cloud Trace, or Dynatrace with zero code refactoring.
2. **Favor OTLP/HTTP over gRPC for Client-Side Agents**: OTLP over HTTP (`http/protobuf` on `:4318`) inherits host operating system truststores seamlessly, avoiding C-core BoringSSL certificate errors behind corporate TLS inspection proxies.
3. **Use Multi-Container Sidecars for Serverless Agents**: Placing the OpenTelemetry Collector as a sidecar next to the agent container decouples telemetry batching, credential handling (Secret Manager), and PII data scrubbing from application code.
4. **Automate UI & Telemetry Verification**: Automated test scripts (e.g. Playwright simulating browser UI interactions) ensure telemetry pipelines remain healthy across continuous integration and deployment.

---

## Resources & Open-Source Code

All configuration files, manifests, simulation scripts, and Grafana/Dynatrace dashboard JSONs are open source and available on GitHub:

👉 **GitHub Repository**: [https://github.com/naveen-engg/google-adk-local-observability](https://github.com/naveen-engg/google-adk-local-observability)  
👉 **Enterprise Branch**: [`feat/enterprise-edition`](https://github.com/naveen-engg/google-adk-local-observability/tree/feat/enterprise-edition)

*Have questions about OpenTelemetry for GenAI or running Google ADK in enterprise environments? Connect with me on [LinkedIn](https://www.linkedin.com) or open an issue on GitHub!*
