"""Automated script to simulate a user session on the Cloud Run ADK Web UI and capture a screenshot."""

import time
from playwright.sync_api import sync_playwright

def main():
    target_url = "https://adk-ops-agent-981754278786.us-central1.run.app/dev-ui/?app=ops_agent"
    output_png = r"docs\media\cloud_run_adk_web_ui.png"

    print(f"Opening ADK Web UI: {target_url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
        )
        page = context.new_page()

        page.goto(target_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # Handle "Help Improve ADK!" telemetry opt-in dialog if present
        opt_in_btn = page.query_selector('button:has-text("No Thanks")') or page.query_selector('button:has-text("Enable")')
        if opt_in_btn:
            print("Dismissing ADK telemetry dialog...")
            opt_in_btn.click()
            page.wait_for_timeout(1000)

        # Wait for textarea
        textarea = page.wait_for_selector('textarea[placeholder*="Type a message"]', timeout=15000)
        prompt_text = "Check the service health of api-gateway and payment-service, and check pipeline health."
        print(f"Typing prompt: {prompt_text}")
        textarea.fill(prompt_text)
        page.wait_for_timeout(500)

        # Click send button or press Enter
        print("Submitting prompt...")
        send_btn = page.query_selector('button:has-text("send")') or page.query_selector('button[aria-label*="send"]')
        if send_btn and send_btn.is_enabled():
            send_btn.click()
        else:
            textarea.press("Enter")

        # Wait for agent processing and streaming response
        print("Waiting for OpsAgent to execute tools and render response in UI...")
        # Wait up to 25s for assistant response
        for _ in range(25):
            time.sleep(1)
            # Check if assistant message appeared
            messages = page.query_selector_all('.message, .agent-message, mat-card, .chat-message')
            if len(messages) > 1:
                break

        # Additional wait for full tool-call cards & response text to render completely
        page.wait_for_timeout(5000)

        # Capture screenshot
        print(f"Capturing screenshot to {output_png}...")
        page.screenshot(path=output_png, full_page=False)
        print("Screenshot captured successfully!")

        browser.close()

if __name__ == "__main__":
    main()
