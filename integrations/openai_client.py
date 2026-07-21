# OpenAI API client
import json
import re
import unicodedata
from logging import getLogger
from typing import Any, Dict, Optional, Tuple, Union

import requests

from app_config import OPENAI_MODEL_NAME

OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = OPENAI_MODEL_NAME
logger = getLogger(__name__)


class NoCommentDecision(ValueError):
    """Raised when the AI explicitly decides the post should not be commented."""


MIN_GENERATED_COMMENT_WORDS = 4
MIN_GENERATED_COMMENT_CHARS = 8
BLOCKED_GENERATED_COMMENTS = {
    "yes",
    "yes.",
    "ok",
    "ok.",
    "okay",
    "khong",
    "khong.",
    "ko",
    "k",
    "qt",
    "ib",
    "inbox",
}
BLOCKED_GENERATED_COMMENT_PHRASES = (
    "khong quan tam",
    "khong phu hop",
    "khong co nhu cau",
    "khong the",
    "toi khong",
    "xin loi",
    "tu choi",
    "sorry",
    "cannot",
    "i cannot",
    "i can't",
)


def _resolve_prompt_config(
    prompt: Union[str, Dict[str, Any]],
    model: Optional[str] = None,
) -> Tuple[str, str]:
    if isinstance(prompt, dict):
        instructions = str(
            prompt.get("prompt") or prompt.get("instructions") or ""
        ).strip()
        resolved_model = model or prompt.get("model") or DEFAULT_OPENAI_MODEL
    else:
        instructions = str(prompt or "").strip()
        resolved_model = model or DEFAULT_OPENAI_MODEL

    if not instructions:
        raise ValueError("Prompt is required")

    logger.debug(
        "Resolved OpenAI prompt config with model=%s prompt_type=%s instructions_length=%s",
        resolved_model,
        type(prompt).__name__,
        len(instructions),
    )
    return instructions, str(resolved_model).strip()


def _build_headers(api_key: str) -> Dict[str, str]:
    normalized_api_key = (api_key or "").strip()
    if not normalized_api_key:
        raise ValueError("OpenAI API key is required")

    return {
        "Authorization": f"Bearer {normalized_api_key}",
        "Content-Type": "application/json",
    }


def _extract_output_text(payload: Dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue

        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue

            text = content.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())

    return "\n".join(chunks).strip()


def _build_batch_filter_instructions(instructions: str) -> str:
    return (
        f"{instructions}\n\n"
        "Dữ liệu đầu vào là một JSON array các bài viết.\n\n"

        "Yêu cầu đầu ra:\n"
        "- Chỉ trả về DUY NHẤT một JSON object.\n"
        "- JSON object phải có key duy nhất là 'matched_posts'.\n"
        "- Giá trị của 'matched_posts' phải là một JSON array.\n"
        "- Mỗi phần tử trong 'matched_posts' là một bài viết PHÙ HỢP lấy từ input.\n\n"

        "Ràng buộc:\n"
        "- KHÔNG được thêm field mới.\n"
        "- KHÔNG được sửa id.\n"
        "- KHÔNG được viết lại message.\n"
        "- KHÔNG được đổi created_time.\n"
        "- Chỉ giữ lại đúng các field: id, message, created_time.\n\n"

        "Nếu không có bài nào phù hợp, trả về:\n"
        "{\"matched_posts\": []}"
    )


def _clean_generated_comment(value: str) -> str:
    comment = str(value or "").strip()
    comment = comment.strip("`").strip()

    if comment.startswith('"') and comment.endswith('"') and len(comment) >= 2:
        comment = comment[1:-1].strip()

    comment = " ".join(comment.split())
    return comment


def _normalize_comment_quality_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    normalized = normalized.replace("đ", "d").replace("Đ", "D")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().casefold()


def _is_no_comment_decision(comment: str) -> bool:
    normalized_comment = _normalize_comment_quality_text(
        _clean_generated_comment(comment)
    )
    return normalized_comment in {"no", "no.", "no!", "no?"}


