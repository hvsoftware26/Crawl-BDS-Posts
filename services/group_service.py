# Group service
import time
from logging import getLogger

from integrations.openai_client import NoCommentDecision, generate_comment_with_openai
from app_config import BROWSER_RESTART_EVERY_GROUPS, GRAPHQL_GROUP_POST_LIMIT, OPENAI_MODEL_NAME
from services.facebook_browser_commenter import FacebookBrowserCommenter
from services.post_service import (
    build_posts_status,
    check_posts_by_AI,
    rm_non_keywords_posts,
)
from services.group_scan_state_service import load_processed_post_ids, remember_processed_posts
from services.facebook_graphql_group_crawler import FacebookGraphQLGroupCrawler

logger = getLogger(__name__)


class GroupService:
    def __init__(
        self,
        groups_list: list[str],
        delay_next_run: int,
        keywords: list[str],
        account_token: str = None,
        account_cookies: str = None,
        account_name: str = None,
        account_page_names: list[str] | None = None,
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
        console_callback=None,
        browser_context=None,
        browser_restart_callback=None,
    ):
        self.groups_list = groups_list
        self.delay_next_run = delay_next_run * 60
        self.keywords = keywords
        self.account_token = account_token
        self.account_cookies = account_cookies
        self.account_name = account_name
        self.account_page_names = [
            " ".join(str(page_name or "").split()).strip()
            for page_name in (account_page_names or [])
            if str(page_name or "").strip()
        ]
        self.proxies = proxies
        self.prompt = prompt
        self.prompt_cmt = prompt_cmt
        self.prompt_cmt_mode = prompt_cmt_mode
        self.API_KEY = API_KEY
        self.max_length_text = max_length_text
        self.progress_callback = progress_callback or (lambda _value: None)
        self.status_callback = status_callback or (lambda _message: None)
        self.post_callback = post_callback or (lambda _value: None)
        self.stop_callback = stop_callback or (lambda: False)
        self.console_callback = console_callback or (lambda _message: None)
        self.browser_context = browser_context
        self.browser_restart_callback = browser_restart_callback
        logger.debug(
            "Initialized GroupService: groups=%s delay_seconds=%s keywords=%s has_token=%s has_cookies=%s has_proxies=%s has_api_key=%s has_browser_context=%s",
            len(groups_list or []),
            self.delay_next_run,
            len(keywords or []),
            bool(account_token),
            bool(account_cookies),
            bool(proxies),
            bool(API_KEY),
            bool(browser_context),
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
                model=OPENAI_MODEL_NAME,
                max_attempts=3,
            )
            return comment_message, "ai"

        if not self._is_fixed_comment_enabled():
            raise ValueError("Chưa có nội dung cmt sẵn")

        return str(self.prompt_cmt or "").strip(), "text"

    def _comment_valid_posts_with_browser(self, posts_status: list[dict]) -> list[dict]:
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
            self.status_callback("Bo qua comment AI vi chua co prompt")
            return posts_status

        if comment_mode == "text" and not self._is_fixed_comment_enabled():
            logger.info("Skip browser commenting because fixed comment content is empty")
            self.status_callback("Bo qua comment vi chua co noi dung cmt san")
            return posts_status

        if comment_mode == "ai" and not self.API_KEY:
            logger.info("Skip AI commenting because OpenAI API key is empty")
            self.status_callback("Bo qua comment AI vi chua co API key")
            return posts_status

        if not self.browser_context:
            logger.info("Skip browser commenting because browser context is missing")
            self.status_callback("Bo qua comment vi chua co Chrome dang dang nhap")
            return posts_status

        self.status_callback(f"Bat dau comment {len(valid_posts)} bai phu hop bang Chrome")
        commenter = FacebookBrowserCommenter(
            browser_context=self.browser_context,
            account_name=self.account_name,
            page_names=self.account_page_names,
            status_callback=self.status_callback,
            stop_callback=self.stop_callback,
        )

        try:
            for index, post in enumerate(valid_posts, start=1):
                if self.stop_callback and self.stop_callback():
                    return posts_status

                post_id = post.get("id")
                try:
                    comment_message, comment_source = self._build_comment_message_for_post(post)
                    result = commenter.comment_post(post, comment_message)
                    post["comment_status"] = 1
                    post["comment_id"] = result.get("comment_id") or ""
                    post["comment_method"] = result.get("method") or "browser"
                    post["comment_page_name"] = result.get("page_name")
                    post["comment_message"] = comment_message
                    post["comment_source"] = comment_source
                    logger.info(
                        "Commented valid post by browser successfully: post_id=%s comment_id=%s page_name=%s url=%s",
                        post_id,
                        result.get("comment_id"),
                        result.get("page_name"),
                        result.get("post_url"),
                    )
                    self.status_callback(
                        "Da comment %s/%s bai hop le bang Chrome/page %s"
                        % (
                            index,
                            len(valid_posts),
                            result.get("page_name") or "",
                        )
                    )
                    self.console_callback(
                        "Da comment bang Chrome/page %s | comment_id: %s"
                        % (
                            result.get("page_name") or "",
                            result.get("comment_id") or "khong doc duoc",
                        )
                    )
                except NoCommentDecision as e:
                    post["comment_status"] = 0
                    post["comment_skipped"] = True
                    post["comment_decision"] = "No"
                    post["comment_error"] = "AI_NO_COMMENT"
                    post["comment_method"] = "browser"
                    post["comment_source"] = "ai"
                    logger.info("Skipped browser-comment because AI returned No: post_id=%s", post_id)
                    self.status_callback(
                        "AI tra ve No, bo qua comment bai %s/%s"
                        % (index, len(valid_posts))
                    )
                    self.console_callback(
                        "Bo qua comment do AI tra ve No | post_id: %s"
                        % (post_id or "?")
                    )
                except Exception as e:
                    post["comment_status"] = 0
                    post["comment_error"] = str(e)
                    post["comment_method"] = "browser"
                    logger.warning("Failed to browser-comment valid post_id=%s: %s", post_id, e)
                    short_error = " ".join(str(e or "").split())[:160]
                    self.status_callback(
                        "Comment that bai bai %s/%s: %s"
                        % (index, len(valid_posts), short_error)
                    )
                    self.console_callback(
                        "Comment that bai | post_id: %s | error: %s"
                        % (post_id or "?", short_error)
                    )

                if not self.sleep_with_stop(1):
                    return posts_status
        finally:
            commenter.close()

        return posts_status

    def sleep_with_stop(self, seconds: float):
        for _ in range(int(seconds * 10)):
            if hasattr(self, "stop_callback") and self.stop_callback and self.stop_callback():
                return False
            time.sleep(0.1)
        return True

    def _filter_unprocessed_posts(self, posts: list[dict], processed_post_ids: set[str]):
        if not processed_post_ids:
            return posts or [], 0

        filtered_posts = []
        skipped_count = 0
        for post in posts or []:
            post_id = str((post or {}).get("id") or "").strip()
            if post_id and post_id in processed_post_ids:
                skipped_count += 1
                continue
            filtered_posts.append(post)

        if skipped_count:
            logger.info(
                "Skipped processed posts before filtering/commenting: skipped=%s remaining=%s",
                skipped_count,
                len(filtered_posts),
            )
            self.status_callback(
                f"Bỏ qua {skipped_count} bài đã xử lý trước đó"
            )
        return filtered_posts, skipped_count

    def _collect_posts_graphql(self, group_id: str, processed_post_ids: set[str] | None = None):
        if not self.browser_context:
            raise RuntimeError("Chua co Playwright browser context de quet GraphQL")

        logger.info(
            "Start collecting posts with GraphQL: group_id=%s",
            group_id,
        )
        self.status_callback(f"Đang quét 0/{GRAPHQL_GROUP_POST_LIMIT} bài")
        if not self.sleep_with_stop(1):
            return

        crawler = FacebookGraphQLGroupCrawler(
            browser_context=self.browser_context,
            group_url=group_id,
            processed_post_ids=processed_post_ids,
            status_callback=self.status_callback,
            stop_callback=self.stop_callback,
        )
        result = crawler.collect()
        if not result:
            return

        logger.info(
            "Finished collecting GraphQL posts: group_id=%s total_posts=%s scroll_count=%s stop_reason=%s",
            group_id,
            result.get("total_posts"),
            result.get("scroll_count"),
            result.get("stop_reason"),
        )
        self.status_callback(
            "Đã quét %s/%s bài"
            % (result.get("total_posts", 0), GRAPHQL_GROUP_POST_LIMIT)
        )
        if not self.sleep_with_stop(1):
            return
        return result

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
            model=OPENAI_MODEL_NAME,
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
            if (
                index > 0
                and BROWSER_RESTART_EVERY_GROUPS > 0
                and index % BROWSER_RESTART_EVERY_GROUPS == 0
                and self.browser_restart_callback
            ):
                replacement_context = self.browser_restart_callback()
                if not replacement_context:
                    raise RuntimeError("Browser restart did not return a usable context")
                self.browser_context = replacement_context
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
                processed_post_ids = load_processed_post_ids(group_id)
                res_posts = self._collect_posts_graphql(
                    group_id,
                    processed_post_ids=processed_post_ids,
                )
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
                    "Collected %s posts from group %s",
                    res_posts.get("total_posts"),
                    group_id,
                )
                self.status_callback(
                    "Đã quét %s/%s bài"
                    % (res_posts.get("total_posts", 0), GRAPHQL_GROUP_POST_LIMIT)
                )
                if not self.sleep_with_stop(1):
                    return
                full_posts = res_posts.get("posts", [])
                state_group_id = res_posts.get("state_group_id") or group_id
                processed_post_ids = load_processed_post_ids(group_id, aliases=[state_group_id])
                full_posts, skipped_before_filter = self._filter_unprocessed_posts(
                    full_posts,
                    processed_post_ids,
                )
                if skipped_before_filter:
                    logger.info(
                        "Removed processed posts before keyword/AI/comment: group_id=%s skipped=%s",
                        group_id,
                        skipped_before_filter,
                    )
                filtered_posts = self._filter_posts_for_output(full_posts)

                posts_status = build_posts_status(
                    status_callback=self.status_callback,
                    full_posts=full_posts,
                    filtered_posts=filtered_posts,
                    group_id=res_posts.get("group_id"),
                    stop_callback = self.stop_callback,
                )
                posts_status = self._comment_valid_posts_with_browser(posts_status)
                remember_processed_posts(
                    group_id,
                    posts_status,
                    aliases=[state_group_id],
                )

                logger.info(
                    "Prepared %s posts for JSON output from group %s",
                    len(posts_status),
                    group_id,
                )

                if len(posts_status) == 0:
                    logger.info(
                        "private group or no relevant posts",
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
                        
