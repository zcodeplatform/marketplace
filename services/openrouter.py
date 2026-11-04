import json

import requests


class OpenRouterError(Exception):
    pass


class OpenRouter:
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key, site_url="", app_name="Comrade Marketplace"):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": app_name,
        }
        if site_url:
            self.headers["HTTP-Referer"] = site_url

    def stream_chat(self, messages, model):
        try:
            response = requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 500,
                },
                stream=True,
                timeout=(10, 90),
            )
        except requests.exceptions.RequestException as error:
            raise OpenRouterError("Could not connect to the AI provider.") from error

        if not response.ok:
            response.close()
            raise OpenRouterError(
                f"The AI provider returned HTTP {response.status_code}."
            )

        try:
            response.encoding = "utf-8"
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise OpenRouterError("The AI provider could not complete the reply.")
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if isinstance(content, str) and content:
                    yield content
        except requests.exceptions.RequestException as error:
            raise OpenRouterError("The connection to the AI provider was interrupted.") from error
        finally:
            response.close()
