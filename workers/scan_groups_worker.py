# Scan groups worker thread
from logging import getLogger

from integrations.telegram_client import send_document
from services.group_service import GroupService
from utils.excel_utils import build_group_posts_excel

logger = getLogger(__name__)


class ScanGroups:
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
        stop_callback=None,
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
        self.stop_callback = stop_callback
        self.total_posts_scanned = 0

        logger.debug(
            "Initialized ScanGroups worker: groups=%s delay=%s keywords=%s has_proxies=%s has_api_key=%s",
            len(groups_list or []),
            delay,
            len(keywords or []),
            bool(proxies),
            bool(API_KEY),
        )

    def _extract_valid_posts(self, posts_status: list[dict] | None) -> list[dict]:
        return [
            post
            for post in (posts_status or [])
            if post.get("status") == 1
        ]

    def _send_group_report(self, group_summary: dict, send_type: int):
        valid_posts = self._extract_valid_posts(group_summary.get("posts_status"))
        report_id = group_summary.get("group_id")
        
        logger.debug(
            "Filtering posts for report: report_type=%s report_id=%s total_posts=%s valid_posts=%s",
            "cycle" if send_type == 1 else "group",
            report_id,
            len(group_summary.get("posts_status", [])),
            len(valid_posts),
        )

        if not valid_posts:
            logger.info(
                "Skipping Telegram report because there are no valid posts: report_type=%s report_id=%s total_in_summary=%s",
                "cycle" if send_type == 1 else "group",
                report_id,
                len(group_summary.get("posts_status", [])),
            )
            return

        if not self.token_tele or not self.idchat:
            logger.info(
                "Skipping Telegram report because token_tele or idchat is missing: report_type=%s report_id=%s",
                "cycle" if send_type == 1 else "group",
                report_id,
            )
            return

        if send_type == 0:
            self.total_posts_scanned += len(valid_posts)
            if self.post_callback:
                self.post_callback(self.total_posts_scanned)

        try:
            excel_file_path = build_group_posts_excel(
                group_id=report_id,
                posts=valid_posts,
                include_group_column=(send_type == 1),
            )
            logger.info("Excel exported: %s", excel_file_path)
        except Exception as e:
            logger.exception("Failed to export Excel for report_id=%s: %s", report_id, e)
            return

        try:
            if send_type == 0:
                caption = (
                    f"📌 <b>KẾT QUẢ NHÓM</b>\n\n"
                    f"🔗 <b>Link nhóm:</b> {group_summary.get('group_id')}\n"
                    f"✅ <b>Số bài phù hợp:</b> {len(valid_posts)}\n"
                    f"📎 <b>Tệp đính kèm:</b> file Excel kết quả"
                )
            else:
                groups_processed = group_summary.get("groups_processed", 0)
                caption = (
                    f"📊 <b>KẾT QUẢ SAU 1 CHU KỲ</b>\n\n"
                    f"📚 <b>Số nhóm đã xử lý:</b> {groups_processed}\n"
                    f"✅ <b>Số bài phù hợp:</b> {len(valid_posts)}\n"
                    f"📎 <b>Tệp đính kèm:</b> file Excel kết quả"
                )

            send_document(
                file_path=excel_file_path,
                token_tele=self.token_tele,
                idchat=self.idchat,
                caption=caption,
            )
            logger.info(
                "Sent Telegram Excel report: report_type=%s report_id=%s valid_posts=%s",
                "cycle" if send_type == 1 else "group",
                report_id,
                len(valid_posts),
            )
            self.status_callback(f"Đã gửi thông báo về Telegram")
        except Exception as e:
            logger.exception("Failed to send Telegram document for report_id=%s: %s", report_id, e)

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
            stop_callback = self.stop_callback,
        )
        posts_status = []
        cycle_valid_posts = []
        cycle_seen_post_ids = set()  # 👈 Add deduplication tracking
        processed_groups = 0

        for group_summary in group_service.get_posts():
            processed_groups += 1
            group_posts_status = group_summary.get("posts_status", [])
            group_valid_posts = self._extract_valid_posts(group_posts_status)

            # 👈 Deduplicate posts before adding to cycle
            for post in group_valid_posts:
                post_id = post.get("id")
                if post_id and post_id not in cycle_seen_post_ids:
                    cycle_valid_posts.append(post)
                    cycle_seen_post_ids.add(post_id)
            
            self._send_group_report(group_summary, send_type=0)
            posts_status.extend(group_posts_status)

            valid_posts_count = sum(
                1 for post in group_posts_status if post.get("status") == 1
            )
            invalid_posts_count = sum(
                1 for post in group_posts_status if post.get("status") == 0
            )
            logger.info(
                "Group summary before Telegram: group_id=%s total=%s valid=%s invalid=%s unique_in_cycle=%s",
                group_summary.get("group_id"),
                len(group_posts_status),
                valid_posts_count,
                invalid_posts_count,
                len(group_valid_posts),
            )

        if processed_groups == 0:
            logger.info("Skipping cycle Telegram report because no groups were processed")
            return posts_status
        
        logger.info(
            "Cycle summary before sending: total_groups_processed=%s cycle_valid_posts=%s cycle_deduped_posts=%s",
            processed_groups,
            sum(1 for post in posts_status if post.get("status") == 1),
            len(cycle_valid_posts),
        )

        cycle_summary = {
            "group_id": f"cycle_summary_{processed_groups}_groups",
            "groups_processed": processed_groups,
            "posts_status": cycle_valid_posts,
        }
        self._send_group_report(cycle_summary, send_type=1)
        return posts_status
