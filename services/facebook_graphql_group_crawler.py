from __future__ import annotations

import hashlib
import json
import queue
import random
import re
import threading
import time
from datetime import datetime, timezone
from logging import getLogger
from typing import Any

from app_config import (
    GRAPHQL_GROUP_IDLE_TIMEOUT_SECONDS,
    GRAPHQL_GROUP_MAX_SCROLLS,
    GRAPHQL_GROUP_NO_HEIGHT_CHANGE_LIMIT,
    GRAPHQL_GROUP_POST_LIMIT,
    GRAPHQL_GROUP_SCROLL_DELAY_MAX_SECONDS,
    GRAPHQL_GROUP_SCROLL_DELAY_MIN_SECONDS,
    GRAPHQL_GROUP_SCROLL_DELAY_SECONDS,
)
from services.group_scan_state_service import (
    normalize_group_state_key,
    update_group_scan_metadata,
)
from utils.time_utils import DISPLAY_DATE_FORMAT, HANOI_TIMEZONE

logger = getLogger(__name__)

POST_ID_KEYS = (
    "legacy_story_hideable_id",
    "post_id",
    "story_fbid",
    "subscription_target_id",
)
TIME_KEYS = (
    "created_time",
    "creation_time",
    "publish_time",
    "publish_time_utc",
    "timestamp",
    "creation_timestamp",
)
MESSAGE_CONTAINER_KEYS = (
    "message",
    "message_text",
    "body",
    "text",
    "text_with_entities",
    "title",
    "title_with_entities",
)
GRAPHQL_POST_RESPONSE_MARKERS = (
    '"group_feed"',
    "GroupsCometFeedRegularStories",
    '"path":["node","group_feed"]',
    '"path": ["node", "group_feed"]',
)


def _clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\\n", "\n").replace("\\r", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_probably_ui_text(text: str) -> bool:
    lowered = text.casefold()
    blocked = {
        "like",
        "comment",
        "share",
        "thich",
        "binh luan",
        "chia se",
        "xem them",
        "see more",
        "join group",
        "tham gia nhom",
    }
    return lowered in blocked or lowered.startswith("http")


def _iter_json_payloads(text: str):
    raw_text = str(text or "").strip()
    if not raw_text:
        return

    if raw_text.startswith("for (;;);"):
        raw_text = raw_text[len("for (;;);") :].strip()

    try:
        yield json.loads(raw_text)
        return
    except ValueError:
        pass

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("for (;;);"):
            line = line[len("for (;;);") :].strip()
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _coerce_post_id(value: Any) -> str:
    if value is None:
        return ""
    post_id = str(value).strip().strip('"').strip("'")
    if not post_id or post_id.lower() in {"null", "none"}:
        return ""
    return post_id


def _extract_post_id(node: dict) -> str:
    for key in POST_ID_KEYS:
        post_id = _coerce_post_id(node.get(key))
        if post_id:
            return post_id
    return ""


def _extract_text_from_container(value: Any, fallback: bool = False) -> str:
    if isinstance(value, str):
        text = _clean_text(value)
        if text and (fallback or not _is_probably_ui_text(text)):
            return text
        return ""

    if isinstance(value, dict):
        for key in ("text", "plain_text", "__html"):
            text = _extract_text_from_container(value.get(key), fallback=fallback)
            if text:
                return text

        for key in MESSAGE_CONTAINER_KEYS:
            if key in value:
                text = _extract_text_from_container(value.get(key), fallback=fallback)
                if text:
                    return text

    if isinstance(value, list):
        for item in value:
            text = _extract_text_from_container(item, fallback=fallback)
            if text:
                return text

    return ""


def _extract_message(node: dict) -> str:
    for key in MESSAGE_CONTAINER_KEYS:
        if key not in node:
            continue
        text = _extract_text_from_container(node.get(key))
        if text:
            return text

    candidates = []
    for child in _iter_dicts(node):
        for key in ("text", "plain_text"):
            text = _extract_text_from_container(child.get(key), fallback=True)
            if len(text) >= 12 and not _is_probably_ui_text(text):
                candidates.append(text)

    if not candidates:
        return ""

    return max(candidates, key=len)


