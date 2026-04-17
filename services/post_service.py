# Post service
from logging import getLogger
import requests, time
from typing import Any, Dict, Optional, Union
from fake_useragent import UserAgent
from app_config import HEADERS_FOR_GET_UID
from integrations.openai_client import check_post_with_openai, filter_posts_with_openai
from utils.text_utils import remove_icons_from_text
from utils.time_utils import format_facebook_created_time

logger = getLogger(__name__)
DEFAULT_AI_BATCH_SIZE = 20


def get_uid_groups(links: str):
    ua = UserAgent()
    list_uids= []
    for link in links:
        list_uids.append(link.split("groups/")[1].split("/")[0])
    return list_uids
def nomalize_post(posts: list[dict],max_length_text: int = 500, stop_callback=None):
    """
    Normalize Facebook posts to a standard format.
    Return: normalized posts list
    """
    fixed_posts = []
    skipped_without_id = 0
    skipped_too_long = 0

    logger.debug("Normalizing posts: raw_posts_count=%s", len(posts or []))

    for post in posts:
        if stop_callback and stop_callback():
            return
        post_id = post.get("id")
        if not post_id:
            skipped_without_id += 1
            continue

        message = remove_icons_from_text(post.get("message")) or ""
        normalized_post = {
            "id": str(post_id),
            "message": message,
            "created_time": format_facebook_created_time(post.get("created_time")),
        }

        if len(message) < max_length_text:
            fixed_posts.append(normalized_post)
        else:
            skipped_too_long += 1

    logger.info(
        "Normalized posts: raw=%s normalized=%s skipped_without_id=%s skipped_too_long=%s",
        len(posts or []),
        len(fixed_posts),
        skipped_without_id,
        skipped_too_long,
    )
    return fixed_posts


def rm_non_keywords_posts(posts: list[dict], keywords: list[str], status_callback, stop_callback=None):
    """
    Keep only posts that contain at least one keyword.
    """

    def sleep_with_stop(seconds):
        for _ in range(int(seconds * 10)):
            if stop_callback and stop_callback():
                return False
            time.sleep(0.1)
        return True

    normalized_keywords = [
        keyword.strip().lower()
        for keyword in (keywords or [])
        if isinstance(keyword, str) and keyword.strip()
    ]

    # 🔥 check stop sớm
    if stop_callback and stop_callback():
        return []

    if not normalized_keywords:
        logger.info(
            "Skipping keyword filter because keyword list is empty. posts_count=%s",
            len(posts or []),
        )

        status_callback(
            "Bỏ qua bước lọc từ khóa vì danh sách từ khóa trống. Tổng bài viết: %s"
            % len(posts or [])
        )

        # 🔥 thay sleep
        if not sleep_with_stop(1):
            return []

        return posts.copy()


