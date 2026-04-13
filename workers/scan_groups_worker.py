# Scan groups worker thread
from logging import getLogger

from integrations.telegram_client import send_document, send_message
from services.group_service import GroupService
from utils.excel_utils import build_group_posts_excel

logger = getLogger(__name__)


class ScanGroups:
    total_posts_scanned = 0
    def __init__(
        self,
        groups_list: list[str],
        delay: int,
        keywords: list[str],
        account_token: str = None,
        account_cookies: str = None,
        proxies: dict = None,
        API_KEY: str = None,
        token_tele: str = None,
        idchat: str = None,
        prompt: str = None,
        max_length_text:int = 500,
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
        self.prompt = prompt
        self.token_tele = token_tele
        self.idchat = idchat
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.post_callback = post_callback

        logger.debug(
            "Initialized ScanGroups worker: groups=%s delay=%s keywords=%s has_proxies=%s has_api_key=%s",
            len(groups_list or []),
            delay,
            len(keywords or []),
            bool(proxies),
            bool(API_KEY),
        )

    def _send_group_report(self, group_summary: dict,send_type:int ):
        valid_posts = [
            post
            for post in (group_summary.get("posts_status") or [])
            if post.get("status") == 1
        ]

        if not valid_posts:
            logger.info(
                "Skipping Telegram report because there are no valid posts: group_id=%s",
                group_summary.get("group_id"),
            )
            return

        if not self.token_tele or not self.idchat:
            logger.info(
                "Skipping Telegram report because token_tele or idchat is missing: group_id=%s",
                group_summary.get("group_id"),
            )
            return
        if send_type == 0:
            message_summary = (
                f"Nhóm: https://www.facebook.com/{group_summary.get('group_id')}\n"
                f"Số bài đã phân tích: {len(valid_posts)}\n"
                "=======================================\n"
            )
        else:
            message_summary = (
                f">>>KẾT QUẢ SAU 1 CHU KỲ<<< "
                f"Số bài đã phân tích: {len(valid_posts)}\n"
                "=======================================\n"
            )
        ScanGroups.total_posts_scanned += len(valid_posts)

        self.post_callback(ScanGroups.total_posts_scanned)

        try:
            send_message(message_summary, self.token_tele, self.idchat)
            logger.info("Sent Telegram summary for group_id=%s", group_summary.get("group_id"))
        except Exception as e:
            logger.exception("Failed to send Telegram message: %s", e)

        try:
            excel_file_path = build_group_posts_excel(
                group_id=group_summary.get("group_id"),
                posts=valid_posts,
            )
            logger.info("Excel exported: %s", excel_file_path)
        except Exception as e:
            logger.exception("Failed to export Excel for group_id=%s: %s", group_summary.get("group_id"), e)
            return

        try:
            send_document(
                file_path=excel_file_path,
                token_tele=self.token_tele,
                idchat=self.idchat,
                caption=f">>> File kết quả của Group {group_summary.get('group_id')} <<<" if send_type == 0 else f">>> File kết quả của các groups <<<",
            )
            logger.info("Sent Telegram Excel report for group_id=%s", group_summary.get("group_id"))
            self.status_callback(f"Đã gửi thông báo về Telegram")
        except Exception as e:
            logger.exception("Failed to send Telegram document for group_id=%s: %s", group_summary.get("group_id"), e)

    def get_groups(self):
        logger.info(
            "Starting ScanGroups worker for groups_count=%s",
            len(self.groups_list or []),
        )
        group_service = GroupService(
            groups_list=self.groups_list,
            delay_next_run=self.delay,
            keywords=self.keywords,
            account_token=self.account_token,
            account_cookies=self.account_cookies,
            proxies=self.proxies,
            API_KEY=self.API_KEY,
            prompt = self.prompt,
            max_length_text= self.max_length_text,
            status_callback = self.status_callback,
            post_callback = self.post_callback,
            progress_callback = self.progress_callback,
        )
        posts_status = []
        group_summaries = []
        for group_summary in group_service.get_posts():
            group_posts_status = group_summary.get("posts_status", [])
            group_summaries.extend(group_summary)
            self._send_group_report(group_summary,send_type = 0)
            posts_status.extend(group_posts_status)
            valid_posts_count = sum(
                1 for post in group_posts_status if post.get("status") == 1
            )
            invalid_posts_count = sum(
                1 for post in group_posts_status if post.get("status") == 0
            )
            logger.info(
                "Group summary before Telegram: group_id=%s total=%s valid=%s invalid=%s",
                group_summary.get("group_id"),
                len(group_posts_status),
                valid_posts_count,
                invalid_posts_count,
            )
        self._send_group_report(group_summary,send_type = 1)
        return posts_status
