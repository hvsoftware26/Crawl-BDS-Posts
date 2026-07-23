# Scan controller
import json
import threading
from logging import getLogger
from pathlib import Path

from services.scheduler_service import ScheduleService
from workers.scan_groups_worker import ScanGroups

logger = getLogger(__name__)
POSTS_JSON_PATH = Path(__file__).resolve().parents[1] / "data" / "posts.json"
POSTS_JSON_LOCK = threading.Lock()


def _post_key(post: dict) -> tuple[str, str]:
    return (
        str((post or {}).get("group_id") or ""),
        str((post or {}).get("id") or ""),
    )


def _merge_posts_status(existing_posts: list[dict], incoming_posts: list[dict]) -> list[dict]:
    merged_posts = []
    index_by_key = {}

    for post in existing_posts or []:
        if not isinstance(post, dict):
            continue

        key = _post_key(post)
        if not key[1]:
            continue

        index_by_key[key] = len(merged_posts)
        merged_posts.append(post)

    for post in incoming_posts or []:
        if not isinstance(post, dict):
            continue

        key = _post_key(post)
        if not key[1]:
            continue

        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(merged_posts)
            merged_posts.append(post)
        else:
            merged_posts[existing_index] = post

    return merged_posts


def _read_posts_json() -> list[dict]:
    if not POSTS_JSON_PATH.exists():
        return []

    try:
        with open(POSTS_JSON_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read posts JSON for merge: path=%s error=%s", POSTS_JSON_PATH, exc)
        return []

    return payload if isinstance(payload, list) else []


def _atomic_write_posts_json(posts_status: list[dict]):
    POSTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = POSTS_JSON_PATH.with_name(f"{POSTS_JSON_PATH.name}.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(posts_status, file, ensure_ascii=False, indent=4)
    temp_path.replace(POSTS_JSON_PATH)


def reset_posts_json():
    with POSTS_JSON_LOCK:
        _atomic_write_posts_json([])


class ScanController:
    def __init__(
        self,
        groups_list,
        delay,
        keywords,
        account_token=None,
        account_cookies=None,
        account_name=None,
        account_page_names=None,
        proxies=None,
        API_KEY=None,
        token_tele=None,
        idchat=None,
        prompt=None,
        prompt_cmt=None,
        prompt_cmt_mode="text",
        max_length_text: int = 500,
        progress_callback=None,
        status_callback=None,
        post_callback=None,
        stop_callback=None,
        console_callback=None,
        browser_context=None,
        browser_restart_callback=None,

    ):
        self.groups_list = groups_list
        self.delay = delay
        self.keywords = keywords
        self.account_token = account_token
        self.account_cookies = account_cookies
        self.account_name = account_name
        self.account_page_names = account_page_names or []
        self.proxies = proxies
        self.API_KEY = API_KEY
        self.token_tele = token_tele
        self.idchat = idchat
        self.prompt = prompt
        self.prompt_cmt = prompt_cmt
        self.prompt_cmt_mode = prompt_cmt_mode
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.post_callback = post_callback
        self.stop_callback = stop_callback
        self.console_callback = console_callback
        self.browser_context = browser_context
        self.browser_restart_callback = browser_restart_callback
        self.schedule_service = ScheduleService()
        logger.debug(
            "Initialized ScanController: groups=%s delay_hours=%s keywords=%s has_token=%s has_cookies=%s has_proxies=%s has_api_key=%s",
            len(groups_list or []),
            delay,
            len(keywords or []),
            bool(account_token),
            bool(account_cookies),
            bool(proxies),
            bool(API_KEY),
        )

    def _write_posts_json(self, posts_status: list[dict]):
        incoming_posts = posts_status or []
        with POSTS_JSON_LOCK:
            existing_posts = _read_posts_json()
            merged_posts = _merge_posts_status(existing_posts, incoming_posts)
            logger.info(
                "Writing merged posts JSON: path=%s existing=%s incoming=%s merged=%s valid_posts=%s invalid_posts=%s",
                POSTS_JSON_PATH,
                len(existing_posts),
                len(incoming_posts),
                len(merged_posts),
                sum(1 for post in merged_posts if post.get("status") == 1),
                sum(1 for post in merged_posts if post.get("status") == 0),
            )
            _atomic_write_posts_json(merged_posts)
        logger.info("Finished writing merged posts JSON to %s", POSTS_JSON_PATH)

    def start_scan(self):
        logger.info(
            "Starting scan controller flow: groups_count=%s delay_hours=%s",
            len(self.groups_list or []),
            self.delay,
        )

        group_schedule = self.schedule_service.build_posts_schedule(
            groups_count=len(self.groups_list or []),
            cycle_time=self.delay,
        )
        delay_next_run = group_schedule["delay_minutes"]

        scan_groups_worker = ScanGroups(
            groups_list=self.groups_list,
            delay = self.delay,
            keywords=self.keywords,
            account_token=self.account_token,
            account_cookies=self.account_cookies,
            account_name=self.account_name,
            account_page_names=self.account_page_names,
            proxies=self.proxies,
            API_KEY=self.API_KEY,
            token_tele=self.token_tele,
            idchat=self.idchat,
            prompt=self.prompt,
            prompt_cmt=self.prompt_cmt,
            prompt_cmt_mode=self.prompt_cmt_mode,
            max_length_text=self.max_length_text,
            progress_callback=self.progress_callback,
            status_callback = self.status_callback,
            post_callback = self.post_callback,
            stop_callback = self.stop_callback,
            console_callback = self.console_callback,
            browser_context = self.browser_context,
            browser_restart_callback=self.browser_restart_callback,
        )

        posts_status = scan_groups_worker.get_groups()
        self._write_posts_json(posts_status)
        return posts_status
