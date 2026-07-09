# Group service
import time
from datetime import datetime
from logging import getLogger

from integrations.facebook_client import (
    FacebookClient,
    comment_post_as_random_page,
    get_managed_pages_with_tokens,
)
from integrations.openai_client import generate_comment_with_openai
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
        recent_window_minutes: float = None,
        account_token: str = None,
        account_cookies: str = None,
        account_name: str = None,
        proxies: dict = None,
        API_KEY: str = None,
        prompt: str = None,
        prompt_cmt: str = None,
        prompt_cmt_mode: str = "text",
        max_length_text: int = 500,
        progress_callback=None,
        status_callback=None,
        post_callback=None,
        stop_callback=None,
    ):
        self.facebook_client = FacebookClient(session=None) 
        self.groups_list = groups_list
        self.delay_next_run = delay_next_run * 60
        self.recent_window_seconds = (
            float(recent_window_minutes) * 60
            if recent_window_minutes is not None
            else self.delay_next_run
        )
        self.keywords = keywords
        self.account_token = account_token
        self.account_cookies = account_cookies
        self.account_name = account_name
        self.proxies = proxies
        self._managed_pages_cache = None
        self.prompt = prompt
        self.prompt_cmt = prompt_cmt
        self.prompt_cmt_mode = prompt_cmt_mode
        self.API_KEY = API_KEY
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback or (lambda _value: None)
        self.status_callback = status_callback or (lambda _message: None)
        self.post_callback = post_callback or (lambda _value: None)
        self.stop_callback = stop_callback or (lambda: False)
        logger.debug(
            "Initialized GroupService: groups=%s delay_seconds=%s recent_window_seconds=%s keywords=%s has_token=%s has_cookies=%s has_proxies=%s has_api_key=%s",
            len(groups_list or []),
            self.delay_next_run,
            self.recent_window_seconds,
            len(keywords or []),
            bool(account_token),
            bool(account_cookies),
            bool(proxies),
            bool(API_KEY),
        )

    def _is_fixed_comment_enabled(self) -> bool:
        return (
            str(self.prompt_cmt_mode or "text").strip().casefold() == "text"
            and bool(str(self.prompt_cmt or "").strip())
        )

    def _is_ai_comment_enabled(self) -> bool:
        return (
            str(self.prompt_cmt_mode or "text").strip().casefold() == "ai"
            and bool(str(self.prompt_cmt or "").strip())
        )

    def _build_comment_message_for_post(self, post: dict) -> tuple[str, str]:
        comment_mode = str(self.prompt_cmt_mode or "text").strip().casefold()

        if comment_mode == "ai":
            if not self._is_ai_comment_enabled():
                raise ValueError("Chưa có prompt comment AI")
            if not self.API_KEY:
                raise ValueError("Chưa có API key để tạo comment AI")

            comment_message = generate_comment_with_openai(
                post=post,
                prompt=self.prompt_cmt,
                api_key=self.API_KEY,
                model="gpt-5-mini",
                proxies=self.proxies,
            )
            return comment_message, "ai"

        if not self._is_fixed_comment_enabled():
            raise ValueError("Chưa có nội dung cmt sẵn")

        return str(self.prompt_cmt or "").strip(), "text"

    def _get_cached_managed_pages(self) -> list[dict]:
        if self._managed_pages_cache is not None:
            return self._managed_pages_cache

        self._managed_pages_cache = get_managed_pages_with_tokens(
            account_token=self.account_token,
            account_cookies=self.account_cookies,
            account_name=self.account_name,
            proxies=self.proxies,
        )
        logger.info(
            "Cached managed page tokens for current run: pages=%s",
            len(self._managed_pages_cache),
        )
        return self._managed_pages_cache

    def _comment_valid_posts(self, posts_status: list[dict]) -> list[dict]:
        if not posts_status:
            return posts_status

        valid_posts = [
            post
            for post in posts_status
            if post.get("status") == 1 and post.get("id")
        ]
        if not valid_posts:
            return posts_status

        comment_mode = str(self.prompt_cmt_mode or "text").strip().casefold()
        if comment_mode == "ai" and not self._is_ai_comment_enabled():
            logger.info("Skip AI commenting because AI comment prompt is empty")
            self.status_callback("Bỏ qua comment AI vì chưa có prompt")
            return posts_status

        if comment_mode == "text" and not self._is_fixed_comment_enabled():
            logger.info("Skip commenting because fixed comment content is empty")
            self.status_callback("Bỏ qua comment vì chưa có nội dung cmt sẵn")
            return posts_status

        if comment_mode == "ai" and not self.API_KEY:
            logger.info("Skip AI commenting because OpenAI API key is empty")
            self.status_callback("Bỏ qua comment AI vì chưa có API key")
            return posts_status

        if not self.account_token:
            logger.info("Skip commenting because account token is empty")
            self.status_callback("Bỏ qua comment vì chưa có token Facebook")
            return posts_status

        self.status_callback(f"Bắt đầu comment {len(valid_posts)} bài viết phù hợp")

        try:
            managed_pages = self._get_cached_managed_pages()
        except Exception as e:
            logger.warning("Failed to cache managed page tokens before commenting: %s", e)
            self.status_callback(f"Khong lay duoc token page de comment: {e}")
            for post in valid_posts:
                post["comment_status"] = 0
                post["comment_error"] = str(e)
            return posts_status

        for index, post in enumerate(valid_posts, start=1):
            if self.stop_callback and self.stop_callback():
                return posts_status

            post_id = post.get("id")
            try:
                comment_message, comment_source = self._build_comment_message_for_post(post)
                result = comment_post_as_random_page(
                    post_url_or_id=post_id,
                    message=comment_message,
                    account_token=self.account_token,
                    account_cookies=self.account_cookies,
                    account_name=self.account_name,
                    proxies=self.proxies,
                    managed_pages=managed_pages,
                )
                post["comment_status"] = 1
                post["comment_id"] = result.get("comment_id")
                post["comment_page_id"] = result.get("page_id")
                post["comment_page_name"] = result.get("page_name")
                post["comment_message"] = comment_message
                post["comment_source"] = comment_source
                logger.info(
                    "Commented valid post successfully: post_id=%s comment_id=%s page_name=%s",
                    post_id,
                    result.get("comment_id"),
                    result.get("page_name"),
                )
                self.status_callback(
                    "Đã comment %s/%s bài hợp lệ bằng page %s (comment_id: %s)"
                    % (
                        index,
                        len(valid_posts),
                        result.get("page_name") or "",
                        result.get("comment_id") or "?",
                    )
                )
            except Exception as e:
                post["comment_status"] = 0
                post["comment_error"] = str(e)
                logger.warning("Failed to comment valid post_id=%s: %s", post_id, e)
                self.status_callback("Comment thất bại bài %s/%s" % (index, len(valid_posts)))

            if not self.sleep_with_stop(1):
                return posts_status

        return posts_status

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
                self.recent_window_seconds,
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
                self.recent_window_seconds,
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
            "Start collecting recent posts: group_id=%s reference_time=%s delay_seconds=%s recent_window_seconds=%s",
            group_id,
            reference_time.isoformat(),
            self.delay_next_run,
            self.recent_window_seconds,
        )
        self.status_callback('Bắt đầu thu thập bài viết')
        if not self.sleep_with_stop(1):
            return
        response = self.facebook_client.get_posts_from_group(
            group_id=group_id,
            account_token=self.account_token,
            account_cookies=self.account_cookies,
            proxies=self.proxies,
            stop_callback=self.stop_callback,
        )
        if not response or response.get("stopped"):
            return

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
                stop_callback=self.stop_callback,
            )
            if not response or response.get("stopped"):
                return
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
                    logger.warning(
                        "No posts collected for group_id=%s, skipping to next group",
                        group_id,
                    )
                    yield {
                        "group_id": group_id,
                        "total_posts": 0,
                        "filtered_posts_count": 0,
                        "posts_status_count": 0,
                        "posts_status": [],
                        "error": "No posts collected",
                    }
                    continue
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
                posts_status = self._comment_valid_posts(posts_status)

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
                        self.status_callback(f"Tạm nghỉ {self.delay_next_run // 60} phút")
                        if not self.sleep_with_stop(1):
                            return
                        if not self.sleep_with_stop(self.delay_next_run):
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
                
                # ✅ Yield error result and continue to next group instead of returning
                yield {
                    "group_id": group_id,
                    "total_posts": 0,
                    "filtered_posts_count": 0,
                    "posts_status_count": 0,
                    "posts_status": [],
                    "error": error_message,
                }
                continue

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
                        
