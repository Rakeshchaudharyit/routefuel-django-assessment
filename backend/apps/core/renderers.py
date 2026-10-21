"""JSON renderer that can embed pre-encoded JSON fragments without re-encoding them."""

from __future__ import annotations

import json
import uuid
from typing import Any

from rest_framework.renderers import JSONRenderer
from rest_framework.utils import encoders


class RawJSON:
    """Already-encoded JSON text to be inserted into a response verbatim.

    Only wrap text produced by ``json.dumps`` (it is trusted to be valid JSON).
    """

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class RawJSONRenderer(JSONRenderer):
    """``JSONRenderer`` plus ``RawJSON`` support.

    A large route geometry is already JSON text in the cache; encoding it again would cost
    tens of milliseconds per response. Each ``RawJSON`` is written as a unique placeholder
    string, then the placeholder (with its quotes) is replaced by the raw text.
    """

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        if data is None:
            return b""
        fragments: dict[str, str] = {}
        prefix = f"__rawjson_{uuid.uuid4().hex}_"

        class Encoder(encoders.JSONEncoder):
            def default(self, o: Any) -> Any:
                if isinstance(o, RawJSON):
                    token = f"{prefix}{len(fragments)}"
                    fragments[token] = o.text
                    return token
                return super().default(o)

        renderer_context = renderer_context or {}
        indent = self.get_indent(accepted_media_type, renderer_context)
        separators = (",", ":") if indent is None and self.compact else (",", ": ")
        text = json.dumps(
            data,
            cls=Encoder,
            indent=indent,
            ensure_ascii=self.ensure_ascii,
            allow_nan=not self.strict,
            separators=separators,
        )
        for token, fragment in fragments.items():
            text = text.replace(f'"{token}"', fragment, 1)
        # Same escaping DRF applies: U+2028/2029 are valid JSON but break JavaScript.
        text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        return text.encode()