def check_posts_by_AI(
    status_callback,
    posts: list[Dict[str, Any]],
    prompt: Union[str, Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
    proxies: Optional[Dict[str, str]] = None,
    batch_size: int = DEFAULT_AI_BATCH_SIZE,
    stop_callback=None,
):
    def sleep_with_stop(seconds: float) -> bool:
        for _ in range(int(seconds * 10)):
            if stop_callback and stop_callback():
                return False
            time.sleep(0.1)
        return True

    candidate_posts = []
    skipped_empty_messages = 0

    if stop_callback and stop_callback():
        return []

    logger.info(
        "Starting AI filter for posts: posts_count=%s model=%s batch_size=%s",
        len(posts or []),
        model or "default",
        batch_size,
    )
    status_callback(
        "Bắt đầu kiểm tra AI cho %s bài viết với model %s"
        % (len(posts or []), model or "default")
    )
    if not sleep_with_stop(1):
        return []

    for post in (posts or []):
        if stop_callback and stop_callback():
            return []

        message = (post or {}).get("message")
        if not isinstance(message, str) or not message.strip():
            skipped_empty_messages += 1
            logger.warning(
                "Skipping post in batch AI filter because message is empty: post_id=%s",
                (post or {}).get("id"),
            )
            status_callback(
                "Bỏ qua bài viết vì không có nội dung: post_id=%s"
                % (post or {}).get("id")
            )
            continue

        candidate_posts.append(post)

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")

    total_batches = (
        (len(candidate_posts) + batch_size - 1) // batch_size
        if candidate_posts
        else 0
    )
    filtered_posts = []

    for batch_index in range(total_batches):
        if stop_callback and stop_callback():
            return filtered_posts

        start_index = batch_index * batch_size
        end_index = start_index + batch_size
        batch_posts = candidate_posts[start_index:end_index]

        logger.info(
            "Sending AI batch %s/%s: batch_posts=%s start_index=%s end_index=%s",
            batch_index + 1,
            total_batches,
            len(batch_posts),
            start_index,
            min(end_index, len(candidate_posts)),
        )
        status_callback(
            "Đang kiểm tra AI cho batch %s/%s: %s bài viết"
            % (batch_index + 1, total_batches, len(batch_posts))
        )
        if not sleep_with_stop(1):
            return filtered_posts

        if stop_callback and stop_callback():
            return filtered_posts

        batch_filtered_posts = filter_posts_with_openai(
            posts=batch_posts,
            prompt=prompt,
            api_key=api_key,
            model=model,
            proxies=proxies,
        )

        if stop_callback and stop_callback():
            return filtered_posts

        filtered_posts.extend(batch_filtered_posts)

        logger.info(
            "Completed AI batch %s/%s: matched_posts=%s cumulative_matched_posts=%s",
            batch_index + 1,
            total_batches,
            len(batch_filtered_posts),
            len(filtered_posts),
        )
        status_callback(
            "Hoàn thành AI check batch %s/%s: %s chọn bài viết"
            % (batch_index + 1, total_batches, len(batch_filtered_posts))
        )
        if not sleep_with_stop(1):
            return filtered_posts

    logger.info(
        "Completed AI filter for posts: input_posts=%s candidate_posts=%s matched_posts=%s skipped_empty_messages=%s total_batches=%s",
        len(posts or []),
        len(candidate_posts),
        len(filtered_posts),
        skipped_empty_messages,
        total_batches,
    )
    status_callback(
        "Có %s bài viết được chọn, %s bài viết bị bỏ"
        % (len(filtered_posts), skipped_empty_messages)
    )
    if not sleep_with_stop(1):
        return filtered_posts

    return filtered_posts


def build_posts_status(
    status_callback,
    full_posts: list[dict],
    filtered_posts: list[dict],
    group_id: str = None,
    stop_callback=None,
):
    def sleep_with_stop(seconds: float) -> bool:
        for _ in range(int(seconds * 10)):
            if stop_callback and stop_callback():
                return False
            time.sleep(0.1)
        return True

    if stop_callback and stop_callback():
        return []

    filtered_post_ids = {
        post.get("id")
        for post in (filtered_posts or [])
        if post.get("id")
    }
    seen_post_ids = set()
    posts_status = []

    for post in (full_posts or []):
        if stop_callback and stop_callback():
            return posts_status

        post_id = post.get("id")
        if not post_id or post_id in seen_post_ids:
            continue

        seen_post_ids.add(post_id)
        posts_status.append(
            {
                "id": post_id,
                "message": post.get("message"),
                "created_time": post.get("created_time"),
                "group_id": group_id,
                "status": 1 if post_id in filtered_post_ids else 0,
            }
        )

    valid_count = sum(1 for post in posts_status if post.get("status") == 1)
    invalid_count = sum(1 for post in posts_status if post.get("status") == 0)

    logger.info(
        "Built posts status list: full_posts=%s filtered_posts=%s output_posts=%s valid_status=%s invalid_status=%s group_id=%s",
        len(full_posts or []),
        len(filtered_posts or []),
        len(posts_status),
        valid_count,
        invalid_count,
        group_id,
    )

    status_callback(
        "Đã xây dựng trạng thái bài viết: tổng bài viết=%s bài viết hợp lệ=%s bài viết không hợp lệ=%s"
        % (len(full_posts or []), valid_count, invalid_count)
    )

    if not sleep_with_stop(1):
        return posts_status

    return posts_status
