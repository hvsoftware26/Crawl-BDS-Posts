from __future__ import annotations

import random
import time
import unicodedata
from logging import getLogger
from urllib.parse import urlparse

from app_config import (
    FACEBOOK_COMMENT_ACTION_DELAY_MAX_SECONDS,
    FACEBOOK_COMMENT_ACTION_DELAY_MIN_SECONDS,
    FACEBOOK_COMMENT_TYPING_DELAY_MAX_SECONDS,
    FACEBOOK_COMMENT_TYPING_DELAY_MIN_SECONDS,
)

logger = getLogger(__name__)


COMMENT_BOX_JS = """
() => {
    const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return (
            rect.width >= 80 &&
            rect.height >= 12 &&
            rect.bottom > 0 &&
            rect.top < window.innerHeight &&
            style.visibility !== "hidden" &&
            style.display !== "none"
        );
    };

    const contextText = (el) => {
        const parts = [];
        let current = el;
        for (let depth = 0; current && depth < 5; depth += 1) {
            parts.push(
                current.getAttribute("aria-label") || "",
                current.getAttribute("aria-placeholder") || "",
                current.getAttribute("data-placeholder") || "",
                current.innerText || "",
                current.textContent || ""
            );
            current = current.parentElement;
        }
        return parts.join(" ").toLowerCase();
    };

    const boxes = Array.from(
        document.querySelectorAll('div[contenteditable="true"][role="textbox"], div[contenteditable="true"]')
    );
    const candidates = boxes.filter((el) => {
        const text = contextText(el);
        return visible(el) && (text.includes("bình luận") || text.includes("comment"));
    });

    candidates.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return candidates[0] || null;
}
"""


COMMENT_IDENTITY_CONTEXT_JS = """
(el) => {
    const parts = [];
    let current = el;
    for (let depth = 0; current && depth < 4; depth += 1) {
        parts.push(
            current.getAttribute("aria-label") || "",
            current.getAttribute("aria-placeholder") || "",
            current.getAttribute("data-placeholder") || "",
            current.innerText || "",
            current.textContent || ""
        );
        current = current.parentElement;
    }
    const text = parts.join(" ").replace(/\\s+/g, " ").trim();
    const patterns = [
        /bình luận dưới tên\\s+.{1,80}/i,
        /bình luận với tư cách\\s+.{1,80}/i,
        /comment as\\s+.{1,80}/i
    ];
    for (const pattern of patterns) {
        const match = text.match(pattern);
        if (match) {
            return match[0];
        }
    }
    return text.slice(0, 240);
}
"""


CLICK_DB_PAGE_IDENTITY_JS = """
({profileName, pageNames}) => {
    const normalize = (value) => String(value || "")
        .normalize("NFD")
        .replace(/[\\u0300-\\u036f]/g, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .replace(/\\s+/g, " ")
        .trim()
        .toLowerCase();
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const profile = normalize(profileName);
    const profileAliases = new Set([profile, ...profile.split(" ").filter((part) => part.length >= 3)]);
    const dbPages = (pageNames || [])
        .map((name) => ({raw: clean(name), normalized: normalize(name)}))
        .filter((page) => page.normalized);
    if (!dbPages.length) {
        return {clicked: false, reason: "no_db_page_names"};
    }
    const isVisible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 24 && rect.height > 12 && style.display !== "none" && style.visibility !== "hidden";
    };
    const blocked = (name) => {
        const normalized = normalize(name);
        const isProfile = Array.from(profileAliases).some((alias) => alias && normalized.includes(alias));
        return (
            !normalized ||
            isProfile ||
            normalized === "tao" ||
            normalized.includes("trung tam tai khoan") ||
            normalized.includes("tim kiem") ||
            normalized.includes("trang ca nhan") ||
            normalized.includes("chuyen de tuong tac") ||
            normalized.includes("tim hieu them")
        );
    };
    const matchDbPage = (name) => {
        const normalized = normalize(name);
        if (blocked(name)) {
            return null;
        }
        return dbPages.find((page) => normalized === page.normalized || normalized.includes(page.normalized));
    };
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'));
    if (!dialogs.length) {
        return {clicked: false, reason: "no_dialog"};
    }
    const roots = dialogs;

    for (const root of roots.reverse()) {
        const nodes = Array.from(root.querySelectorAll('[role="button"], [tabindex="0"], a'));
        for (const node of nodes) {
            if (!isVisible(node)) {
                continue;
            }
            const rawText = node.innerText || node.textContent || node.getAttribute("aria-label") || "";
            const lines = String(rawText).split("\\n").map(clean).filter(Boolean);
            const matchedPage = lines.map(matchDbPage).find(Boolean);
            if (!matchedPage) {
                continue;
            }

            node.click();
            return {clicked: true, name: matchedPage.raw};
        }
    }

    return {clicked: false, reason: "no_db_page_in_dialog"};
}
"""


