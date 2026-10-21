"""Read a JSON list out of a language model reply, even when the reply is messy or was cut off."""
from __future__ import annotations

import json
import re


def parse_json_list(reply: str) -> list[dict]:
    """Return every complete object in the first JSON array of the reply.

    Handles code fences, text before or after the array, and a reply that stopped in the middle
    (the objects before the break are kept). Returns [] when nothing can be read.
    """
    text = re.sub(r"```(?:json)?", "", reply or "").strip()
    start = text.find("[")
    if start == -1:
        return []
    try:                                                    # the whole array, the normal case
        whole = json.loads(text[start:text.rfind("]") + 1])
        if isinstance(whole, list):
            return [x for x in whole if isinstance(x, dict)]
    except ValueError:
        pass
    decoder, position, items = json.JSONDecoder(), start + 1, []
    while True:                                             # a broken or truncated array: keep the good objects
        brace = text.find("{", position)
        if brace == -1:
            break
        try:
            item, position = decoder.raw_decode(text, brace)
        except ValueError:
            break
        if isinstance(item, dict):
            items.append(item)
    return items
