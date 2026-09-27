"""Safe template rendering for admin-managed notification copy."""

from __future__ import annotations

import re
from typing import Any, Mapping

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*(?:\|\s*([a-z_]+)\s*)?}}")
MAX_DEPTH = 5


class TemplateRenderError(ValueError):
    """Raised when a template references a value that is unavailable."""



def _apply_filter(value: Any, filter_name: str) -> Any:
    name = filter_name.lower()
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "title":
        return str(value).title()
    if name == "trim":
        return str(value).strip()
    if name == "date":
        text = str(value)
        return text.split("T")[0]
    if name == "time":
        text = str(value)
        return text.split("T")[-1][:5] if "T" in text else text
    raise TemplateRenderError(f"Unsupported template filter '{filter_name}'.")



def render(template: str, context: Mapping[str, Any], *, strict: bool = False) -> str:
    """Substitute ``{{ placeholders }}`` using a controlled context.

    ``strict=True`` is used for real/test delivery. Missing variables raise a
    controlled error so an admin typo cannot silently produce broken copy.
    ``strict=False`` remains useful for lightweight previews and legacy tests.
    """
    if not template:
        return ""

    result = template
    for _ in range(MAX_DEPTH):
        def _replace(match: re.Match[str]) -> str:
            raw_key, filter_name = match.group(1), match.group(2)
            key = raw_key.split(".")[-1]
            if key not in context:
                if strict:
                    raise TemplateRenderError(f"Missing template variable '{raw_key}'.")
                value = ""
            else:
                value = context.get(key)
            if value is None:
                if strict:
                    raise TemplateRenderError(f"Template variable '{raw_key}' has no value.")
                value = ""
            if filter_name:
                value = _apply_filter(value, filter_name)
            return str(value)

        new_result = PLACEHOLDER_RE.sub(_replace, result)
        if new_result == result:
            break
        result = new_result

    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()



def extract_placeholders(*texts: str) -> list[str]:
    """Return sorted unique placeholder names used across *texts*."""
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in PLACEHOLDER_RE.finditer(text):
            found.add(match.group(1).split(".")[-1])
    return sorted(found)



def render_subject(subject: str, context: Mapping[str, Any], channel_label: str) -> str:
    rendered = render(subject or "", context, strict=True)
    return rendered or f"Notification from {channel_label}"
