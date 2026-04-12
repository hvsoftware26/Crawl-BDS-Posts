# Scan controller
import json
from logging import getLogger
from pathlib import Path

from services.scheduler_service import ScheduleService
from workers.scan_groups_worker import ScanGroups

logger = getLogger(__name__)
POSTS_JSON_PATH = Path(__file__).resolve().parents[1] / "data" / "posts.json"


class ScanController:
    def __init__(
        self,
        groups_list,
        delay,
        keywords,
        account_token=None,
        account_cookies=None,
        proxies=None,
        API_KEY=None,
        token_tele=None,
        idchat=None,
        prompt=None,
        max_length_text: int = 500,
        progress_callback=None,
        status_callback=None,
        post_callback=None,

    ):
        self.groups_list = groups_list
        self.delay = delay
        self.keywords = keywords
        self.account_token = account_token
        self.account_cookies = account_cookies
        self.proxies = proxies
        self.API_KEY = API_KEY
        self.token_tele = token_tele
        self.idchat = idchat
        self.prompt = prompt
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.post_callback = post_callback
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
        POSTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Writing posts JSON: path=%s posts_count=%s valid_posts=%s invalid_posts=%s",
            POSTS_JSON_PATH,
            len(posts_status or []),
            sum(1 for post in (posts_status or []) if post.get("status") == 1),
            sum(1 for post in (posts_status or []) if post.get("status") == 0),
        )
        with open(POSTS_JSON_PATH, "w", encoding="utf-8") as file:
            json.dump(posts_status, file, ensure_ascii=False, indent=4)
        logger.info("Finished writing posts JSON to %s", POSTS_JSON_PATH)

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
            proxies=self.proxies,
            API_KEY=self.API_KEY,
            token_tele=self.token_tele,
            idchat=self.idchat,
            prompt=self.prompt,
            max_length_text=self.max_length_text,
            progress_callback=self.progress_callback,
            status_callback = self.status_callback,
            post_callback = self.post_callback,
        )

        posts_status = scan_groups_worker.get_groups()
        self._write_posts_json(posts_status)
        return posts_status
