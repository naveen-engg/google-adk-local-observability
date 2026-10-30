import glob
import os
import shutil
import time
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

output_dir = Path("docs/media")
output_dir.mkdir(parents=True, exist_ok=True)
frames_dir = output_dir / "frames"
frames_dir.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    video_dir = output_dir / "temp_video"
    video_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(channel="chrome", headless=True)
    context = browser.new_context(
        viewport={"width": 1400, "height": 900},
        record_video_dir=str(video_dir),
        record_video_size={"width": 1400, "height": 900}
    )
    page = context.new_page()

    print("Navigating to ADK Dev UI...")
    page.goto("http://127.0.0.1:8000/dev-ui/")
    page.wait_for_timeout(3000)

    frame_count = 0
    def snap(label=""):
        global frame_count
        frame_path = frames_dir / f"frame_{frame_count:03d}.png"
        page.screenshot(path=str(frame_path))
        frame_count += 1
        print(f"Captured frame {frame_count} ({label})")

    snap("Initial State")

    prompts = [
        "Hi, my name is Naveen!",
        "Check the health of our local observability pipeline.",
        "Explain how the calls_total metric works."
    ]

    textarea = page.wait_for_selector("textarea[placeholder='Type a Message...']")

    for idx, prompt_text in enumerate(prompts):
        print(f"\nSending prompt {idx+1}: {prompt_text}")
        textarea.fill("")
        # Type character by character for realistic demo video feel
        for ch in prompt_text:
            textarea.type(ch, delay=35)
        
        page.wait_for_timeout(500)
        snap(f"Typed prompt {idx+1}")
        
        # Press Enter to send
        textarea.press("Enter")
        
        # Wait for model response to start and finish
        print("Waiting for response...")
        # Take a couple intermediate frames
        for _ in range(4):
            page.wait_for_timeout(1000)
            snap("Waiting/Streaming")
        
        # Additional wait for full tool execution and answer
        page.wait_for_timeout(2000)
        snap(f"Completed prompt {idx+1}")

    # Final overview snapshot
    page.wait_for_timeout(2000)
    snap("Final Chat State")
    page.screenshot(path=str(output_dir / "adk_web_chat.png"))

    # Close page and context to finalize video
    page.close()
    context.close()
    browser.close()

    # Rename the recorded webm video
    recorded_videos = list(video_dir.glob("*.webm"))
    if recorded_videos:
        final_video = output_dir / "adk_web_demo.webm"
        if final_video.exists():
            final_video.unlink()
        shutil.move(str(recorded_videos[0]), str(final_video))
        print(f"Recorded video saved to: {final_video}")
    shutil.rmtree(str(video_dir), ignore_errors=True)

# Build animated GIF using Pillow
print("Building animated GIF from captured frames...")
frame_files = sorted(frames_dir.glob("frame_*.png"))
if frame_files:
    # Sample every other frame or use all with appropriate duration
    images = [Image.open(f) for f in frame_files]
    # Resize slightly for optimized GIF size (1120x720)
    resized_images = [im.resize((1120, 720), Image.Resampling.LANCZOS) for im in images]
    gif_path = output_dir / "adk_web_demo.gif"
    resized_images[0].save(
        str(gif_path),
        save_all=True,
        append_images=resized_images[1:],
        duration=650,
        loop=0,
        optimize=True
    )
    print(f"Animated GIF saved to: {gif_path}")

shutil.rmtree(str(frames_dir), ignore_errors=True)
print("ADK Web Demo recording complete!")
