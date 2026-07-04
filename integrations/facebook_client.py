from logging import getLogger
import random
import re
import time
import requests
from urllib.parse import parse_qs, urlparse

from app_config import build_headers, build_params

logger = getLogger(__name__)


def _create_graph_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _extract_facebook_post_id(post_url_or_id: str) -> str:
    post_value = str(post_url_or_id or "").strip()
    if not post_value:
        raise ValueError("post_url_or_id is required")

    if re.fullmatch(r"[A-Za-z0-9_]+", post_value):
        return post_value

    parsed_url = urlparse(post_value)
    query = parse_qs(parsed_url.query)
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]

    story_fbid = (query.get("story_fbid") or query.get("fbid") or [None])[0]
    owner_id = (query.get("id") or [None])[0]
    if story_fbid and owner_id:
        return f"{owner_id}_{story_fbid}"

    if "groups" in path_segments and "posts" in path_segments:
        group_index = path_segments.index("groups")
        posts_index = path_segments.index("posts")
        if len(path_segments) > group_index + 1 and len(path_segments) > posts_index + 1:
            group_id = path_segments[group_index + 1]
            post_id = path_segments[posts_index + 1]
            if group_id.isdigit() and post_id:
                return f"{group_id}_{post_id}"
            return post_id

    for marker in ("posts", "videos", "photos"):
        if marker in path_segments:
            marker_index = path_segments.index(marker)
            if len(path_segments) > marker_index + 1:
                return path_segments[marker_index + 1]

    raise ValueError(
        "Không tách được post id. Hãy truyền dạng object_id, ví dụ groupid_postid hoặc pageid_postid."
    )


def _build_facebook_post_link(original_post_value: str, post_id: str) -> str:
    original_value = str(original_post_value or "").strip()
    if original_value.startswith(("http://", "https://")):
        return original_value
    return f"https://www.facebook.com/{post_id}"


def _raise_graph_payload_error(payload: dict, context: str):
    error = payload.get("error") if isinstance(payload, dict) else None
    if not error:
        return

    message = error.get("message", "Unknown Facebook API error")
    code = error.get("code")
    subcode = error.get("error_subcode")
    raise Exception(f"{context}: {message} (code={code}, subcode={subcode})")


def _extract_cookie_value(cookies: str, name: str) -> str:
    wanted_name = str(name or "").strip()
    if not wanted_name:
        return ""

    for part in str(cookies or "").split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.strip() == wanted_name:
            return value.strip()

    return ""


def _normalize_page_identity(value: str) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _is_main_profile_identity(page: dict, account_cookies: str, account_name: str = "") -> bool:
    page_id = str(page.get("id") or "").strip()
    page_name = _normalize_page_identity(page.get("name") or "")
    profile_id = _extract_cookie_value(account_cookies, "c_user")
    profile_name = _normalize_page_identity(account_name)

    if profile_id and page_id == profile_id:
        return True

    if profile_name and page_name == profile_name:
        return True

    return False


