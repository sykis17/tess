import re

from bs4 import BeautifulSoup

_EXCERPT_MAX_CHARS = 2000
_PREVIEW_CHARS = 500


def html_to_text(html: str) -> str:
    """Extract readable text from HTML, preferring article/main content."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    content = soup.find("article") or soup.find("main") or soup.find("body")
    if content is None:
        content = soup

    text = content.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_EXCERPT_MAX_CHARS]


def make_excerpt(text: str, max_chars: int = _PREVIEW_CHARS) -> str:
    """Truncate extracted text to a preview excerpt."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"
