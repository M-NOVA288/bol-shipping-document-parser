"""Optional AI fallback for documents the rule-based parser can't fully read.

When regex extraction leaves required fields empty, this module can send the
raw text to an LLM and ask for the same JSON shape back. The result goes
through the exact same validation as a regex parse, so the model never gets to
skip a check. It only runs when ANTHROPIC_API_KEY is set and --llm is passed.

Uses only the standard library so the project stays dependency-free.
"""

from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("BOL_LLM_MODEL", "claude-haiku-5-5")

PROMPT = """Extract shipping data from the document below. Reply with JSON only, no prose.
Use null for anything not present. Do not guess values that are not in the text.

Schema:
{{"bol_number": str, "ship_date": "YYYY-MM-DD", "carrier": str, "scac": str,
  "po_number": str,
  "ship_from": {{"name": str, "street": str, "city": str, "state": str, "zip": str}},
  "ship_to": {{"name": str, "street": str, "city": str, "state": str, "zip": str}},
  "line_items": [{{"product_code": str, "description": str, "quantity": int,
                   "weight": float, "weight_unit": "lbs"|"kg", "weight_lbs": float}}],
  "total_weight_lbs": float, "hazmat": bool, "special_instructions": str}}

Document:
<document>
{text}
</document>"""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def extract_with_llm(text: str, timeout: int = 60) -> dict:
    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
        }
    ).encode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    reply = "".join(block.get("text", "") for block in payload.get("content", []))
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model reply did not contain JSON")
    return json.loads(reply[start : end + 1])


def merge(regex_result: dict, llm_result: dict) -> dict:
    """Keep every regex value; only fill gaps from the model."""
    merged = dict(regex_result)
    for key, value in llm_result.items():
        if key in merged and not merged[key] and value:
            merged[key] = value
    return merged
