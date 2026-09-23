from __future__ import annotations

import html
import re
from urllib.parse import urlparse


FENCED_CODE_RE = re.compile(r"```(?:[^\n`]*)\n?(.*?)```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\[([^\]\n]+)]\((https?://[^\s)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
HARD_BREAK_RE = re.compile(r"\\[ \t]*\r?\n")


def render_telegram_html(markdown: str) -> str:
    """Convert a safe Markdown subset emitted by the LLM to Telegram HTML.

    Arbitrary HTML is escaped first. Only balanced tags created by this
    function are returned, so model output cannot inject unsupported markup.
    """
    text = HARD_BREAK_RE.sub("\n", markdown).strip()
    placeholders: list[str] = []

    def stash(value: str) -> str:
        token = f"\x00GAIKA{len(placeholders)}\x00"
        placeholders.append(value)
        return token

    def replace_fenced(match: re.Match[str]) -> str:
        code = match.group(1).strip("\n")
        return stash(f"<pre><code>{html.escape(code)}</code></pre>")

    def replace_inline(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(match.group(1))}</code>")

    def replace_link(match: re.Match[str]) -> str:
        label, url = match.groups()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return match.group(0)
        safe_url = html.escape(url, quote=True)
        safe_label = html.escape(label)
        return stash(f'<a href="{safe_url}">{safe_label}</a>')

    text = FENCED_CODE_RE.sub(replace_fenced, text)
    text = INLINE_CODE_RE.sub(replace_inline, text)
    text = LINK_RE.sub(replace_link, text)
    text = html.escape(text)
    text = BOLD_RE.sub(r"<b>\1</b>", text)
    text = STRIKE_RE.sub(r"<s>\1</s>", text)
    text = ITALIC_RE.sub(r"<i>\1</i>", text)

    for index, value in enumerate(placeholders):
        text = text.replace(f"\x00GAIKA{index}\x00", value)
    return text