def _validate_generated_comment_quality(comment: str) -> str:
    cleaned_comment = _clean_generated_comment(comment)
    normalized_comment = _normalize_comment_quality_text(cleaned_comment)
    word_count = len(re.findall(r"\w+", normalized_comment, flags=re.UNICODE))

    if not cleaned_comment:
        raise ValueError("OpenAI returned empty comment")

    if _is_no_comment_decision(cleaned_comment):
        raise NoCommentDecision("AI returned No, skip commenting this post")

    if normalized_comment in BLOCKED_GENERATED_COMMENTS:
        raise ValueError(f"AI comment is too low quality: {cleaned_comment!r}")

    if any(phrase in normalized_comment for phrase in BLOCKED_GENERATED_COMMENT_PHRASES):
        raise ValueError(f"AI comment is negative or refusal-like: {cleaned_comment!r}")

    if len(cleaned_comment) < MIN_GENERATED_COMMENT_CHARS:
        raise ValueError(f"AI comment is too short: {cleaned_comment!r}")

    if word_count < MIN_GENERATED_COMMENT_WORDS:
        raise ValueError(f"AI comment has too few words: {cleaned_comment!r}")

    if re.fullmatch(r"[\W_]+", normalized_comment, flags=re.UNICODE):
        raise ValueError(f"AI comment has no meaningful text: {cleaned_comment!r}")

    return cleaned_comment


def _build_comment_generation_instructions(instructions: str, retry_note: str = "") -> str:
    quality_rules = (
        "If the input is not a real buyer lead or should not be commented, return exactly {\"comment\":\"No\"}.\n"
        "The value No is an internal skip signal only, not a public Facebook comment.\n"
        "If the input should be commented, create a natural Vietnamese Facebook comment for the input post.\n"
        "Return only one JSON object with exactly one key named 'comment'.\n"
        "The comment must be one single sentence, friendly, specific enough, and natural.\n"
        "The comment must have 6 to 20 Vietnamese words.\n"
        "Never return short or one-word public comments such as Ok, Yes, qt, ib, or Inbox.\n"
        "Do not explain. Do not mention that you are an AI."
    )
    if retry_note:
        quality_rules = f"{quality_rules}\n{retry_note}"

    return f"{instructions}\n\n{quality_rules}"


def generate_comment_with_openai(
    post: Dict[str, Any],
    prompt: Union[str, Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
    timeout: int = 45,
    max_attempts: int = 2,
) -> str:
    if not isinstance(post, dict) or not post:
        raise ValueError("Post is required")

    instructions, resolved_model = _resolve_prompt_config(prompt, model=model)
    post_payload = {
        "id": post.get("id"),
        "title": post.get("message") or "",
        "message": post.get("message") or "",
        "created_time": post.get("created_time"),
        "group_id": post.get("group_id"),
    }
    attempts = max(1, int(max_attempts or 1))
    last_error: Exception | None = None
    rejected_comments = []

    for attempt in range(1, attempts + 1):
        retry_note = ""
        if rejected_comments:
            retry_note = (
                "Previous generated comment was rejected as too short or low quality: "
                + ", ".join(repr(comment) for comment in rejected_comments[-3:])
                + ". Generate a different useful Vietnamese comment."
            )

        request_payload = {
            "model": resolved_model,
            "instructions": _build_comment_generation_instructions(
                instructions,
                retry_note=retry_note,
            ),
            "input": json.dumps(post_payload, ensure_ascii=False),
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "generated_comment",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "comment": {
                                "type": "string",
                                "description": "A single natural Vietnamese Facebook comment.",
                            },
                        },
                        "required": ["comment"],
                        "additionalProperties": False,
                    },
                }
            },
        }

        logger.info(
            "Generating AI comment: post_id=%s model=%s timeout=%ss attempt=%s/%s",
            post.get("id"),
            resolved_model,
            timeout,
            attempt,
            attempts,
        )
        response = requests.post(
            OPENAI_RESPONSES_API_URL,
            headers=_build_headers(api_key),
            json=request_payload,
            timeout=timeout,
        )
        if response.status_code != 200:
            logger.error(
                "OpenAI comment request failed: post_id=%s status_code=%s body=%s",
                post.get("id"),
                response.status_code,
                response.text,
            )
            raise Exception(f"OpenAI comment request failed: {response.text}")

        raw_result = _extract_output_text(response.json())
        if not raw_result:
            last_error = ValueError("OpenAI comment response is empty")
            continue

        try:
            parsed_result = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OpenAI comment response is invalid JSON: {raw_result}") from exc

        raw_comment = parsed_result.get("comment", "")
        try:
            comment = _validate_generated_comment_quality(raw_comment)
        except NoCommentDecision:
            logger.info(
                "AI returned No comment decision: post_id=%s attempt=%s/%s",
                post.get("id"),
                attempt,
                attempts,
            )
            raise
        except ValueError as exc:
            last_error = exc
            rejected_comments.append(_clean_generated_comment(raw_comment))
            logger.warning(
                "Rejected generated AI comment: post_id=%s attempt=%s/%s error=%s",
                post.get("id"),
                attempt,
                attempts,
                exc,
            )
            continue

        logger.info(
            "Generated AI comment: post_id=%s comment_length=%s attempt=%s/%s",
            post.get("id"),
            len(comment),
            attempt,
            attempts,
        )
        return comment

    raise ValueError(f"OpenAI did not generate a safe comment: {last_error}")


