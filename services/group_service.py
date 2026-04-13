# Group service
import time
from datetime import datetime
from logging import getLogger

from integrations.facebook_client import FacebookClient
from services.post_service import (
    build_posts_status,
    check_posts_by_AI,
    nomalize_post,
    rm_non_keywords_posts,
)
from utils.time_utils import HANOI_TIMEZONE, is_created_time_within_delay_window

logger = getLogger(__name__)


class GroupService:
    def __init__(
        self,
        groups_list: list[str],
        delay_next_run: int,
        keywords: list[str],
        account_token: str = None,
        account_cookies: str = None,
        proxies: dict = None,
        API_KEY: str = None,
        prompt: str = None,
        max_length_text: int = 500,
        progress_callback=None,
        status_callback=None,
        post_callback=None,
        stop_callback=None,
    ):
        self.facebook_client = FacebookClient(session=None) 
        self.groups_list = groups_list
        self.delay_next_run = delay_next_run * 60
        self.keywords = keywords
        self.account_token = account_token
        self.account_cookies = account_cookies
        self.proxies = proxies
        self.prompt = prompt
        self.API_KEY = API_KEY
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.post_callback = post_callback
        self.stop_callback = stop_callback
        logger.debug(
            "Initialized GroupService: groups=%s delay_seconds=%s keywords=%s has_token=%s has_cookies=%s has_proxies=%s has_api_key=%s",
            len(groups_list or []),
            self.delay_next_run,
            len(keywords or []),
            bool(account_token),
            bool(account_cookies),
            bool(proxies),
            bool(API_KEY),
        )

    def sleep_with_stop(self, seconds: float):
        for _ in range(int(seconds * 10)):
            if hasattr(self, "stop_callback") and self.stop_callback and self.stop_callback():
                return False
            time.sleep(0.1)
        return True

    def _filter_recent_posts(self, posts: list[dict], reference_time: datetime):
        recent_posts = [
            post
            for post in posts
            if is_created_time_within_delay_window(
                post.get("created_time"),
                self.delay_next_run,
                now=reference_time,
            )
        ]
        logger.debug(
            "Filtered recent posts: input_posts=%s recent_posts=%s reference_time=%s",
            len(posts or []),
            len(recent_posts),
            reference_time.isoformat(),
        )
        return recent_posts

    def _has_posts_older_than_window(self, posts: list[dict], reference_time: datetime):
        has_older_posts = any(
            post.get("created_time")
            and not is_created_time_within_delay_window(
                post.get("created_time"),
                self.delay_next_run,
                now=reference_time,
            )
            for post in posts
        )
        if has_older_posts:
            logger.debug(
                "Detected posts older than delay window: posts_count=%s reference_time=%s",
                len(posts or []),
                reference_time.isoformat(),
            )
        return has_older_posts

    def _extend_unique_posts(
        self,
        current_posts: list[dict],
        new_posts: list[dict],
        seen_post_ids: set[str],
    ):
        added_count = 0
        duplicated_count = 0
        for post in new_posts:
            post_id = post.get("id")
            if post_id and post_id in seen_post_ids:
                duplicated_count += 1
                continue

            current_posts.append(post)
            if post_id:
                seen_post_ids.add(post_id)
            added_count += 1

        logger.debug(
            "Extended unique posts: incoming=%s added=%s duplicated=%s total_unique=%s",
            len(new_posts or []),
            added_count,
            duplicated_count,
            len(current_posts),
        )
        return added_count

    def _collect_recent_posts(self, group_id: str):
        all_recent_posts = []
        seen_post_ids = set()
        page_number = 1
        consecutive_pages_without_new_posts = 0
        reference_time = datetime.now(HANOI_TIMEZONE)
        logger.info(
            "Start collecting recent posts: group_id=%s reference_time=%s delay_seconds=%s",
            group_id,
            reference_time.isoformat(),
            self.delay_next_run,
        )
        self.status_callback('Bắt đầu thu thập bài viết')
        if not self.sleep_with_stop(1):
            return
        response = self.facebook_client.get_posts_from_group(
            group_id=group_id,
            account_token=self.account_token,
            account_cookies=self.account_cookies,
            proxies=self.proxies,
        )

        while True:
            page_posts = nomalize_post(response.get("posts", []),self.max_length_text, stop_callback=self.stop_callback)
            recent_posts = self._filter_recent_posts(page_posts, reference_time)
            added_recent_posts = self._extend_unique_posts(
                all_recent_posts,
                recent_posts,
                seen_post_ids,
            )
            if added_recent_posts == 0:
                consecutive_pages_without_new_posts += 1
            else:
                consecutive_pages_without_new_posts = 0

            logger.info(
                "Collected page for group_id=%s page=%s normalized_posts=%s recent_posts=%s added_recent_posts=%s total_unique_recent_posts=%s consecutive_pages_without_new_posts=%s",
                group_id,
                page_number,
                len(page_posts),
                len(recent_posts),
                added_recent_posts,
                len(all_recent_posts),
                consecutive_pages_without_new_posts,
            )
            self.status_callback(f"Đã thu thập {len(all_recent_posts)} bài viết gần đây")
            if not self.sleep_with_stop(1):
                return

            if consecutive_pages_without_new_posts >= 3:
                logger.info(
                    "Stop paging group_id=%s at page=%s because there were %s consecutive pages without new recent posts",
                    group_id,
                    page_number,
                    consecutive_pages_without_new_posts,
                )
                self.status_callback("Không còn bài viết mới gần đây, dừng thu thập")
                if not self.sleep_with_stop(1):
                    return
                break

            next_api = response.get("next_api")
            if not next_api:
                logger.info(
                    "Stop paging group_id=%s at page=%s because next_api is empty",
                    group_id,
                    page_number,
                )
                self.status_callback("Đã thu thập hết bài viết gần đây")
                if not self.sleep_with_stop(1):
                    return
                break

            response = self.facebook_client.get_posts_from_next_api(
                next_api=next_api,
                account_cookies=self.account_cookies,
                proxies=self.proxies,
            )
            page_number += 1

        logger.info(
            "Finished collecting recent posts: group_id=%s total_recent_posts=%s pages_scanned=%s",
            group_id,
            len(all_recent_posts),
            page_number,
        )
        self.status_callback(f"Hoàn thành thu thập bài viết gần đây: {len(all_recent_posts)} bài viết")
        if not self.sleep_with_stop(1):
            return
        return {
            "group_id": group_id,
            "total_posts": len(all_recent_posts),
            "posts": all_recent_posts,
        }

    def _filter_posts_for_output(self, posts: list[dict]):
        logger.info(
            "Start filtering posts for output: input_posts=%s keywords=%s has_api_key=%s",
            len(posts or []),
            len(self.keywords or []),
            bool(self.API_KEY),
        )
        self.status_callback("Lọc bài viết theo từ khóa")
        if not self.sleep_with_stop(1):
            return
        keyword_filtered_posts = rm_non_keywords_posts(
            posts,
            self.keywords,
            status_callback = self.status_callback,
            stop_callback = self.stop_callback,
        )
        if not keyword_filtered_posts:
            logger.info("No posts left after keyword filtering")
            self.status_callback("Không có bài viết sau khi lọc từ khóa")
            if not self.sleep_with_stop(1):
                return
            return []

        if not self.API_KEY:
            logger.info(
                "OpenAI API key is missing. Skip AI filtering and keep keyword-filtered posts: posts_count=%s",
                len(keyword_filtered_posts),
            )
            self.status_callback("Không có API Key, bỏ qua lọc")
            if not self.sleep_with_stop(1):
                return
            return keyword_filtered_posts

        ai_filtered_posts = check_posts_by_AI(
            status_callback = self.status_callback,
            posts=keyword_filtered_posts,
            prompt=self.prompt,
            api_key=self.API_KEY,
            model="gpt-5-mini",
            proxies=self.proxies,
            stop_callback=self.stop_callback,
        )
        logger.info(
            "Completed output filtering: keyword_filtered_posts=%s ai_filtered_posts=%s",
            len(keyword_filtered_posts),
            len(ai_filtered_posts),
        )
        self.status_callback(f"Hoàn thành lọc: {len(ai_filtered_posts)} bài viết phù hợp")
        if not self.sleep_with_stop(1):
            return
        return ai_filtered_posts

    def get_posts(self):
        logger.info("Start processing groups: groups_count=%s", len(self.groups_list or []))
        self.status_callback("Bắt đầu xử lý nhóm")
        if not self.sleep_with_stop(1):
            return
        for index, group_id in enumerate(self.groups_list):
            if self.stop_callback and self.stop_callback():
                return
            full_posts = []
            filtered_posts = []
            posts_status = []
            error_message = None

            logger.info(
                "Processing group %s/%s: group_id=%s",
                index + 1,
                len(self.groups_list),
                group_id,
            )
            self.status_callback(f"Đang xử lý nhóm {index + 1}/{len(self.groups_list)}")
            if not self.sleep_with_stop(1):
                return
            self.progress_callback(f"{index + 1}/{len(self.groups_list)}")

            try:
                res_posts = self._collect_recent_posts(group_id)
                if not res_posts:
                    return
                logger.info(
                    "Collected %s recent posts from group %s",
                    res_posts.get("total_posts"),
                    group_id,
                )
                self.status_callback(f"Thu thập {res_posts.get('total_posts')} bài viết gần đây")
                if not self.sleep_with_stop(1):
                    return

                full_posts = res_posts.get("posts", [])
                filtered_posts = self._filter_posts_for_output(full_posts)

                posts_status = build_posts_status(
                    status_callback=self.status_callback,
                    full_posts=full_posts,
                    filtered_posts=filtered_posts,
                    group_id=res_posts.get("group_id"),
                    stop_callback = self.stop_callback,
                )

                logger.info(
                    "Prepared %s posts for JSON output from group %s",
                    len(posts_status),
                    group_id,
                )

                if len(posts_status) == 0:
                    logger.info(
                        "private group" if self._has_posts_older_than_window(full_posts, datetime.now(HANOI_TIMEZONE)) else "no relevant posts",
                        extra={"group_id": group_id},
                    )
                    self.status_callback("Nhóm riêng tư hoặc không có bài viết")
                    if not self.sleep_with_stop(1):
                        return

                    yield {
                        "group_id": group_id,
                        "total_posts": len(full_posts),
                        "filtered_posts_count": len(filtered_posts),
                        "posts_status_count": 0,
                        "posts_status": [],
                        "error": None,
                    }

                    if self.delay_next_run > 0:
                        logger.info(
                            "Sleeping before next group: group_id=%s delay_seconds=%s",
                            group_id,
                            self.delay_next_run,
                        )
                        if not self.sleep_with_stop(5):
                            return

                    continue

                self.status_callback(f"Chuẩn bị data cho {len(posts_status)} bài viết")
                if not self.sleep_with_stop(1):
                    return

            except Exception as e:
                error_message = str(e)
                logger.exception(
                    "Failed to process group_id=%s error=%s",
                    group_id,
                    error_message,
                )
                self.status_callback("Lỗi khi xử lý nhóm")
                if not self.sleep_with_stop(1):
                    return

            valid_posts_count = sum(
                1 for post in posts_status if post.get("status") == 1
            )
            invalid_posts_count = sum(
                1 for post in posts_status if post.get("status") == 0
            )

            logger.info(
                "Yielding group summary: group_id=%s total_posts=%s filtered_posts=%s valid_posts=%s invalid_posts=%s error=%s",
                group_id,
                len(full_posts),
                len(filtered_posts),
                valid_posts_count,
                invalid_posts_count,
                error_message,
            )

            yield {
                "group_id": group_id,
                "total_posts": len(full_posts),
                "filtered_posts_count": len(filtered_posts),
                "posts_status_count": len(posts_status),
                "posts_status": posts_status,
                "error": error_message,
            }

            if self.delay_next_run > 0:
                logger.info(
                    "Sleeping before next group: group_id=%s delay_seconds=%s",
                    group_id,
                    self.delay_next_run,
                )
                if len(posts_status) == 0:
                    if not self.sleep_with_stop(5):
                        return
                else:
                    self.status_callback(f"Tạm nghỉ {self.delay_next_run // 60} phút")
                    if not self.sleep_with_stop(1):
                        return
                    if not self.sleep_with_stop(self.delay_next_run):
                        return
                        