def _get_managed_pages_with_tokens(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> list[dict]:
    if not account_token:
        raise ValueError("account_token is required")

    http = session or _create_graph_session()
    url = "https://graph.facebook.com/v22.0/me/accounts"
    params = {
        "fields": "id,name,access_token,category,tasks",
        "limit": 100,
        "access_token": account_token,
    }
    headers = {"cookie": account_cookies} if account_cookies else None
    pages = []

    while url:
        response = http.get(
            url,
            params=params,
            headers=headers,
            proxies=proxies,
            timeout=30,
        )
        params = None

        try:
            payload = response.json()
        except ValueError as exc:
            raise Exception(f"Facebook trả về dữ liệu page không hợp lệ: {response.text}") from exc

        _raise_graph_payload_error(payload, "Không lấy được danh sách page")

        for page in payload.get("data", []) if isinstance(payload, dict) else []:
            if page.get("id") and page.get("access_token"):
                if _is_main_profile_identity(page, account_cookies, account_name):
                    logger.info(
                        "Skip main profile identity from page commenting: id=%s name=%s",
                        page.get("id"),
                        page.get("name"),
                    )
                    continue

                pages.append(
                    {
                        "id": str(page.get("id")),
                        "name": str(page.get("name") or ""),
                        "access_token": str(page.get("access_token")),
                    }
                )

        url = payload.get("paging", {}).get("next") if isinstance(payload, dict) else None

    return pages


def comment_post_as_random_page(
    post_url_or_id: str,
    message: str,
    account_token: str,
    account_cookies: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
    randomizer: random.Random | None = None,
    account_name: str = "",
) -> dict:
    """
    Comment một bài Facebook bằng một page ngẫu nhiên mà account đang quản lý.

    Lưu ý:
    - `account_token` phải đọc được `/me/accounts` kèm `access_token` của page.
    - `post_url_or_id` nên là Graph object id ổn định như `groupid_postid` hoặc `pageid_postid`.
    - Hàm chỉ comment một lần cho một lời gọi; phần gọi bên ngoài quyết định tần suất.
    """
    comment_message = str(message or "").strip()
    if not comment_message:
        raise ValueError("message is required")

    post_id = _extract_facebook_post_id(post_url_or_id)
    http = session or _create_graph_session()
    pages = _get_managed_pages_with_tokens(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=http,
        proxies=proxies,
    )
    if not pages:
        raise Exception("Account khong co page hop le de comment. Nick chinh da duoc loai khoi danh sach page.")

    chooser = randomizer or random.SystemRandom()
    selected_page = chooser.choice(pages)
    response = http.post(
        f"https://graph.facebook.com/v22.0/{post_id}/comments",
        data={
            "message": comment_message,
            "access_token": selected_page["access_token"],
        },
        headers={"cookie": account_cookies} if account_cookies else None,
        proxies=proxies,
        timeout=30,
    )

    try:
        payload = response.json()
    except ValueError as exc:
        raise Exception(f"Facebook trả về dữ liệu comment không hợp lệ: {response.text}") from exc

    _raise_graph_payload_error(payload, "Comment bằng page thất bại")

    comment_id = payload.get("id")
    if not comment_id:
        raise Exception(f"Facebook không trả về comment id: {payload}")

    logger.info(
        "Commented post as page: post_id=%s page_id=%s page_name=%s comment_id=%s",
        post_id,
        selected_page["id"],
        selected_page["name"],
        comment_id,
    )

    return {
        "post_id": post_id,
        "post_url": _build_facebook_post_link(post_url_or_id, post_id),
        "comment_id": comment_id,
        "page_id": selected_page["id"],
        "page_name": selected_page["name"],
    }

def comment_post_as_page(
    post_url_or_id: str,
    message: str,
    account_token: str,
    account_cookies: str = "",
    page_name: str = "",
    page_id: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> dict:
    """
    Comment một bài Facebook bằng page cụ thể theo `page_name` hoặc `page_id`.
    """
    comment_message = str(message or "").strip()
    if not comment_message:
        raise ValueError("message is required")

    wanted_page_name = str(page_name or "").strip().casefold()
    wanted_page_id = str(page_id or "").strip()
    if not wanted_page_name and not wanted_page_id:
        raise ValueError("page_name or page_id is required")

    post_id = _extract_facebook_post_id(post_url_or_id)
    http = session or _create_graph_session()
    pages = _get_managed_pages_with_tokens(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=http,
        proxies=proxies,
    )
    if not pages:
        raise Exception("Account khong co page hop le de comment. Nick chinh da duoc loai khoi danh sach page.")

    selected_page = None
    for page in pages:
        if wanted_page_id and str(page.get("id") or "").strip() == wanted_page_id:
            selected_page = page
            break
        if wanted_page_name and str(page.get("name") or "").strip().casefold() == wanted_page_name:
            selected_page = page
            break

    if selected_page is None:
        available_pages = ", ".join(page.get("name") or page.get("id") or "" for page in pages)
        raise Exception(f"Không tìm thấy page yêu cầu. Page hiện có: {available_pages}")

    response = http.post(
        f"https://graph.facebook.com/v22.0/{post_id}/comments",
        data={
            "message": comment_message,
            "access_token": selected_page["access_token"],
        },
        headers={"cookie": account_cookies} if account_cookies else None,
        proxies=proxies,
        timeout=30,
    )

    try:
        payload = response.json()
    except ValueError as exc:
        raise Exception(f"Facebook trả về dữ liệu comment không hợp lệ: {response.text}") from exc

    _raise_graph_payload_error(payload, "Comment bằng page thất bại")

    comment_id = payload.get("id")
    if not comment_id:
        raise Exception(f"Facebook không trả về comment id: {payload}")

    logger.info(
        "Commented post as selected page: post_id=%s page_id=%s page_name=%s comment_id=%s",
        post_id,
        selected_page["id"],
        selected_page["name"],
        comment_id,
    )

    return {
        "post_id": post_id,
        "post_url": _build_facebook_post_link(post_url_or_id, post_id),
        "comment_id": comment_id,
        "page_id": selected_page["id"],
        "page_name": selected_page["name"],
    }


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
