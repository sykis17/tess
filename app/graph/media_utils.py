from app.graph.schemas import ContentType

MEDIA_AGENTS = frozenset({"photo", "video", "audio"})


def is_image_url(content: str) -> bool:
    """Return True when content is an HTTP(S) URL or data URI suitable for images."""
    return (
        content.startswith("http://")
        or content.startswith("https://")
        or content.startswith("data:")
    )


def is_media_url(content: str) -> bool:
    """Return True when content is an HTTP(S) URL suitable for video or audio playback."""
    return content.startswith("http://") or content.startswith("https://")


def resolve_content_type(source_agent: str, content: str) -> ContentType:
    """Infer Panel content_type from specialist agent and response content."""
    first_line = content.strip().split("\n", 1)[0].strip()

    if source_agent == "photo" and is_image_url(first_line):
        return "image"
    if source_agent == "video" and is_media_url(first_line):
        return "video"
    if source_agent == "audio" and is_media_url(first_line):
        return "audio"
    return "markdown"


def extract_typed_media_content(content: str, content_type: ContentType) -> str:
    """For typed media panels, use the first-line URL; otherwise return full content."""
    if content_type in ("image", "video", "audio"):
        return content.strip().split("\n", 1)[0].strip()
    return content
