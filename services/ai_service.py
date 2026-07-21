import requests
from typing import Dict

from app_config import OPENAI_MODEL_NAME



class OpenAIService:
    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = OPENAI_MODEL_NAME, timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def mask_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 12:
            return self.api_key[:4] + "..." if len(self.api_key) > 4 else self.api_key
        return f"{self.api_key[:7]}...{self.api_key[-4:]}"

    def list_models(self) -> Dict:
        try:
            res = requests.get(
                f"{self.BASE_URL}/models",
                headers=self._headers(),
                timeout=self.timeout
            )

            if res.status_code == 200:
                data = res.json().get("data", [])
                model_ids = sorted([m.get("id", "") for m in data if m.get("id")])
                return {
                    "ok": True,
                    "models": model_ids,
                    "count": len(model_ids),
                }

            elif res.status_code == 401:
                return {"ok": False, "message": "API key không hợp lệ hoặc đã bị thu hồi"}

            elif res.status_code == 403:
                return {"ok": False, "message": "Không có quyền truy cập"}

            else:
                return {"ok": False, "message": f"{res.status_code}: {res.text}"}

        except Exception as e:
            return {"ok": False, "message": str(e)}

    def check_api_key(self) -> Dict:
        model_result = self.list_models()
        if not model_result.get("ok"):
            return {
                "valid": False,
                "message": model_result.get("message", "Không kiểm tra được API key"),
                "masked_key": self.mask_key(),
            }

        models = model_result.get("models", [])
        default_model_ok = self.model in models

        return {
            "valid": True,
            "message": "API key hợp lệ",
            "masked_key": self.mask_key(),
            "default_model": self.model,
            "default_model_ok": default_model_ok,
            "models_count": len(models),
            "sample_models": models[:20],
        }

