from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    role: MessageRole
    content: str


class LLMConfig(BaseModel):
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = None


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    config: LLMConfig | None = None


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    raw: dict[str, Any] | None = None


def extract_content(content: str | list[str | dict[str, Any]]) -> str:
    """Normalize LangChain message content to a plain string."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and "text" in part:
            parts.append(str(part["text"]))
    return "".join(parts)


def to_langchain_messages(messages: list[LLMMessage]) -> list[BaseMessage]:
    """Convert TESS message models to LangChain message objects."""
    lc_messages: list[BaseMessage] = []
    for message in messages:
        match message.role:
            case "system":
                lc_messages.append(SystemMessage(content=message.content))
            case "user":
                lc_messages.append(HumanMessage(content=message.content))
            case "assistant":
                lc_messages.append(AIMessage(content=message.content))
    return lc_messages