def filter_posts_with_openai(
    posts: list[Dict[str, Any]],
    prompt: Union[str, Dict[str, Any]],
    api_key: str,
    model: Optional[str] = None,
    timeout: int = 90,
) -> list[Dict[str, Any]]:
    if not isinstance(posts, list) or not posts:
        return []

    instructions, resolved_model = _resolve_prompt_config(prompt, model=model)
    request_posts = [
        {
            "id": post.get("id"),
            "message": post.get("message"),
            "created_time": post.get("created_time"),
        }
        for post in posts
        if isinstance(post, dict) and post.get("id")
    ]
    if not request_posts:
        logger.warning("Skipping OpenAI batch filter because there are no valid posts to send")
        return []

    logger.info(
        "Sending batch posts to OpenAI for evaluation: posts_count=%s model=%s timeout=%ss",
        len(request_posts),
        resolved_model,
        timeout,
    )
    request_payload = {
        "model": resolved_model,
        "instructions": _build_batch_filter_instructions(instructions),
        "input": json.dumps(request_posts, ensure_ascii=False),
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "matched_posts",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "matched_posts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "message": {"type": "string"},
                                    "created_time": {
                                        "type": ["string", "null"],
                                    },
                                },
                                "required": ["id", "message", "created_time"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["matched_posts"],
                    "additionalProperties": False,
                },
            }
        },
    }

    response = requests.post(
        OPENAI_RESPONSES_API_URL,
        headers=_build_headers(api_key),
        json=request_payload,
        timeout=timeout,
    )
    if response.status_code != 200:
        logger.error(
            "OpenAI batch request failed: posts_count=%s status_code=%s body=%s",
            len(request_posts),
            response.status_code,
            response.text,
        )
        raise Exception(f"OpenAI batch request failed: {response.text}")

    logger.debug(
        "OpenAI batch request completed: posts_count=%s status_code=%s",
        len(request_posts),
        response.status_code,
    )
    raw_result = _extract_output_text(response.json())
    if not raw_result:
        logger.error("OpenAI batch filter returned empty response")
        raise ValueError("OpenAI batch filter returned an empty response")

    try:
        parsed_result = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        logger.error(
            "OpenAI batch filter returned invalid JSON raw_result=%s",
            raw_result,
        )
        raise ValueError(f"OpenAI batch filter returned invalid JSON: {raw_result}") from exc

    if not isinstance(parsed_result, dict):
        logger.error(
            "OpenAI batch filter response is not an object: parsed_result=%s",
            parsed_result,
        )
        raise ValueError("OpenAI batch filter response must be a JSON object")

    matched_posts_payload = parsed_result.get("matched_posts")
    if not isinstance(matched_posts_payload, list):
        logger.error(
            "OpenAI batch filter response missing matched_posts list: parsed_result=%s",
            parsed_result,
        )
        raise ValueError("OpenAI batch filter response must include 'matched_posts' list")

    original_posts_by_id = {
        str(post.get("id")): post
        for post in posts
        if isinstance(post, dict) and post.get("id")
    }
    matched_posts = []
    matched_ids = set()
    unknown_ids = []

    for item in matched_posts_payload:
        if not isinstance(item, dict):
            continue

        post_id = str(item.get("id") or "").strip()
        if not post_id or post_id in matched_ids:
            continue

        original_post = original_posts_by_id.get(post_id)
        if not original_post:
            unknown_ids.append(post_id)
            continue

        matched_ids.add(post_id)
        matched_posts.append(original_post)

    logger.info(
        "OpenAI batch filter completed: input_posts=%s matched_posts=%s ignored_unknown_ids=%s",
        len(request_posts),
        len(matched_posts),
        len(unknown_ids),
    )
    if unknown_ids:
        logger.warning(
            "OpenAI batch filter returned ids not found in original input: ids=%s",
            unknown_ids[:20],
        )

    return matched_posts
