from google import genai
from google.genai import types as genai_types

from ._registry import register_family
from .base import Reviewer


@register_family("google")
class GoogleReviewer(Reviewer):
    def __init__(self, model: str, api_key: str, **_: object) -> None:
        self.model = model
        self.display_name = model
        self._client = genai.Client(api_key=api_key)

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                http_options=genai_types.HttpOptions(
                    timeout=int(timeout * 1000),
                ),
            ),
        )
        return resp.text or ""
