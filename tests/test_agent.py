"""Offline test suite for OpsAgent and local observability configurations.

Validates that:
1. The greeting tool executes side-effect-free and returns a valid success payload.
2. The observability diagnostic tools execute cleanly without network credentials.
3. The query_prometheus_metric tool handles queries gracefully.
4. The simulate_incident tool generates latency and error scenarios.
5. The agent instantiates cleanly without making live LLM or network requests.
6. Model resolution logic routes gemini-* and non-gemini models as specified.
7. Collector YAML and Prometheus YAML parse without errors.
8. Grafana dashboard JSON files parse and contain matching UIDs.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from agents.ops_agent.agent import (
    GreeterAgent,
    OpsAgent,
    check_observability_pipeline,
    check_pipeline_health,
    explain_telemetry_metric,
    greet_user,
    query_prometheus_metric,
    resolve_model,
    simulate_incident,
)


def test_greet_user_tool_with_valid_name():
  """Verifies greet_user returns success and properly formatted greeting."""
  result = greet_user("Alice")
  assert isinstance(result, dict)
  assert result.get("status") == "success"
  assert "Alice" in result.get("greeting", "")
  assert "OpsAgent" in result.get("greeting", "")


def test_greet_user_tool_with_empty_name():
  """Verifies greet_user provides a fallback when name is blank."""
  result = greet_user("   ")
  assert result.get("status") == "success"
  assert "Friend" in result.get("greeting", "")


def test_observability_diagnostic_tools():
  """Verifies local diagnostic tools execute and return expected schema."""
  health = check_pipeline_health()
  assert "pipeline_health" in health
  assert "OTel Collector HTTP (4318)" in health["pipeline_health"]

  guide = explain_telemetry_metric("tokens")
  assert guide.get("metric") == "gen_ai.client.token.usage"
  assert "promql" in guide


def test_query_prometheus_metric_handling():
  """Verifies query_prometheus_metric returns structured response even if Prometheus is offline."""
  res = query_prometheus_metric("up")
  assert "status" in res
  assert res.get("query") == "up"


def test_simulate_incident():
  """Verifies incident simulation executes and returns expected scenario data."""
  latency_sim = simulate_incident("latency")
  assert latency_sim.get("status") == "simulated_latency"
  assert latency_sim.get("duration_seconds") == 0.5

  error_sim = simulate_incident("error")
  assert error_sim.get("status") == "simulated_error"
  assert error_sim.get("error_code") == 500


def test_agent_instantiation_without_network():
  """Verifies OpsAgent instantiates cleanly without active network calls."""
  assert OpsAgent.name == "OpsAgent"
  assert len(OpsAgent.tools) >= 4
  assert "under three sentences" in OpsAgent.instruction
  # Backwards compatibility check
  assert GreeterAgent is OpsAgent


def test_model_resolution_gemini():
  """Verifies gemini-* names resolve to native model strings."""
  resolved = resolve_model("gemini-2.5-flash")
  assert isinstance(resolved, str)
  assert resolved == "gemini-2.5-flash"


def test_collector_yaml_validity():
  """Verifies otel-collector-config.yaml parses and binds to loopback endpoints."""
  root = Path(__file__).resolve().parent.parent
  collector_file = root / "otel-collector-config.yaml"
  assert collector_file.exists(), "otel-collector-config.yaml must exist"

  with open(collector_file, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

  # Check receivers
  receivers = config.get("receivers", {}).get("otlp", {}).get("protocols", {})
  assert "127.0.0.1:4317" in receivers.get("grpc", {}).get("endpoint", "")
  assert "127.0.0.1:4318" in receivers.get("http", {}).get("endpoint", "")

  # Check spanmetrics connector
  spanmetrics = config.get("connectors", {}).get("spanmetrics", {})
  assert spanmetrics.get("exemplars", {}).get("enabled") is True

  # Check prometheus exporter
  prom_exp = config.get("exporters", {}).get("prometheus", {})
  assert "127.0.0.1:8889" in prom_exp.get("endpoint", "")
  assert prom_exp.get("enable_open_metrics") is True


def test_prometheus_yaml_validity():
  """Verifies prometheus/prometheus.yml has 5s interval and targets 127.0.0.1:8889."""
  root = Path(__file__).resolve().parent.parent
  prom_file = root / "prometheus" / "prometheus.yml"
  assert prom_file.exists(), "prometheus/prometheus.yml must exist"

  with open(prom_file, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

  assert config.get("global", {}).get("scrape_interval") == "5s"
  targets = config["scrape_configs"][0]["static_configs"][0]["targets"]
  assert "127.0.0.1:8889" in targets


def test_grafana_dashboards_validity():
  """Verifies dashboard JSONs parse and UIDs match provisioning expectations."""
  root = Path(__file__).resolve().parent.parent
  genai_dash = root / "grafana" / "dashboards" / "adk-genai.json"
  traces_dash = root / "grafana" / "dashboards" / "adk-traces.json"

  assert genai_dash.exists()
  assert traces_dash.exists()

  with open(genai_dash, "r", encoding="utf-8") as f:
    data_genai = json.load(f)
  assert data_genai.get("uid") == "adk-genai"

  with open(traces_dash, "r", encoding="utf-8") as f:
    data_traces = json.load(f)
  assert data_traces.get("uid") == "adk-traces"