BODY_HAS_MARKER_JS = """
(markers) => {
    const normalize = (value) => String(value || "")
        .normalize("NFD")
        .replace(/[\\u0300-\\u036f]/g, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .replace(/\\s+/g, " ")
        .trim()
        .toLowerCase();
    const bodyText = normalize(document.body ? document.body.innerText || document.body.textContent || "" : "");
    return (markers || []).some((marker) => bodyText.includes(normalize(marker)));
}
"""


BODY_FIND_MARKER_JS = """
(markers) => {
    const normalize = (value) => String(value || "")
        .normalize("NFD")
        .replace(/[\\u0300-\\u036f]/g, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .replace(/\\s+/g, " ")
        .trim()
        .toLowerCase();
    const bodyText = normalize(document.body ? document.body.innerText || document.body.textContent || "" : "");
    for (const marker of markers || []) {
        if (bodyText.includes(normalize(marker))) {
            return marker;
        }
    }
    return "";
}
"""


class FacebookBrowserCommenter:
    def __init__(
        self,
        browser_context,
        account_name: str = "",
        page_names: list[str] | None = None,
        status_callback=None,
        stop_callback=None,
    ):
        if not browser_context:
            raise RuntimeError("Missing Playwright browser context for browser commenting")

        self.browser_context = browser_context
        self.account_name = str(account_name or "").strip()
        self.page_names = self._normalize_page_names(page_names or [])
        self.selected_identity_name = ""
        self.status_callback = status_callback or (lambda _message: None)
        self.stop_callback = stop_callback or (lambda: False)
        self.page = None

    def close(self):
        if not self.page:
            return
        try:
            self.page.close()
        except Exception as exc:
            logger.warning("Could not close browser comment page: %s", exc)
        finally:
            self.page = None

    def comment_post(self, post: dict, message: str) -> dict:
        post_url = self._resolve_post_url(post)
        comment_message = str(message or "").strip()
        if not comment_message:
            raise ValueError("Comment message is empty")

        page = self._ensure_page()
        self.status_callback("Mở bài viết để comment bằng Chrome")
        logger.info("Open post for browser comment: post_id=%s url=%s", post.get("id"), post_url)
        page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
        self._natural_wait(2.0, 4.0)
        self._raise_if_comments_disabled()

        comment_box = self._find_comment_box()
        comment_box = self._ensure_comment_identity(comment_box)
        self._type_comment(comment_box, comment_message)
        self._submit_comment(comment_box)

        return {
            "post_id": str(post.get("id") or ""),
            "post_url": post_url,
            "page_name": self.selected_identity_name,
            "comment_id": "",
            "method": "browser",
        }

    def _ensure_page(self):
        if self.page and not self.page.is_closed():
            return self.page

        self.page = self.browser_context.new_page()
        self.page.set_viewport_size({"width": 500, "height": 700})
        self.page.set_default_timeout(30000)
        self.page.set_default_navigation_timeout(60000)
        return self.page

    def _resolve_post_url(self, post: dict) -> str:
        url = str((post or {}).get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            return url

        post_id = str((post or {}).get("id") or "").strip()
        if post_id:
            return f"https://www.facebook.com/{post_id}"

        raise ValueError("Post URL is missing")

    def _natural_wait(self, min_seconds: float | None = None, max_seconds: float | None = None) -> bool:
        min_delay = (
            FACEBOOK_COMMENT_ACTION_DELAY_MIN_SECONDS
            if min_seconds is None
            else float(min_seconds)
        )
        max_delay = (
            FACEBOOK_COMMENT_ACTION_DELAY_MAX_SECONDS
            if max_seconds is None
            else float(max_seconds)
        )
        delay_seconds = random.uniform(min_delay, max(min_delay, max_delay))
        deadline = time.monotonic() + delay_seconds

        while time.monotonic() < deadline:
            if self.stop_callback():
                return False
            wait_ms = min(250, int((deadline - time.monotonic()) * 1000))
            if wait_ms <= 0:
                break
            self.page.wait_for_timeout(wait_ms)

        return not self.stop_callback()

    def _body_has_marker(self, markers: list[str]) -> bool:
        try:
            return bool(self.page.evaluate(BODY_HAS_MARKER_JS, markers))
        except Exception:
            return False

    def _find_body_marker(self, markers: list[str]) -> str:
        try:
            return str(self.page.evaluate(BODY_FIND_MARKER_JS, markers) or "")
        except Exception:
            return ""

    def _raise_if_comments_disabled(self):
        if self._body_has_marker(["Tắt bình luận", "Tat binh luan"]):
            raise RuntimeError("Bai viet da tat binh luan")

    def _wait_for_rejection_marker(self, timeout_seconds: float = 8.0) -> str:
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        markers = ["Đã bị từ chối", "Từ chối", "Da bi tu choi", "Tu choi"]
        while time.monotonic() < deadline:
            if self.stop_callback():
                raise InterruptedError("Stopped while checking comment rejection")

            marker = self._find_body_marker(markers)
            if marker:
                return marker

            self.page.wait_for_timeout(350)

        return ""

    def _raise_if_comment_rejected(self):
        marker = self._wait_for_rejection_marker()
        if marker:
            raise RuntimeError(f"Binh luan bi Facebook tu choi: {marker}")

    def _find_comment_box(self, timeout_seconds: float = 25.0):
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        scroll_attempts = 0

        while time.monotonic() < deadline:
            if self.stop_callback():
                raise InterruptedError("Stopped while finding comment box")
            self._raise_if_comments_disabled()

            handle = self.page.evaluate_handle(COMMENT_BOX_JS)
            element = handle.as_element()
            if element:
                try:
                    element.scroll_into_view_if_needed(timeout=5000)
                    return element
                except Exception:
                    pass

            scroll_attempts += 1
            if scroll_attempts % 2 == 0:
                self.page.mouse.wheel(0, random.randint(450, 1100))
            self._natural_wait(0.35, 0.9)

        raise RuntimeError("Không tìm thấy ô bình luận trên bài viết")

    def _get_comment_identity_context(self, comment_box) -> str:
        try:
            return str(self.page.evaluate(COMMENT_IDENTITY_CONTEXT_JS, comment_box) or "")
        except Exception:
            return ""

    @staticmethod
    def _normalize_identity_text(value: str) -> str:
        normalized = unicodedata.normalize("NFD", str(value or ""))
        normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
        return " ".join(normalized.replace("đ", "d").replace("Đ", "D").casefold().split())

    def _identity_context_has_comment_marker(self, context: str) -> bool:
        normalized = self._normalize_identity_text(context)
        return any(
            marker in normalized
            for marker in (
                "binh luan duoi ten",
                "binh luan voi tu cach",
                "comment as",
            )
        )

    def _identity_context_is_profile(self, context: str) -> bool:
        profile_name = self._normalize_identity_text(self.account_name)
        normalized_context = self._normalize_identity_text(context)
        if not profile_name or not normalized_context:
            return False

        aliases = [profile_name]
        aliases.extend(part for part in profile_name.split() if len(part) >= 3)
        return any(alias in normalized_context for alias in aliases)

    def _identity_context_is_non_profile(self, context: str) -> bool:
        return self._identity_context_has_comment_marker(context) and not self._identity_context_is_profile(context)

    @classmethod
    def _normalize_page_names(cls, page_names: list[str]) -> list[str]:
        normalized_names = []
        seen = set()
        for name in page_names or []:
            cleaned_name = " ".join(str(name or "").split()).strip()
            if not cleaned_name:
                continue
            key = cls._normalize_identity_text(cleaned_name)
            if not key or key in seen:
                continue
            seen.add(key)
            normalized_names.append(cleaned_name)
        return normalized_names

    def _identity_context_matches_db_page(self, context: str) -> bool:
        if not self._identity_context_has_comment_marker(context):
            return False
        if self._identity_context_is_profile(context):
            return False

        return bool(self._matching_db_page_from_context(context))

    def _matching_db_page_from_context(self, context: str) -> str:
        normalized_context = self._normalize_identity_text(context)
        for page_name in self.page_names:
            if self._normalize_identity_text(page_name) in normalized_context:
                return page_name
        return ""

    def _ensure_comment_identity(self, comment_box):
        if not self.page_names:
            raise RuntimeError("Chua co danh sach page trong DB de chon khi comment")

        current_context = self._get_comment_identity_context(comment_box)
        if self._identity_context_matches_db_page(current_context):
            self.selected_identity_name = self._matching_db_page_from_context(current_context)
            logger.info("Comment identity already selected: identity=%s", self.selected_identity_name)
            return comment_box

        self.status_callback("Chuyen danh tinh comment sang page trong DB")
        logger.info(
            "Switch comment identity to DB page: account_name=%s db_pages=%s current_context=%s",
            self.account_name,
            self.page_names,
            " ".join(current_context.split())[:180],
        )
        self._open_identity_switcher(comment_box)
        selected_identity = self._click_db_page_identity()
        self._wait_identity_switch_completed()

        switched_box = self._find_comment_box(timeout_seconds=30)
        switched_context = self._get_comment_identity_context(switched_box)
        self.selected_identity_name = self._matching_db_page_from_context(switched_context) or selected_identity
        if not self._identity_context_matches_db_page(switched_context):
            logger.warning(
                "Could not verify DB page comment identity after selecting page: selected_identity=%s context=%s",
                selected_identity,
                " ".join(switched_context.split())[:180],
            )

        return switched_box

    def _open_identity_switcher(self, comment_box):
        comment_box.scroll_into_view_if_needed(timeout=5000)
        box = comment_box.bounding_box()
        if not box:
            raise RuntimeError("Không đọc được vị trí ô bình luận để mở đổi danh tính")

        click_points = [
            (box["x"] - 24, box["y"] + box["height"] / 2),
            (box["x"] - 26, box["y"] + box["height"] - 4),
            (box["x"] - 38, box["y"] + box["height"] / 2),
        ]

        last_error = None
        for x, y in click_points:
            if self.stop_callback():
                raise InterruptedError("Stopped while opening identity switcher")
            try:
                self.page.mouse.click(max(4, x), max(4, y))
                self._natural_wait(0.6, 1.2)
                if self._identity_dialog_visible():
                    return
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"Không mở được hộp chọn page/comment identity: {last_error or ''}")

    def _identity_dialog_visible(self) -> bool:
        return self._body_has_marker(
            [
                "Trang & trang cá nhân",
                "Chuyển để tương tác",
                "Trang va trang ca nhan",
                "Chuyen de tuong tac",
            ]
        )

    def _click_db_page_identity(self) -> str:
        try:
            result = self.page.evaluate(
                CLICK_DB_PAGE_IDENTITY_JS,
                {
                    "profileName": self.account_name,
                    "pageNames": self.page_names,
                },
            )
        except Exception as exc:
            raise RuntimeError(f"Khong click duoc page trong DB: {exc}") from exc

        if not isinstance(result, dict) or not result.get("clicked"):
            reason = (result or {}).get("reason") if isinstance(result, dict) else "unknown"
            raise RuntimeError(f"Khong tim thay page trong DB o hop chon danh tinh: {reason}")

        selected_name = str(result.get("name") or "").strip()
        self.selected_identity_name = selected_name
        logger.info("Selected DB page comment identity: %s", selected_name)
        return selected_name

    def _wait_identity_switch_completed(self):
        self._natural_wait(2.0, 4.0)
        try:
            self.page.locator("text=Đang chuyển sang").wait_for(state="hidden", timeout=30000)
        except Exception:
            pass
        self._natural_wait(1.0, 2.2)

    def _type_comment(self, comment_box, message: str):
        self.status_callback("Đang nhập bình luận bằng Chrome")
        comment_box.scroll_into_view_if_needed(timeout=5000)
        comment_box.click(timeout=10000)
        self._natural_wait(0.4, 0.9)

        for character in message:
            if self.stop_callback():
                raise InterruptedError("Stopped while typing comment")
            self.page.keyboard.insert_text(character)
            if character.isspace():
                self._natural_wait(0.12, 0.42)
            else:
                self._natural_wait(
                    FACEBOOK_COMMENT_TYPING_DELAY_MIN_SECONDS,
                    FACEBOOK_COMMENT_TYPING_DELAY_MAX_SECONDS,
                )

    def _submit_comment(self, comment_box):
        self.status_callback("Đang gửi bình luận")
        self.page.keyboard.press("Enter")
        self._natural_wait(2.0, 4.0)

        try:
            self.page.wait_for_function(
                "(el) => !el || !el.isConnected || !(el.innerText || '').trim()",
                arg=comment_box,
                timeout=8000,
            )
        except Exception:
            logger.info("Comment box did not clear after Enter; continuing because Facebook may keep composer state")

        self._raise_if_comment_rejected()

    @staticmethod
    def is_facebook_url(value: str) -> bool:
        try:
            parsed = urlparse(str(value or ""))
            return "facebook.com" in parsed.netloc
        except Exception:
            return False
