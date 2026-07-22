from __future__ import annotations

from logging import getLogger


logger = getLogger(__name__)

# Block before response bodies reach the renderer. CDP avoids Playwright route
# interception, which can interfere with authenticated proxies.
BLOCKED_RESOURCE_URLS = (
    "*.jpg*", "*.jpeg*", "*.png*", "*.gif*", "*.webp*", "*.avif*",
    "*.svg*", "*.ico*", "*.mp4*", "*.webm*", "*.m3u8*",
    "*.woff*", "*.woff2*", "*.ttf*", "*.otf*",
)


def block_heavy_resources(context) -> None:
    """Block images, video and fonts on existing and subsequently opened pages."""

    def configure_page(page) -> None:
        try:
            session = context.new_cdp_session(page)
            session.send("Network.enable")
            session.send("Network.setBlockedURLs", {"urls": list(BLOCKED_RESOURCE_URLS)})
        except Exception as exc:
            logger.warning("Could not enable heavy-resource blocking for page: %s", exc)

    context.on("page", configure_page)
    for page in context.pages:
        configure_page(page)


VPS_LIGHTWEIGHT_INIT_SCRIPT = r"""
(() => {
    const installLightweightStyle = () => {
        if (!document.documentElement || document.getElementById('__vps_lightweight_style')) return;
        const style = document.createElement('style');
        style.id = '__vps_lightweight_style';
        style.textContent = `
            *, *::before, *::after {
                animation-duration: 0.001s !important;
                animation-delay: 0s !important;
                transition-duration: 0.001s !important;
                transition-delay: 0s !important;
                scroll-behavior: auto !important;
                caret-color: transparent !important;
            }
            video, audio, canvas,
            [role="complementary"],
            [aria-label="Chat"], [aria-label="Chats"],
            [aria-label="Đoạn chat"], [aria-label="Đoạn chat đang mở"],
            a[href*="/reel/"], a[href*="/reels/"] {
                display: none !important;
                visibility: hidden !important;
            }
            * { backdrop-filter: none !important; box-shadow: none !important; }
        `;
        document.documentElement.appendChild(style);
    };
    installLightweightStyle();
    document.addEventListener('DOMContentLoaded', installLightweightStyle, {once: true});

    try {
        Object.defineProperty(window, 'Notification', {value: undefined, configurable: false});
    } catch (_) {}
    try {
        Object.defineProperty(navigator, 'getUserMedia', {value: undefined, configurable: false});
    } catch (_) {}
})();
"""


def enable_vps_lightweight_mode(context) -> None:
    """Reduce rendering work while leaving the Facebook feed and GraphQL intact."""

    context.add_init_script(VPS_LIGHTWEIGHT_INIT_SCRIPT)
    for page in context.pages:
        try:
            page.evaluate(VPS_LIGHTWEIGHT_INIT_SCRIPT)
        except Exception as exc:
            logger.debug("Could not apply lightweight style to existing page: %s", exc)


def is_out_of_memory_page(page) -> bool:
    """Recognize Chrome's renderer OOM error page without waiting on selectors."""

    try:
        text = page.evaluate(
            "() => ((document.body && document.body.innerText) || '').slice(0, 4000).toLowerCase()"
        )
    except Exception:
        return False
    return any(marker in (text or "") for marker in (
        "out of memory", "status_no_memory", "status_commitment_limit",
    ))
