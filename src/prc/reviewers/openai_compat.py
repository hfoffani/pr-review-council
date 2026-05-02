from openai import OpenAI

from ._registry import register_family
from .base import Reviewer


@register_family("openai-compatible")
class OpenAICompatibleReviewer(Reviewer):
    def __init__(
        self, model: str, api_key: str, base_url: str, **_: object
    ) -> None:
        self.model = model
        self.display_name = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=timeout,
        )
        return resp.choices[0].message.content or ""
