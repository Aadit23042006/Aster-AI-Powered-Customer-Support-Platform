"""Provider interfaces for Phase 4 multimodal services.

The application depends on these small protocols rather than a vendor-specific
API throughout the feature code.
"""
from __future__ import annotations

from typing import Protocol


class VisionProvider(Protocol):
    def analyze(self, image: bytes, *, mime_type: str, prompt: str) -> str: ...


class GeminiVisionProvider:
    def __init__(self, api_key: str, model: str):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def analyze(
        self,
        image: bytes,
        *,
        mime_type: str,
        prompt: str,
    ) -> str:
        from google.genai import types

        request_config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_bytes(
                    data=image,
                    mime_type=mime_type,
                ),
                prompt,
            ],
            config=request_config,
        )

        return response.text or ""