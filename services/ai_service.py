import requests
from typing import Optional, Dict, List



class OpenAIService:
    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = "gpt-5-mini", timeout: int = 30):
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

    def check_model(self) -> Dict:
        result = self.list_models()
        if not result.get("ok"):
            return {"ok": False, "message": result.get("message", "Không tải được danh sách model")}

        models = result.get("models", [])
        if self.model in models:
            return {"ok": True, "message": f"Model {self.model} dùng được"}
        return {"ok": False, "message": f"Model {self.model} không dùng được hoặc chưa được cấp quyền"}

    def ask(self, prompt: str) -> Dict:
        try:
            res = requests.post(
                f"{self.BASE_URL}/responses",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "input": prompt
                },
                timeout=self.timeout
            )

            if res.status_code == 200:
                data = res.json()
                output_text = data.get("output_text", "")

                if not output_text:
                    try:
                        output = data.get("output", [])
                        parts = []
                        for item in output:
                            for content in item.get("content", []):
                                text = content.get("text")
                                if text:
                                    parts.append(text)
                        output_text = "\n".join(parts).strip()
                    except Exception:
                        output_text = str(data)

                return {
                    "ok": True,
                    "response": output_text,
                    "raw": data
                }

            elif res.status_code == 401:
                return {"ok": False, "message": "API key không hợp lệ hoặc đã bị thu hồi"}

            elif res.status_code == 403:
                return {"ok": False, "message": "Không có quyền dùng model hoặc endpoint này"}

            elif res.status_code == 429:
                return {"ok": False, "message": "Hết quota, billing bị tắt hoặc bị giới hạn tốc độ"}

            else:
                return {"ok": False, "message": f"{res.status_code}: {res.text}"}

        except Exception as e:
            return {"ok": False, "message": str(e)}
