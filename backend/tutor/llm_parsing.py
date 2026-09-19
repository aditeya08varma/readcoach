"""Shared helpers for parsing a Claude `messages.create` response into plain
text / JSON.

Extracted from `claude_client.py` (owned by tutor-logic-engineer) after an
audit found `_text_of`/`_strip_code_fence`/`_parse_json_object` copy-pasted
verbatim into `backend/eval/judge_client.py` (owned by eval-engineer) -  both
modules make the exact same "respond with ONLY JSON, no prose, no code
fences" request of Claude and needed the exact same three-step unwrap. This
module is the one place that logic now lives; both callers import it.

Lives in `backend/tutor` rather than a new top-level shared package because
`backend/eval` already reaches into `backend/tutor` via a `sys.path.insert`
(see `judge_client.py`, `groundedness_eval.py`, `latency_eval.py`,
`diagnostic_eval.py`) to import `claude_client`/`alignment` - this follows
that same established cross-directory-import convention instead of inventing
a second one.
"""

from __future__ import annotations

import json


def text_of(response) -> str:
    """Concatenate every text block of an Anthropic `Message` response."""
    return "".join(block.text for block in response.content if block.type == "text")


def strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ``` markdown code fence, if present - Claude
    occasionally wraps a "JSON only" response in one despite being asked not
    to.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def parse_json_object(text: str) -> dict:
    """Parse a JSON object out of `text`, tolerating a code fence and any
    stray prose before/after the braces (finds the outermost `{...}`).
    """
    text = strip_code_fence(text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array out of `text`, same tolerance as `parse_json_object`."""
    text = strip_code_fence(text)
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start : end + 1])
