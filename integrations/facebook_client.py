from logging import getLogger
import random
import re
import requests
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = getLogger(__name__)
FACEBOOK_GRAPH_VERSION = "v20.0"
FACEBOOK_ME_ACCOUNTS_URL = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/me/accounts"
FACEBOOK_UID_PICTURE_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,vi;q=0.8",
    "origin": "https://checkuid.live",
    "priority": "u=1, i",
    "referer": "https://checkuid.live/",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
}


class FacebookUidCheckNetworkError(Exception):
    pass


def _create_graph_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _build_me_accounts_headers(account_cookies: str = "") -> dict:
    headers = {"accept": "application/json"}
    cookie_value = str(account_cookies or "").strip()
    if cookie_value:
        headers["cookie"] = cookie_value
    return headers


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


def _normalize_facebook_uid_candidate(value: str) -> str:
    candidate = str(value or "").strip().strip('"').strip("'")
    if not candidate:
        return ""

    if re.fullmatch(r"\d{5,20}", candidate):
        return candidate

    try:
        parsed_url = urlparse(candidate)
        query_uid = (parse_qs(parsed_url.query).get("id") or [""])[0]
        if re.fullmatch(r"\d{5,20}", query_uid):
            return query_uid

        path_segments = [segment for segment in parsed_url.path.split("/") if segment]
        for segment in path_segments:
            if re.fullmatch(r"\d{5,20}", segment):
                return segment
    except Exception:
        pass

    basename = Path(candidate).name
    if basename != candidate:
        return _normalize_facebook_uid_candidate(basename)

    return ""


def extract_facebook_uid_from_cookie(cookies: str) -> str:
    return _normalize_facebook_uid_candidate(_extract_cookie_value(cookies, "c_user"))


def resolve_facebook_uid(
    account_name: str = "",
    path_chrome: str = "",
    email: str = "",
    cookie: str = "",
) -> str:
    cookie_uid = extract_facebook_uid_from_cookie(cookie)
    if cookie_uid:
        return cookie_uid

    for value in (account_name, path_chrome, email):
        uid = _normalize_facebook_uid_candidate(value)
        if uid:
            return uid

    return ""


