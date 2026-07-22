import argparse
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app_config import CHROME_PATH
from utils.proxy_utils import build_playwright_proxy, mask_proxy


FACEBOOK_URL = "https://www.facebook.com/?locale=vi_VN"

NETWORK_ARGS = [
    "--disable-quic",
    "--disable-features=UseDnsHttpsSvcb,UseDnsHttpsSvcbAlpn,EncryptedClientHello",
    "--dns-prefetch-disable",
    "--disable-background-networking",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-blink-features=AutomationControlled",
]

ACTIVITY_JS = """
(intervalMs) => {
  window.__diagCount = 0;
  window.__diagTimer = setInterval(() => {
    window.__diagCount++;
    window.scrollBy(0, (window.__diagCount % 2) ? 300 : -300);
    fetch('/ajax/bootloader-endpoint/?_diag=' + window.__diagCount).catch(() => {});
    const node = document.createElement('div');
    node.textContent = 'diag ' + window.__diagCount;
    document.body.appendChild(node);
  }, intervalMs);
}
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diagnose Playwright CDP pump latency with a persistent Chrome profile."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("starved", "pumped"),
        default="starved",
        help="starved sleeps without Playwright calls; pumped periodically drains CDP.",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("DIAG_PROFILE", ""),
        help="Chrome profile path. Can also be set with DIAG_PROFILE.",
    )
    parser.add_argument(
        "--proxy",
        default=os.environ.get("DIAG_PROXY", ""),
        help="Optional proxy value. Can also be set with DIAG_PROXY.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("DIAG_URL", FACEBOOK_URL),
        help="URL to open before starting the activity pump.",
    )
    parser.add_argument("--hold", type=float, default=15.0, help="Seconds to hold before measuring.")
    parser.add_argument("--tick-ms", type=int, default=400, help="Pump interval for pumped mode.")
    parser.add_argument("--activity-ms", type=int, default=50, help="In-page activity interval.")
    return parser.parse_args()


def run(mode, profile, proxy="", url=FACEBOOK_URL, hold=15.0, tick_ms=400, activity_ms=50):
    profile_path = Path(profile).expanduser().resolve()
    profile_path.mkdir(parents=True, exist_ok=True)

    launch_options = {
        "user_data_dir": str(profile_path),
        "executable_path": CHROME_PATH,
        "headless": False,
        "ignore_default_args": ["--enable-automation"],
        "args": list(NETWORK_ARGS),
    }

    if proxy:
        launch_options["proxy"] = build_playwright_proxy(proxy)

    print(f"mode={mode}")
    print(f"profile={profile_path}")
    print(f"proxy={mask_proxy(proxy) if proxy else '(none)'}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(**launch_options)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.evaluate(ACTIVITY_JS, max(10, int(activity_ms)))

        end_time = time.monotonic() + max(0.0, float(hold))
        if mode == "starved":
            while time.monotonic() < end_time:
                time.sleep(max(0.05, tick_ms / 1000.0))
                _ = context.pages
        else:
            while time.monotonic() < end_time:
                page.wait_for_timeout(max(10, int(tick_ms)))

        start_time = time.monotonic()
        count = page.evaluate("() => window.__diagCount")
        first_round_trip_ms = round((time.monotonic() - start_time) * 1000)

        samples = []
        for _ in range(5):
            sample_start = time.monotonic()
            page.evaluate("() => window.__diagCount")
            samples.append(round((time.monotonic() - sample_start) * 1000))

        page.evaluate("() => clearInterval(window.__diagTimer)")
        print(f"activity ticks in page: {count}")
        print(f"first round-trip after {hold:g}s hold: {first_round_trip_ms} ms")
        print(f"next 5 round-trips (ms): {samples}")
        context.close()


def main():
    args = parse_args()
    if not args.profile:
        print("Missing --profile or DIAG_PROFILE.", file=sys.stderr)
        return 2

    run(
        mode=args.mode,
        profile=args.profile,
        proxy=args.proxy,
        url=args.url,
        hold=args.hold,
        tick_ms=args.tick_ms,
        activity_ms=args.activity_ms,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
