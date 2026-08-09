"""Small local models don't reliably emit *only* JSON -- they wrap it in
prose or markdown fences. This pulls the first balanced {...} block out of
whatever text came back instead of requiring exact-format compliance."""
import json
import re


def extract_json(text: str) -> dict:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in: {text!r}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError(f"unbalanced JSON object in: {text!r}")
