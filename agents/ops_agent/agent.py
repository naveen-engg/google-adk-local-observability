"""OpsAgent implementation.

Defines OpsAgent (AI Site Reliability & Observability Copilot), multi-provider model resolution,
concise instruction text, and interactive SRE diagnostic tools for local OpenTelemetry pipelines.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.parse
import urllib.request
from typing import Any, Union
from google.adk.agents import Agent

logger = logging.getLogger("ops_agent")


def greet_user(name: str) -> dict[str, str]:
  """Greets a user when they explicitly provide their name.

  Args:
    name: The name of the user to greet.

  Returns:
    A dictionary containing the greeting status and message.
  """
  clean_name = name.strip() if (name and name.strip()) else "Friend"
  return {
      "status": "success",
      "greeting": (
          f"Hello, {clean_name}! I am OpsAgent, your SRE and Observability Copilot for Google ADK."
      ),
  }


def check_pipeline_health() -> dict[str, Any]:
  """Checks the real-time operational status of the local observability ports on localhost (127.0.0.1).

  Returns:
    A dictionary listing local port status for Collector, Jaeger, Prometheus, Grafana, and ADK Web.
  """
  services = {
      "OTel Collector HTTP (4318)": 4318,
      "OTel Collector gRPC (4317)": 4317,
      "Collector Prometheus Exporter (8889)": 8889,
      "Jaeger Tracing UI (16686)": 16686,
      "Prometheus Metrics UI (9090)": 9090,
      "Grafana Dashboards (3000)": 3000,
      "ADK Dev Web UI (8000)": 8000,
  }
  status_map = {}
  for name, port in services.items():
    try:
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        status_map[name] = (
            "ONLINE" if s.connect_ex(("127.0.0.1", port)) == 0 else "OFFLINE"
        )
    except Exception:
      status_map[name] = "OFFLINE"

  return {"pipeline_health": status_map}


# Alias for backward compatibility
check_observability_pipeline = check_pipeline_health


def explain_telemetry_metric(metric_topic: str) -> dict[str, str]:
  """Provides definitions, units, and PromQL guidance for ADK OpenTelemetry GenAI metrics.

  Args:
    metric_topic: Topic such as 'tokens', 'latency', 'tools', or 'spans'.

  Returns:
    A guide with metric names, units, and sample PromQL queries.
  """
  topic = metric_topic.lower().strip()
  if "token" in topic:
    return {
        "metric": "gen_ai.client.token.usage",
        "type": "Histogram / Counter",
        "unit": "tokens",
        "promql": "sum(rate(gen_ai_client_token_usage_sum[1m])) by (gen_ai_token_type)",
        "description": "Tracks input and output token consumption per model call.",
    }
  elif "latenc" in topic or "duration" in topic:
    return {
        "metric": "gen_ai.client.operation.duration",
        "type": "Histogram",
        "unit": "seconds",
        "promql": "histogram_quantile(0.95, sum(rate(gen_ai_client_operation_duration_seconds_bucket[5m])) by (le))",
        "description": "Measures end-to-end LLM request duration and percentile latency.",
    }
  elif "tool" in topic:
    return {
        "metric": "gen_ai.execute_tool",
        "type": "Counter / Histogram",
        "unit": "calls",
        "promql": "sum(rate(gen_ai_execute_tool_total[5m])) by (tool_name)",
        "description": "Records tool invocation counts and execution durations.",
    }
  return {
      "metric": "calls_total (spanmetrics)",
      "type": "Counter with Trace-ID Exemplars",
      "unit": "spans",
      "promql": "sum(rate(calls_total[1m])) by (span_name)",
      "description": "Aggregated span execution rates with trace-ID exemplars linking into Jaeger.",
  }


def query_prometheus_metric(query: str) -> dict[str, Any]:
  """Queries live metric data from the local Prometheus instance at http://127.0.0.1:9090.

  Args:
    query: A PromQL query string (e.g. 'up', 'calls_total', 'gen_ai_client_token_usage_sum').

  Returns:
    A dictionary with query result status and Prometheus data.
  """
  clean_query = query.strip()
  url = f"http://127.0.0.1:9090/api/v1/query?query={urllib.parse.quote(clean_query)}"
  try:
    req = urllib.request.Request(url, headers={"User-Agent": "OpsAgent/1.0"})
    with urllib.request.urlopen(req, timeout=1.0) as resp:
      if resp.status == 200:
        data = json.loads(resp.read().decode("utf-8"))
        return {
            "status": "success",
            "query": clean_query,
            "data": data.get("data", {}).get("result", []),
        }
  except Exception as e:
    return {
        "status": "unavailable",
        "query": clean_query,
        "message": f"Prometheus at 127.0.0.1:9090 is not reachable or returned an error: {e}",
    }


def simulate_incident(incident_type: str) -> dict[str, Any]:
  """Simulates an operational incident scenario (latency spike, tool failure, or traffic burst) to generate visible telemetry.

  Args:
    incident_type: One of 'latency', 'error', or 'burst'.

  Returns:
    Diagnostic simulation report.
  """
  kind = incident_type.lower().strip()
  if "latenc" in kind or "slow" in kind:
    time.sleep(0.5)  # Generates real latency in trace span and duration histogram
    return {
        "status": "simulated_latency",
        "duration_seconds": 0.5,
        "impact": "Introduced a 500ms latency delay into the tool execution trace span.",
    }
  elif "err" in kind or "fail" in kind:
    return {
        "status": "simulated_error",
        "error_code": 500,
        "error_message": "Simulated upstream connection failure in collector pipeline.",
        "impact": "Generated an error telemetry event for trace and metric error rate counters.",
    }
  return {
      "status": "simulated_burst",
      "synthetic_events": 100,
      "impact": "Simulated a sudden spike in client token usage and LLM invocation rate.",
  }


def resolve_model(model_name: str | None = None) -> Union[str, Any]:
  """Resolves the model parameter based on model name prefix and environment.

  - 'gemini-*' uses ADK's native Google GenAI model integration.
  - Other names use ADK's LiteLlm adapter (e.g. github_copilot/*, ollama_chat/*, openai/*).

  Args:
    model_name: Optional explicit model name. Defaults to ADK_MODEL env var.

  Returns:
    Model string (for Gemini native) or LiteLlm model instance.
  """
  effective_name = (
      model_name
      or os.environ.get("ADK_MODEL")
      or "gemini-2.5-flash"
  ).strip()

  if effective_name.startswith("gemini-"):
    logger.debug("Using native Google GenAI model: %s", effective_name)
    return effective_name

  try:
    from google.adk.models.lite_llm import LiteLlm

    # Propagate OLLAMA_API_BASE if targeting local Ollama models
    if "ollama" in effective_name.lower():
      ollama_base = os.environ.get("OLLAMA_API_BASE")
      if ollama_base:
        os.environ.setdefault("OLLAMA_API_BASE", ollama_base)

    logger.debug("Using LiteLlm adapter model: %s", effective_name)
    return LiteLlm(model_name=effective_name)
  except ImportError as err:
    logger.warning(
        "LiteLLM support is not installed (pip install litellm). "
        "Falling back to raw model string '%s'. Error: %s",
        effective_name,
        err,
    )
    return effective_name


# Single agent instance for ADK Dev UI (adk web) and programmatic runners
OpsAgent = Agent(
    name="OpsAgent",
    description=(
        "OpsAgent: An AI Site Reliability & Observability Copilot for Google ADK. "
        "Diagnoses local observability pipelines, queries live telemetry metrics, "
        "simulates incidents, and inspects OpenTelemetry traces."
    ),
    instruction=(
        "You are OpsAgent, an AI Site Reliability and Observability Copilot for Google ADK. "
        "When the user introduces themselves, call greet_user to welcome them. "
        "When the user asks about system health, ports, or service status, call check_pipeline_health. "
        "When the user asks to explain or define telemetry metrics, call explain_telemetry_metric. "
        "When the user asks to query live Prometheus metrics or PromQL data, call query_prometheus_metric. "
        "When the user asks to simulate an incident, latency spike, or failure scenario, call simulate_incident. "
        "Answer questions directly and concisely, and always keep each response strictly under three sentences."
    ),
    model=resolve_model(),
    tools=[
        greet_user,
        check_pipeline_health,
        explain_telemetry_metric,
        query_prometheus_metric,
        simulate_incident,
    ],
)

# Aliases for backwards compatibility with test suites and runners
GreeterAgent = OpsAgent
agent = OpsAgent
root_agent = OpsAgent
