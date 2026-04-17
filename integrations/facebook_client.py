from logging import getLogger
import re
import time
import requests

from app_config import build_headers, build_params

logger = getLogger(__name__)


def _sleep_with_stop(seconds: float, stop_callback=None) -> bool:
    if seconds <= 0:
        return True

    for _ in range(int(seconds * 10)):
        if stop_callback and stop_callback():
            return False
        time.sleep(0.1)
    return True


def _extract_numeric_group_id(group_input: str) -> str | None:
    """
    Trả về group id nếu input đã chứa UID số.
    Hỗ trợ:
    - "659144150945217"
    - "https://www.facebook.com/groups/659144150945217/"
    - "facebook.com/groups/659144150945217/?ref=share"
    """
    if not group_input:
        return None

    group_input = str(group_input).strip()

    if group_input.isdigit():
        return group_input

    match = re.search(r"/groups/(\d+)", group_input)
    if match:
        return match.group(1)

    return None


def _resolve_group_id_from_tds(group_input: str) -> str:
    """
    Chỉ dùng khi input không có UID số sẵn, ví dụ:
    - https://www.facebook.com/some.group.slug
    - https://www.facebook.com/groups/ten-group/
    """
    link = str(group_input).strip()

    logger.info("Resolving Facebook group/user link via TDS: input=%s", link)

    try:
        response = requests.post(
            "https://id.traodoisub.com/api.php",
            data={"link": link},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        logger.exception("TDS request failed for input=%s", link)
        raise Exception(f"Không gọi được API TDS: {e}") from e
    except ValueError as e:
        logger.exception("TDS returned non-JSON response for input=%s", link)
        raise Exception("API TDS trả về dữ liệu không hợp lệ") from e

    resolved_id = payload.get("id")
    if not resolved_id:
        logger.error("TDS could not resolve id: input=%s payload=%s", link, payload)
        raise Exception(f"Không convert được link sang ID qua TDS: {link}")

    logger.info("Resolved via TDS: input=%s -> id=%s", link, resolved_id)
    return str(resolved_id)


def _normalize_group_id(group_input: str) -> str:
    """
    Ưu tiên:
    1. Nếu đã là UID số => dùng luôn
    2. Nếu là link có UID số => tách ra dùng luôn
    3. Nếu là link slug/user => convert qua TDS
    """
    numeric_id = _extract_numeric_group_id(group_input)
    if numeric_id:
        logger.info("Using direct numeric group id: input=%s -> id=%s", group_input, numeric_id)
        return numeric_id

    return _resolve_group_id_from_tds(group_input)


def _raise_facebook_error(payload: dict, status_code: int, resolved_group_id: str, raw_group_input: str):
    error = payload.get("error")
    if not error:
        return

    error_message = error.get("message", "Unknown Facebook API error")
    error_code = error.get("code")
    error_subcode = error.get("error_subcode")
    error_type = error.get("type")

    logger.error(
        "Facebook API error: status_code=%s raw_input=%s resolved_group_id=%s "
        "type=%s code=%s subcode=%s message=%s",
        status_code,
        raw_group_input,
        resolved_group_id,
        error_type,
        error_code,
        error_subcode,
        error_message,
    )

    lowered = error_message.lower()

    if "access token" in lowered or "session" in lowered or "expired" in lowered:
        raise Exception(f"TOKEN không hợp lệ hoặc đã hết hạn: {error_message}")

    if "permissions" in lowered or "unsupported get request" in lowered:
        raise Exception(
            f"Không có quyền truy cập group hoặc group không hợp lệ: {error_message}"
        )

    raise Exception(f"Facebook API error: {error_message}")

class FacebookClient:
    def __init__(self,session):
        self.session = requests.Session()
    def get_posts_from_group(
        self,
        group_id: str,
        account_token: str,
        account_cookies: str,
        proxies: dict = None,
        stop_callback=None,
    ):
        """
        Lấy page đầu tiên của post trong group.
        - Nếu input là ID số hoặc link có ID số: không gọi TDS
        - Nếu input là link slug/user: mới gọi TDS để convert
        """
        if not _sleep_with_stop(5, stop_callback):
            logger.info("Stop requested before fetching first page: raw_group_input=%s", group_id)
            return {"id": None, "posts": [], "next_api": None, "stopped": True}
        logger.info(
            "Fetching first page of posts: raw_group_input=%s has_proxies=%s has_token=%s has_cookies=%s",
            group_id,
            bool(proxies),
            bool(account_token),
            bool(account_cookies),
        )

        raw_group_input = str(group_id).strip()
        resolved_group_id = _normalize_group_id(raw_group_input)

        logger.info(
            "Prepared Facebook Graph request: raw_group_input=%s resolved_group_id=%s",
            raw_group_input,
            resolved_group_id,
        )

        try:
            res_get_posts = self.session.get(
                f"https://graph.facebook.com/v22.0/{resolved_group_id}",
                params=build_params(account_token),
                headers=build_headers(account_cookies),
                proxies=proxies,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.exception(
                "Failed HTTP request to Facebook Graph API: resolved_group_id=%s",
                resolved_group_id,
            )
            raise Exception(f"Lỗi kết nối Facebook Graph API: {e}") from e

        try:
            payload = res_get_posts.json()
        except ValueError as e:
            logger.error(
                "Facebook Graph API returned non-JSON response: status_code=%s body=%s",
                res_get_posts.status_code,
                res_get_posts.text,
            )
            raise Exception("Facebook Graph API trả về dữ liệu không hợp lệ") from e

        _raise_facebook_error(
            payload=payload,
            status_code=res_get_posts.status_code,
            resolved_group_id=resolved_group_id,
            raw_group_input=raw_group_input,
        )

        if not _sleep_with_stop(5, stop_callback):
            logger.info("Stop requested after fetching first page: resolved_group_id=%s", resolved_group_id)
            return {"id": payload.get("id"), "posts": [], "next_api": None, "stopped": True}

        posts = payload.get("feed", {}).get("data", [])
        next_api = payload.get("feed", {}).get("paging", {}).get("next")

        logger.info(
            "Fetched first page successfully: resolved_group_id=%s posts_count=%s has_next_api=%s",
            resolved_group_id,
            len(posts),
            bool(next_api),
        )

        return {
            "id": payload.get("id"),
            "posts": posts,
            "next_api": next_api,
        }

    def get_posts_from_next_api(
        self,
        next_api: str,
        account_cookies: str,
        proxies: dict = None,
        stop_callback=None,
    ):
        """
        Lấy trang tiếp theo từ paging URL của Facebook Graph API.
        """
        if not _sleep_with_stop(5, stop_callback):
            logger.info("Stop requested before fetching next_api")
            return {"posts": [], "next_api": None, "stopped": True}
        if not next_api:
            logger.debug("Skipping next_api fetch because next_api is empty")
            return {"posts": [], "next_api": None}

        logger.info("Fetching next page of group posts from paging URL")

        try:
            res_get_posts = self.session.get(
                next_api,
                headers=build_headers(account_cookies),
                proxies=proxies,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.exception("Failed HTTP request to Facebook next_api")
            raise Exception(f"Lỗi kết nối khi gọi next_api: {e}") from e

        if res_get_posts.status_code != 200:
            logger.error(
                "Facebook next_api fetch failed: status_code=%s body=%s",
                res_get_posts.status_code,
                res_get_posts.text,
            )
            raise Exception(f"Failed to get posts from next_api: {res_get_posts.text}")

        try:
            payload = res_get_posts.json()
        except ValueError as e:
            logger.error(
                "Facebook next_api returned non-JSON response: body=%s",
                res_get_posts.text,
            )
            raise Exception("next_api trả về dữ liệu không hợp lệ") from e

        error = payload.get("error")
        if error:
            logger.error("Facebook next_api returned error: %s", error)
            raise Exception(f"Facebook next_api error: {error.get('message', error)}")

        logger.info(
            "Fetched next page successfully: posts_count=%s has_next_api=%s",
            len(payload.get("data", [])),
            bool(payload.get("paging", {}).get("next")),
        )

        return {
            "posts": payload.get("data", []),
            "next_api": payload.get("paging", {}).get("next"),
        }