def check_facebook_uid_status(
    uid: str,
    session: requests.Session | None = None,
    proxies: dict = None,
    timeout: int = 30,
) -> dict:
    facebook_uid = _normalize_facebook_uid_candidate(uid)
    if not facebook_uid:
        raise ValueError("Facebook UID is required")

    http = session or _create_graph_session()
    try:
        response = http.get(
            f"https://graph.facebook.com/{facebook_uid}/picture",
            params={"redirect": "false"},
            headers=FACEBOOK_UID_PICTURE_HEADERS,
            proxies=proxies,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise FacebookUidCheckNetworkError(f"Không kết nối được API kiểm tra UID: {exc}") from exc

    status_code = int(getattr(response, "status_code", 200) or 200)
    if status_code in (407, 429) or status_code >= 500:
        raise FacebookUidCheckNetworkError(
            f"API kiểm tra UID trả HTTP {status_code}: {getattr(response, 'text', '')[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise Exception(f"Facebook UID check returned invalid JSON: {response.text}") from exc

    _raise_graph_payload_error(payload, "Không kiểm tra được UID Facebook")

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise Exception(f"Facebook UID check response không hợp lệ: {payload}")

    image_url = str(data.get("url") or "")
    has_dimensions = data.get("height") is not None or data.get("width") is not None
    is_dead_placeholder = (
        "static.xx.fbcdn.net/rsrc.php" in image_url
        or image_url.endswith("/UlIqmHJn-SK.gif")
        or image_url.endswith("UlIqmHJn-SK.gif")
    )
    is_alive = bool(has_dimensions or (image_url and not is_dead_placeholder))

    logger.info(
        "Checked Facebook UID status: uid=%s alive=%s has_dimensions=%s placeholder=%s",
        facebook_uid,
        is_alive,
        has_dimensions,
        is_dead_placeholder,
    )
    return {
        "uid": facebook_uid,
        "alive": is_alive,
        "status": "alive" if is_alive else "dead",
        "url": image_url,
        "raw": payload,
    }


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


def _get_me_accounts_pages(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
    fields: str = "id,name,access_token,category,tasks",
    require_access_token: bool = False,
) -> list[dict]:
    if not account_token:
        raise ValueError("account_token is required")

    http = session or _create_graph_session()
    url = FACEBOOK_ME_ACCOUNTS_URL
    params = {
        "fields": fields,
        "limit": 100,
        "access_token": account_token,
    }
    headers = _build_me_accounts_headers(account_cookies)
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
            if not isinstance(page, dict) or not page.get("id"):
                continue

            if require_access_token and not page.get("access_token"):
                continue

            if _is_main_profile_identity(page, account_cookies, account_name):
                logger.info(
                    "Skip main profile identity from /me/accounts: id=%s name=%s",
                    page.get("id"),
                    page.get("name"),
                )
                continue

            page_info = {
                "id": str(page.get("id")),
                "name": str(page.get("name") or ""),
            }
            for key in ("access_token", "category", "tasks", "perms"):
                if key in page and page.get(key) is not None:
                    page_info[key] = page.get(key)
            pages.append(page_info)

        url = payload.get("paging", {}).get("next") if isinstance(payload, dict) else None

    return pages


def _get_managed_pages_with_tokens(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> list[dict]:
    pages = _get_me_accounts_pages(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=session,
        proxies=proxies,
        fields="id,name,access_token,category,tasks",
        require_access_token=True,
    )
    return [
        {
            "id": page["id"],
            "name": page.get("name", ""),
            "access_token": str(page.get("access_token")),
        }
        for page in pages
    ]


def get_managed_pages_with_tokens(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> list[dict]:
    return _get_managed_pages_with_tokens(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=session,
        proxies=proxies,
    )


def get_managed_pages_info(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> list[dict]:
    return _get_me_accounts_pages(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=session,
        proxies=proxies,
        fields="id,name,access_token,category,tasks,perms",
        require_access_token=False,
    )


def get_managed_page_names(
    account_token: str,
    account_cookies: str = "",
    account_name: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> list[str]:
    pages = get_managed_pages_info(
        account_token=account_token,
        account_cookies=account_cookies,
        account_name=account_name,
        session=session,
        proxies=proxies,
    )
    names = []
    seen = set()
    for page in pages:
        name = " ".join(str(page.get("name") or "").split()).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def get_account_profile_info(
    account_token: str,
    account_cookies: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
) -> dict:
    if not account_token:
        raise ValueError("account_token is required")

    http = session or _create_graph_session()
    response = http.get(
        "https://graph.facebook.com/v22.0/me",
        params={
            "fields": "id,name",
            "access_token": account_token,
        },
        headers={"cookie": account_cookies} if account_cookies else None,
        proxies=proxies,
        timeout=30,
    )

    try:
        payload = response.json()
    except ValueError as exc:
        raise Exception(f"Facebook trả về thông tin tài khoản không hợp lệ: {response.text}") from exc

    _raise_graph_payload_error(payload, "Không lấy được thông tin tài khoản")

    profile_id = str(payload.get("id") or "").strip()
    profile_name = " ".join(str(payload.get("name") or "").split()).strip()
    if not profile_id and not profile_name:
        raise Exception(f"Facebook không trả về thông tin tài khoản: {payload}")

    return {
        "id": profile_id,
        "name": profile_name,
        "raw": payload,
    }


def comment_post_as_random_page(
    post_url_or_id: str,
    message: str,
    account_token: str,
    account_cookies: str = "",
    session: requests.Session | None = None,
    proxies: dict = None,
    randomizer: random.Random | None = None,
    account_name: str = "",
    managed_pages: list[dict] | None = None,
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
    pages = managed_pages
    if pages is None:
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

