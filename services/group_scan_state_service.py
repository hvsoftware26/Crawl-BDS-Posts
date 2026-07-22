from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

from app_config import APP_BASE_DIR


GROUP_SCAN_STATE_PATH = APP_BASE_DIR / "data" / "group_scan_state.json"
GROUP_SCAN_STATE_LOCK = threading.Lock()
MAX_POST_IDS_PER_GROUP = 2000


def normalize_group_state_key(group_id: str) -> str:
    raw_value = str(group_id or "").strip()
    if not raw_value:
        return ""

    if raw_value.isdigit():
        return raw_value

    numeric_match = re.search(r"/groups/(\d+)", raw_value)
    if numeric_match:
        return numeric_match.group(1)

    parsed = urlparse(raw_value if "://" in raw_value else f"https://{raw_value}")
    if parsed.netloc and "." in parsed.netloc:
        path = (parsed.path or "").rstrip("/")
        return f"{parsed.netloc.casefold()}{path.casefold()}"

    return raw_value.rstrip("/").casefold()


def load_processed_post_ids(group_id: str, aliases: list[str] | None = None) -> set[str]:
    keys = _normalized_keys(group_id, aliases)
    if not keys:
        return set()

    with GROUP_SCAN_STATE_LOCK:
        state = _read_state()

    groups = state.get("groups") if isinstance(state, dict) else {}
    processed_ids = set()
    for key in keys:
        group_state = groups.get(key, {}) if isinstance(groups, dict) else {}
        for post_id in group_state.get("post_ids", []) if isinstance(group_state, dict) else []:
            normalized_post_id = str(post_id or "").strip()
            if normalized_post_id:
                processed_ids.add(normalized_post_id)
    return processed_ids


def remember_processed_posts(
    group_id: str,
    posts: list[dict],
    aliases: list[str] | None = None,
    max_post_ids: int = MAX_POST_IDS_PER_GROUP,
) -> int:
    post_ids = []
    seen = set()
    for post in posts or []:
        post_id = str((post or {}).get("id") or "").strip()
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        post_ids.append(post_id)

    if not post_ids:
        return 0

    keys = _normalized_keys(group_id, aliases)
    if not keys:
        return 0

    with GROUP_SCAN_STATE_LOCK:
        state = _read_state()
        groups = state.setdefault("groups", {})
        merged_ids = _merge_group_post_ids(groups, keys, post_ids, max_post_ids)
        updated_at = datetime.now(timezone.utc).isoformat()

        for key in keys:
            group_state = groups.get(key, {})
            if not isinstance(group_state, dict):
                group_state = {}
            group_state.update(
                {
                    "post_ids": merged_ids,
                    "last_seen_post_id": post_ids[0],
                    "updated_at": updated_at,
                }
            )
            groups[key] = group_state

        _write_state(state)

    return len(post_ids)


def update_group_scan_metadata(
    group_id: str,
    aliases: list[str] | None = None,
    group_url: str | None = None,
    status: str | None = None,
    valid_posts_count: int | None = None,
    scroll_count: int | None = None,
    reload_count: int | None = None,
    last_graphql_response_at: str | None = None,
    stop_reason: str | None = None,
    error: str | None = None,
) -> None:
    keys = _normalized_keys(group_id, aliases)
    if not keys:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    with GROUP_SCAN_STATE_LOCK:
        state = _read_state()
        groups = state.setdefault("groups", {})
        for key in keys:
            group_state = groups.get(key, {})
            if not isinstance(group_state, dict):
                group_state = {}
                groups[key] = group_state
            else:
                groups.setdefault(key, group_state)
            if group_url is not None:
                group_state["group_url"] = group_url
            if status is not None:
                group_state["status"] = status
            if valid_posts_count is not None:
                group_state["valid_posts_count"] = int(valid_posts_count)
            if scroll_count is not None:
                group_state["scroll_count"] = int(scroll_count)
            if reload_count is not None:
                group_state["reload_count"] = int(reload_count)
            if last_graphql_response_at is not None:
                group_state["last_graphql_response_at"] = last_graphql_response_at
            if stop_reason is not None:
                group_state["stop_reason"] = stop_reason
            if error is not None:
                group_state["error"] = error
            elif "error" in group_state and status in ("running", "completed"):
                group_state.pop("error", None)
            group_state["updated_at"] = now_iso

        _write_state(state)


def _normalized_keys(group_id: str, aliases: list[str] | None = None) -> list[str]:
    values = [group_id]
    values.extend(aliases or [])

    keys = []
    seen = set()
    for value in values:
        key = normalize_group_state_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _read_state() -> dict:
    if not GROUP_SCAN_STATE_PATH.exists():
        return {"groups": {}}

    try:
        with open(GROUP_SCAN_STATE_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {"groups": {}}

    if not isinstance(payload, dict):
        return {"groups": {}}
    if not isinstance(payload.get("groups"), dict):
        payload["groups"] = {}
    return payload


def _write_state(state: dict):
    GROUP_SCAN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = GROUP_SCAN_STATE_PATH.with_name(f"{GROUP_SCAN_STATE_PATH.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
    temp_path.replace(GROUP_SCAN_STATE_PATH)


def _merge_group_post_ids(
    groups: dict,
    keys: list[str],
    new_post_ids: list[str],
    max_post_ids: int,
) -> list[str]:
    merged = []
    seen = set()

    for post_id in new_post_ids:
        if post_id in seen:
            continue
        seen.add(post_id)
        merged.append(post_id)

    for key in keys:
        group_state = groups.get(key, {})
        if not isinstance(group_state, dict):
            existing_ids = []
        else:
            existing_ids = group_state.get("post_ids", [])
        for post_id in existing_ids:
            normalized_post_id = str(post_id or "").strip()
            if not normalized_post_id or normalized_post_id in seen:
                continue
            seen.add(normalized_post_id)
            merged.append(normalized_post_id)

    return merged[: max(1, int(max_post_ids or MAX_POST_IDS_PER_GROUP))]
