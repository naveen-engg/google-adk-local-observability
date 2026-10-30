import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

output_dir = Path("docs/media")
output_dir.mkdir(parents=True, exist_ok=True)

# Fetch latest trace ID from Jaeger v3 API
latest_trace_id = "b0c4b2b1a66ec7e7583e4baf53340226"
try:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    req_url = f"http://127.0.0.1:16686/api/v3/traces?query.startTimeMin={past}&query.startTimeMax={now}&query.limit=1"
    req = urllib.request.urlopen(req_url, timeout=5)
    data = json.loads(req.read().decode())
    tid = data["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"]
    if tid:
        latest_trace_id = tid
        print(f"Discovered latest trace ID: {latest_trace_id}")
except Exception as e:
    print(f"Using default trace ID ({latest_trace_id}), error fetching: {e}")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()

    # 1. Prometheus
    print("Capturing Prometheus Table & Graph...")
    page.goto("http://127.0.0.1:9090/graph?g0.expr=traces_span_metrics_calls_total&g0.tab=1")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(output_dir / "prometheus_metrics.png"), full_page=False)

    # 2. Jaeger Trace View
    print(f"Capturing Jaeger Waterfall for trace: {latest_trace_id}...")
    page.goto(f"http://127.0.0.1:16686/trace/{latest_trace_id}")
    page.wait_for_timeout(4000)
    page.screenshot(path=str(output_dir / "jaeger_trace_waterfall.png"), full_page=False)

    # 2b. Jaeger Search View
    print("Capturing Jaeger Search...")
    page.goto("http://127.0.0.1:16686/search?service=adk-greeter&limit=20")
    page.wait_for_timeout(3000)
    find_btn = page.query_selector("button:has-text('Find Traces')")
    if find_btn:
        find_btn.click()
        page.wait_for_timeout(2000)
    page.screenshot(path=str(output_dir / "jaeger_search.png"), full_page=False)

    # 3. Grafana Login
    print("Logging into Grafana...")
    page.goto("http://127.0.0.1:3000/login")
    page.wait_for_timeout(2000)
    user_input = page.query_selector("input[name='user']")
    if user_input:
        user_input.fill("admin")
        page.fill("input[name='password']", "admin")
        page.click("button[type='submit']")
        page.wait_for_timeout(3000)
        skip_btn = page.query_selector("button:has-text('Skip'), a:has-text('Skip')")
        if skip_btn:
            skip_btn.click()
            page.wait_for_timeout(2000)

    # 4. Grafana GenAI Dashboard
    print("Capturing Grafana GenAI Dashboard...")
    page.goto("http://127.0.0.1:3000/d/adk-genai?from=now-1h&to=now&refresh=10s")
    page.wait_for_timeout(5000)
    page.screenshot(path=str(output_dir / "grafana_adk_genai.png"), full_page=False)

    # 5. Grafana Traces Dashboard
    print(f"Capturing Grafana Traces Dashboard with trace {latest_trace_id}...")
    page.goto(f"http://127.0.0.1:3000/d/adk-traces?from=now-1h&to=now&var-limit=20&var-trace_id={latest_trace_id}")
    page.wait_for_timeout(6000)
    page.screenshot(path=str(output_dir / "grafana_adk_traces.png"), full_page=False)

    browser.close()
    print("All snapshots refreshed successfully!")