def _format_created_time(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000.0
        try:
            return (
                datetime.fromtimestamp(timestamp, timezone.utc)
                .astimezone(HANOI_TIMEZONE)
                .strftime(DISPLAY_DATE_FORMAT)
            )
        except (OSError, OverflowError, ValueError):
            return None

    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    if re.fullmatch(r"\d+(\.\d+)?", raw_value):
        try:
            return _format_created_time(float(raw_value))
        except ValueError:
            return None

    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed_time = datetime.fromisoformat(normalized)
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        return parsed_time.astimezone(HANOI_TIMEZONE).strftime(DISPLAY_DATE_FORMAT)
    except ValueError:
        pass

    for date_format in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed_time = datetime.strptime(raw_value, date_format)
            if parsed_time.tzinfo is None:
                parsed_time = parsed_time.replace(tzinfo=timezone.utc)
            return parsed_time.astimezone(HANOI_TIMEZONE).strftime(DISPLAY_DATE_FORMAT)
        except ValueError:
            continue

    return None


def _extract_created_time(node: dict) -> str | None:
    for key in TIME_KEYS:
        if key not in node:
            continue
        created_time = _format_created_time(node.get(key))
        if created_time:
            return created_time

    for child in _iter_dicts(node):
        for key in TIME_KEYS:
            if key not in child:
                continue
            created_time = _format_created_time(child.get(key))
            if created_time:
                return created_time

    return None


def _is_post_url(value: str) -> bool:
    lowered = str(value or "").casefold()
    return "facebook.com" in lowered and ("/posts/" in lowered or "/permalink/" in lowered)


def _extract_post_url(node: dict) -> str:
    for key in ("permalink_url", "wwwURL", "www_url", "shareable_url", "url"):
        value = str(node.get(key) or "").strip()
        if _is_post_url(value):
            return value

    fallback_url = ""
    for child in _iter_dicts(node):
        for key in ("permalink_url", "wwwURL", "www_url", "shareable_url", "url"):
            value = str(child.get(key) or "").strip()
            if _is_post_url(value):
                return value
            if not fallback_url and "facebook.com" in value:
                fallback_url = value

    return fallback_url


def _iter_group_feed_story_nodes(payload: Any):
    if not isinstance(payload, dict):
        return

    data = payload.get("data")
    if not isinstance(data, dict):
        return

    node = data.get("node")
    if isinstance(node, dict) and node.get("__typename") == "Group":
        group_feed = node.get("group_feed")
        if isinstance(group_feed, dict):
            for edge in group_feed.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                story_node = edge.get("node")
                if isinstance(story_node, dict) and story_node.get("__typename") == "Story":
                    yield story_node

    if payload.get("path") == ["node", "group_feed"]:
        for edge in data.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            story_node = edge.get("node")
            if isinstance(story_node, dict) and story_node.get("__typename") == "Story":
                yield story_node


def _extract_actor_info(node: dict) -> tuple[str, str]:
    actors = node.get("actors")
    if not isinstance(actors, list):
        for child in _iter_dicts(node):
            child_actors = child.get("actors")
            if isinstance(child_actors, list) and child_actors:
                actors = child_actors
                break

    if not isinstance(actors, list) or not actors:
        return "", ""

    actor = actors[0] if isinstance(actors[0], dict) else {}
    return str(actor.get("id") or "").strip(), str(actor.get("name") or "").strip()


def _post_from_story_node(node: dict, group_id: str) -> dict | None:
    post_id = _extract_post_id(node)
    if not post_id:
        return None

    author_id, author_name = _extract_actor_info(node)
    return {
        "id": post_id,
        "post_id": post_id,
        "message": _extract_message(node),
        "created_time": _extract_created_time(node),
        "url": _extract_post_url(node) or _build_fallback_post_url(group_id, post_id),
        "group_id": group_id,
        "author_id": author_id,
        "author_name": author_name,
    }


def _extract_group_path_id(group_id: str) -> str:
    match = re.search(r"/groups/([^/?#]+)", str(group_id or ""))
    if match:
        return match.group(1).strip("/")
    return str(group_id or "").strip()


def _build_fallback_post_url(group_id: str, post_id: str) -> str:
    group_path_id = _extract_group_path_id(group_id)
    if group_path_id and re.fullmatch(r"\d+", group_path_id):
        return f"https://www.facebook.com/groups/{group_path_id}/posts/{post_id}/"
    return f"https://www.facebook.com/{post_id}"


def _fallback_post_key(group_id: str, post: dict) -> str:
    stable_parts = [
        str(group_id or ""),
        str(post.get("url") or ""),
        str(post.get("created_time") or ""),
        str(post.get("message") or "")[:160],
    ]
    digest = hashlib.sha1("|".join(stable_parts).encode("utf-8", errors="ignore")).hexdigest()
    return f"fallback_{digest[:20]}"


def parse_graphql_posts_from_text(text: str, group_id: str = "") -> list[dict]:
    posts = []
    seen_ids = set()

    for payload in _iter_json_payloads(text):
        for story_node in _iter_group_feed_story_nodes(payload):
            post = _post_from_story_node(story_node, group_id)
            post_id = str((post or {}).get("id") or "").strip()
            if not post or not post_id or post_id in seen_ids:
                continue
            posts.append(post)
            seen_ids.add(post_id)

    return posts


def _has_group_feed_story_edges(text: str) -> bool:
    for payload in _iter_json_payloads(text):
        if any(True for _story_node in _iter_group_feed_story_nodes(payload)):
            return True
    return False


class FacebookGraphQLGroupCrawler:
    def __init__(
        self,
        browser_context,
        group_url: str,
        processed_post_ids: set[str] | None = None,
        max_posts: int = GRAPHQL_GROUP_POST_LIMIT,
        max_scrolls: int = GRAPHQL_GROUP_MAX_SCROLLS,
        idle_timeout_seconds: float = GRAPHQL_GROUP_IDLE_TIMEOUT_SECONDS,
        scroll_delay_seconds: float = GRAPHQL_GROUP_SCROLL_DELAY_SECONDS,
        no_height_change_limit: int = GRAPHQL_GROUP_NO_HEIGHT_CHANGE_LIMIT,
        status_callback=None,
        stop_callback=None,
    ):
        self.browser_context = browser_context
        self.group_url = str(group_url or "").strip()
        self.group_key = normalize_group_state_key(self.group_url) or self.group_url
        self.processed_post_ids = set(processed_post_ids or set())
        self.seen_post_ids = set()
        self.max_posts = max(1, int(max_posts or GRAPHQL_GROUP_POST_LIMIT))
        self.max_scrolls = max(1, int(max_scrolls or GRAPHQL_GROUP_MAX_SCROLLS))
        self.idle_timeout_seconds = max(1.0, float(idle_timeout_seconds or GRAPHQL_GROUP_IDLE_TIMEOUT_SECONDS))
        self.scroll_delay_seconds = max(0.2, float(scroll_delay_seconds or GRAPHQL_GROUP_SCROLL_DELAY_SECONDS))
        self.no_height_change_limit = max(1, int(no_height_change_limit or GRAPHQL_GROUP_NO_HEIGHT_CHANGE_LIMIT))
        self.status_callback = status_callback or (lambda _message: None)
        self.stop_callback = stop_callback or (lambda: False)

        self.page = None
        self.response_queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self.response_signatures = set()
        self.response_lock = threading.Lock()
        self.listener_active = False
        self.stop_scanning = False
        self.stop_reason = None
        self.scroll_count = 0
        self.last_graphql_monotonic = None
        self.last_graphql_response_at = None
        self.collected_posts = []

    def _set_stop_reason(self, reason: str):
        if not self.stop_reason:
            self.stop_reason = reason
        self.stop_scanning = True

    def _emit_progress(self, final: bool = False):
        prefix = "Đã quét" if final else "Đang quét"
        self.status_callback(f"{prefix} {len(self.collected_posts)}/{self.max_posts} bài")

    def _state_update(self, status: str, error: str | None = None):
        update_group_scan_metadata(
            self.group_key,
            aliases=[self.group_url],
            group_url=self.group_url,
            status=status,
            valid_posts_count=len(self.collected_posts),
            scroll_count=self.scroll_count,
            last_graphql_response_at=self.last_graphql_response_at,
            stop_reason=self.stop_reason,
            error=error,
        )

    def _log(self, message: str):
        logger.info("[Group %s] %s", self.group_key, message)

    def _is_graphql_post_response(self, response, text: str) -> bool:
        url = str(getattr(response, "url", "") or "").lower()
        if "/api/graphql" not in url and "graphql" not in url:
            return False

        status = int(getattr(response, "status", 0) or 0)
        if status and status >= 400:
            return False

        body = str(text or "")
        if not body:
            return False

        body_lower = body.casefold()
        if not any(marker.casefold() in body_lower for marker in GRAPHQL_POST_RESPONSE_MARKERS):
            return False

        return _has_group_feed_story_edges(body)

    def _on_response(self, response):
        with self.response_lock:
            if not self.listener_active or self.stop_scanning or self.stop_callback():
                return

        if "graphql" not in str(getattr(response, "url", "") or "").lower():
            return

        try:
            text = response.text()
        except Exception as exc:
            logger.warning("[Group %s] Could not read GraphQL response body: %s", self.group_key, exc)
            return

        if not text:
            return

        if not self._is_graphql_post_response(response, text):
            return

        signature = hashlib.sha1(
            (str(response.url) + "\n" + text).encode("utf-8", errors="ignore")
        ).hexdigest()

        with self.response_lock:
            if signature in self.response_signatures or self.stop_scanning:
                return
            self.response_signatures.add(signature)
            received_at = datetime.now(HANOI_TIMEZONE).isoformat()
            self.last_graphql_response_at = received_at
            self.last_graphql_monotonic = time.monotonic()
            self.response_queue.put((str(response.url), text, received_at))

        logger.info("[Group %s] Captured Group feed GraphQL response: bytes=%s", self.group_key, len(text))

    def _drain_response_queue(self):
        while not self.stop_scanning:
            try:
                response_url, text, received_at = self.response_queue.get_nowait()
            except queue.Empty:
                return

            try:
                parsed_posts = parse_graphql_posts_from_text(text, group_id=self.group_url)
                stats = self._ingest_posts(parsed_posts)
                logger.info(
                    "[Group %s] Group feed GraphQL response: posts=%s added=%s duplicate=%s progress=%s/%s url=%s",
                    self.group_key,
                    len(parsed_posts),
                    stats["added"],
                    stats["duplicate"],
                    len(self.collected_posts),
                    self.max_posts,
                    response_url,
                )
                self.last_graphql_response_at = received_at
                if len(self.collected_posts) >= self.max_posts:
                    self._set_stop_reason("collected_enough_posts")
                self._state_update("running")
            except Exception as exc:
                logger.exception("[Group %s] GraphQL parse error: %s", self.group_key, exc)

    def _ingest_posts(self, posts: list[dict]) -> dict:
        stats = {
            "added": 0,
            "duplicate": 0,
        }

        for post in posts or []:
            if self.stop_scanning or self.stop_callback():
                self._set_stop_reason("user_stop")
                break

            post_id = str(post.get("id") or "").strip()
            if not post_id:
                post_id = _fallback_post_key(self.group_url, post)

            post["id"] = post_id
            post["post_id"] = post_id
            post["group_id"] = self.group_url

            if post_id in self.processed_post_ids or post_id in self.seen_post_ids:
                stats["duplicate"] += 1
                continue

            self.seen_post_ids.add(post_id)
            self.collected_posts.append(post)
            stats["added"] += 1

            progress = f"{len(self.collected_posts)}/{self.max_posts}"
            logger.info("[Group %s] Progress: %s", self.group_key, progress)
            self._emit_progress()

            if len(self.collected_posts) >= self.max_posts:
                self._set_stop_reason("collected_enough_posts")
                break

        return stats

    def _wait_with_stop(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline:
            if self.stop_callback() or self.stop_scanning:
                return False
            wait_ms = min(250, int((deadline - time.monotonic()) * 1000))
            if wait_ms <= 0:
                break
            self.page.wait_for_timeout(wait_ms)
            self._drain_response_queue()
        return not self.stop_callback() and not self.stop_scanning

    def _next_scroll_delay(self) -> float:
        min_delay = max(0.4, float(GRAPHQL_GROUP_SCROLL_DELAY_MIN_SECONDS))
        max_delay = max(min_delay + 0.2, float(GRAPHQL_GROUP_SCROLL_DELAY_MAX_SECONDS))
        return random.uniform(min_delay, max_delay)

    def _scroll_once(self) -> dict:
        before_metrics = self._read_scroll_metrics()
        before = {
            "beforeTop": int(before_metrics.get("scrollTop") or 0),
            "beforeHeight": int(before_metrics.get("scrollHeight") or 0),
            "viewportHeight": int(before_metrics.get("viewportHeight") or 0),
        }

        try:
            viewport = self.page.viewport_size or {}
            width = int(viewport.get("width") or 500)
            height = int(viewport.get("height") or 720)
            self.page.mouse.move(
                random.randint(80, max(81, width - 60)),
                random.randint(160, max(161, height - 140)),
            )

            self.page.evaluate(
                """
                () => {
                    const doc = document.scrollingElement || document.documentElement || document.body;
                    const bodyHeight = document.body ? document.body.scrollHeight : 0;
                    const docHeight = doc ? doc.scrollHeight : 0;
                    const viewportHeight = window.innerHeight || 700;
                    const baseAmount = Math.max(bodyHeight, docHeight, viewportHeight * 3);
                    const jitter = 0.82 + Math.random() * 0.43;
                    window.scrollBy({
                        top: baseAmount * jitter,
                        left: 0,
                        behavior: "smooth"
                    });
                }
                """
            )
            self.page.wait_for_timeout(random.randint(180, 520))
            self._drain_response_queue()

            if not self.stop_scanning and random.random() < 0.18:
                self.page.mouse.wheel(0, random.randint(120, 360))
                self.page.wait_for_timeout(random.randint(120, 320))

            return before
        except Exception as exc:
            logger.warning("[Group %s] Scroll evaluate failed, fallback to mouse wheel: %s", self.group_key, exc)
            try:
                self.page.mouse.wheel(0, random.randint(900, 1700))
            except Exception:
                pass
            return before

    def _read_scroll_metrics(self) -> dict:
        try:
            return self.page.evaluate(
                """
                () => {
                    const doc = document.scrollingElement || document.documentElement || document.body;
                    const scrollTop = doc.scrollTop || window.scrollY || 0;
                    const scrollHeight = doc.scrollHeight || document.body.scrollHeight || 0;
                    const viewportHeight = window.innerHeight || 0;
                    return {
                        scrollTop,
                        scrollHeight,
                        viewportHeight,
                        atBottom: scrollTop + viewportHeight >= scrollHeight - 8
                    };
                }
                """
            )
        except Exception:
            return {"scrollTop": 0, "scrollHeight": 0, "viewportHeight": 0, "atBottom": False}

    def collect(self) -> dict:
        if not self.browser_context:
            raise RuntimeError("Missing Playwright browser context for GraphQL group crawler")
        if not self.group_url:
            raise ValueError("group_url is required")

        self._log("Start GraphQL scan")
        self._emit_progress()
        self._state_update("running")
        started_at = time.monotonic()
        no_height_change_count = 0

        try:
            self.page = self.browser_context.new_page()
            self.page.set_viewport_size({"width": 500, "height": 700})
            self.page.set_default_timeout(30000)
            self.page.set_default_navigation_timeout(60000)
            self.listener_active = True
            self.page.on("response", self._on_response)

            self.page.goto(self.group_url, wait_until="domcontentloaded", timeout=60000)
            self._wait_with_stop(random.uniform(2.5, 4.5))
            self._drain_response_queue()

            while not self.stop_scanning:
                if self.stop_callback():
                    self._set_stop_reason("user_stop")
                    break

                if len(self.collected_posts) >= self.max_posts:
                    self._set_stop_reason("collected_enough_posts")
                    break

                if self.scroll_count >= self.max_scrolls:
                    self._set_stop_reason("max_scrolls_reached")
                    break

                last_response = self.last_graphql_monotonic or started_at
                if time.monotonic() - last_response >= self.idle_timeout_seconds and self.scroll_count > 0:
                    self._set_stop_reason("graphql_idle_timeout")
                    break

                response_before_scroll = self.last_graphql_monotonic
                before = self._scroll_once()
                if self.stop_scanning:
                    break

                self.scroll_count += 1
                self._state_update("running")

                if not self._wait_with_stop(self._next_scroll_delay()):
                    if not self.stop_reason:
                        self._set_stop_reason("user_stop")
                    break

                self._drain_response_queue()
                after = self._read_scroll_metrics()
                has_new_response = (
                    self.last_graphql_monotonic is not None
                    and self.last_graphql_monotonic != response_before_scroll
                )
                if (
                    not has_new_response
                    and int(after.get("scrollHeight") or 0) <= int(before.get("beforeHeight") or 0)
                    and after.get("atBottom")
                ):
                    no_height_change_count += 1
                else:
                    no_height_change_count = 0

                if no_height_change_count >= self.no_height_change_limit:
                    self._set_stop_reason("page_not_loading_more")
                    break

            self._drain_response_queue()
            if not self.stop_reason:
                self.stop_reason = "completed"

            self._log(f"Stop scrolling: {self.stop_reason}; Progress: {len(self.collected_posts)}/{self.max_posts}")
            self._emit_progress(final=True)
            status = "stopped" if self.stop_reason == "user_stop" else "completed"
            self._state_update(status)
            return {
                "group_id": self.group_url,
                "state_group_id": self.group_key,
                "total_posts": len(self.collected_posts),
                "posts": list(self.collected_posts),
                "scroll_count": self.scroll_count,
                "last_graphql_response_at": self.last_graphql_response_at,
                "stop_reason": self.stop_reason,
            }
        except Exception as exc:
            self.stop_reason = self.stop_reason or "error"
            self._state_update("error", error=str(exc))
            logger.exception("[Group %s] GraphQL group scan failed: %s", self.group_key, exc)
            raise
        finally:
            self.listener_active = False
            if self.page:
                try:
                    self.page.remove_listener("response", self._on_response)
                except Exception as exc:
                    logger.warning("[Group %s] Could not remove GraphQL listener: %s", self.group_key, exc)
                try:
                    self.page.close()
                except Exception as exc:
                    logger.warning("[Group %s] Could not close group page: %s", self.group_key, exc)
                self.page = None
