"""HTML page importer — normalize pasted or fetched HTML into AgentSite page files.

Pure functions (stdlib only) that turn raw HTML into the file map stored for a
mockup-mode page version: ``index.html`` plus an optional extracted
``styles.css``. Also provides ``fetch_page`` for URL imports.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<html[\s>]", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_CHARSET_RE = re.compile(r"<meta[^>]+charset", re.IGNORECASE)
_ATTR_URL_RE = re.compile(r"(\s(?:src|href)\s*=\s*)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)

_SKIP_SCHEMES = ("http://", "https://", "data:", "mailto:", "tel:", "javascript:", "#", "//")


def _extract_styles(html: str) -> tuple[str, list[str]]:
    """Remove ``<style>`` blocks from the HTML, returning (html, css_chunks)."""
    chunks: list[str] = []

    def _collect(match: re.Match) -> str:
        css = match.group(1).strip()
        if css:
            chunks.append(css)
        return ""

    return _STYLE_BLOCK_RE.sub(_collect, html), chunks


def _ensure_head_tag(html: str) -> str:
    """Insert an empty ``<head></head>`` after ``<html ...>`` if none exists."""
    if re.search(r"<head[\s>]", html, re.IGNORECASE):
        return html
    match = re.search(r"<html[^>]*>", html, re.IGNORECASE)
    if match:
        return html[: match.end()] + "\n<head></head>" + html[match.end() :]
    return html


def _insert_into_head(html: str, snippet: str) -> str:
    """Insert a snippet right after the opening ``<head>`` tag."""
    html = _ensure_head_tag(html)
    match = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if match:
        return html[: match.end()] + "\n" + snippet + html[match.end() :]
    return html


def normalize_html(html: str, *, extract_css: bool = True) -> dict[str, str]:
    """Normalize raw HTML into an AgentSite page file map.

    Returns ``{"index.html": ..., "styles.css": ...}`` (styles.css only when
    ``extract_css`` is True and at least one ``<style>`` block was found).

    - Extracts ``<style>`` blocks into ``styles.css`` and links it from the head.
    - Ensures the document starts with ``<!DOCTYPE html>``.
    - Ensures ``<meta charset="utf-8">`` is present in the head.
    - Wraps bare fragments (no ``<html>`` tag) in a minimal document.
    """
    html = html.strip()
    files: dict[str, str] = {}

    # Wrap bare fragments in a minimal document
    if not _HTML_TAG_RE.search(html):
        html = (
            "<html>\n<head>\n"
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "</head>\n<body>\n" + html + "\n</body>\n</html>"
        )

    # Extract inline styles into styles.css
    if extract_css:
        html, css_chunks = _extract_styles(html)
        if css_chunks:
            files["styles.css"] = "\n\n".join(css_chunks) + "\n"
            html = _insert_into_head(html, '<link rel="stylesheet" href="styles.css">')

    # Ensure charset meta
    if not _CHARSET_RE.search(html):
        html = _insert_into_head(html, '<meta charset="utf-8">')

    # Ensure doctype
    if not _DOCTYPE_RE.match(html):
        html = "<!DOCTYPE html>\n" + html

    files["index.html"] = html + ("\n" if not html.endswith("\n") else "")
    return files


def absolutize_urls(html: str, base_url: str) -> str:
    """Rewrite relative ``src=``/``href=`` attribute values to absolute URLs.

    Skips values that are already absolute or use non-fetchable schemes
    (``data:``, ``mailto:``, ``tel:``, ``javascript:``, ``#`` anchors,
    protocol-relative ``//``).
    """

    def _rewrite(match: re.Match) -> str:
        prefix, quote, value = match.group(1), match.group(2), match.group(3).strip()
        if not value or value.lower().startswith(_SKIP_SCHEMES):
            return match.group(0)
        return f"{prefix}{quote}{urljoin(base_url, value)}{quote}"

    return _ATTR_URL_RE.sub(_rewrite, html)


async def fetch_page(url: str, *, timeout: float = 20.0, max_bytes: int = 5_000_000) -> str:
    """Fetch an HTML page from a URL and absolutize its relative URLs.

    Raises ``ValueError`` with a friendly message on non-2xx responses,
    non-HTML content types, or responses larger than ``max_bytes``.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise ValueError(f"Could not fetch URL: {exc}") from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        raise ValueError(f"Fetch failed with status {resp.status_code}")

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and content_type not in ("text/html", "application/xhtml+xml"):
        raise ValueError(f"URL did not return HTML (content-type: {content_type})")

    if len(resp.content) > max_bytes:
        raise ValueError(f"Page is too large ({len(resp.content)} bytes, max {max_bytes})")

    return absolutize_urls(resp.text, str(resp.url))
