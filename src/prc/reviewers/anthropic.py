from anthropic import Anthropic

from ._registry import register_family
from .base import Reviewer


@register_family("anthropic")
class AnthropicReviewer(Reviewer):
    def __init__(self, model: str, api_key: str, **_: object) -> None:
        self.model = model
        self.display_name = model
        self._client = Anthropic(api_key=api_key)

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user}],
            timeout=timeout,
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )
