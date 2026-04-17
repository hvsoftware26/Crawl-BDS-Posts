# Telegram API client
import logging

import requests

logger = logging.getLogger(__name__)


def _build_chat_id(idchat):
    normalized_idchat = str(idchat or "").strip()
    if not normalized_idchat:
        return ""
    if normalized_idchat.startswith("-"):
        return normalized_idchat
    return f"-{normalized_idchat}"


def send_message(message, token_tele, idchat):
    if message == "":
        logger.warning("Message is empty, not sending.")
        return {
            "status": "error",
            "message": "Message is empty, not sent.",
        }
    if not token_tele or not idchat:
        logger.warning("Telegram config is missing, not sending message.")
        return {
            "status": "error",
            "message": "Telegram config is missing.",
        }

    post = requests.get(
        f"https://api.telegram.org/bot{token_tele}/sendMessage",
        params={
            "chat_id": _build_chat_id(idchat),
            "text": message,
        },
        timeout=30,
    )
    return {
        "status": "success" if post.json().get("ok") else "error",
        "message": "Message sent successfully."
        if post.json().get("ok")
        else "Failed to send message.",
    }


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
        logger.exception("Failed to send document: %s", e)
        return {
            "status": "error",
            "message": str(e),
        }

