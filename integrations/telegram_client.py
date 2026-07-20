# Telegram API client
import logging

import requests

from utils.security import mask_secret

logger = logging.getLogger(__name__)


def _build_chat_id(idchat):
    normalized_idchat = str(idchat or "").strip()
    if not normalized_idchat:
        return ""
    if normalized_idchat.startswith("-"):
        return normalized_idchat
    return f"-{normalized_idchat}"


def _sanitize_error(error, token_tele):
    error_text = str(error)
    token_value = str(token_tele or "")
    if token_value:
        error_text = error_text.replace(token_value, mask_secret(token_value))
    return error_text


def send_document(file_path, token_tele, idchat, caption=None, parse_mode="HTML"):
    if not file_path:
        logger.warning("Document path is empty, not sending.")
        return {
            "status": "error",
            "message": "Document path is empty.",
        }

    if not token_tele or not idchat:
        logger.warning("Telegram config is missing, not sending document.")
        return {
            "status": "error",
            "message": "Telegram config is missing.",
        }

    try:
        with open(file_path, "rb") as document:
            data = {
                "chat_id": _build_chat_id(idchat),
                "caption": caption or "",
            }

            if parse_mode:
                data["parse_mode"] = parse_mode

            post = requests.post(
                f"https://api.telegram.org/bot{token_tele}/sendDocument",
                data=data,
                files={"document": document},
                timeout=60,
            )

        result = post.json()

        return {
            "status": "success" if result.get("ok") else "error",
            "message": "Document sent successfully."
            if result.get("ok")
            else result.get("description", "Failed to send document."),
        }

    except Exception as e:
        safe_error = _sanitize_error(e, token_tele)
        logger.error("Failed to send document with Telegram token=%s: %s", mask_secret(token_tele), safe_error)
        return {
            "status": "error",
            "message": safe_error,
        }
