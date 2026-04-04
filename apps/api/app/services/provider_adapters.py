from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


PROVIDER_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "openai_compatible": "openai_compatible",
    "openai-compatible": "openai_compatible",
    "deepseek": "openai_compatible",
    "kimi": "openai_compatible",
    "qwen": "openai_compatible",
    "dashscope": "openai_compatible",
    "hunyuan": "openai_compatible",
    "tencent_hunyuan": "openai_compatible",
}


@dataclass(slots=True)
class ModelCapability:
    supports_chat: bool
    supports_stream: bool
    supports_embeddings: bool
    supports_vision: bool = False
    supports_tools: bool = False
    supports_json_mode: bool = False


@dataclass(slots=True)
class ProviderConfig:
    provider: str
    api_base: str
    api_key: str
    model: str
    api_version: str | None = None
    timeout: float = 60.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    organization: str | None = None
    project: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class ChatRequest:
    provider: str
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int | None = None
    stream: bool = False
    system_prompt: str | None = None
    tools: list[dict[str, Any]] | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatResponse:
    provider: str
    model: str
    text: str
    usage: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(slots=True)
class EmbedRequest:
    provider: str
    model: str
    inputs: list[str]
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmbedResponse:
    provider: str
    model: str
    embeddings: list[list[float]]
    usage: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        code: str,
        retryable: bool,
        status_code: int | None = None,
        detail: str | None = None,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.detail = detail or message
        self.raw_response = raw_response


def normalize_provider_name(provider: str | None) -> str:
    normalized = (provider or "openai_compatible").strip().lower()
    return PROVIDER_ALIASES.get(normalized, normalized)


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _summarize_error(text: str, limit: int = 400) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _map_error_code(status_code: int | None, detail: str) -> str:
    upper = detail.upper()
    if status_code == 400:
        return "BAD_REQUEST"
    if status_code in {401, 403}:
        return "AUTH_ERROR"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 429 or "RESOURCE_EXHAUSTED" in upper:
        return "RATE_LIMIT"
    if status_code is not None and 500 <= status_code < 600:
        return "PROVIDER_ERROR"
    return "NETWORK_ERROR" if status_code is None else "UNKNOWN_ERROR"


def _build_auth_headers(provider: str, config: ProviderConfig) -> dict[str, str]:
    provider_name = normalize_provider_name(provider)
    headers = dict(config.extra_headers)
    headers["Content-Type"] = "application/json"
    if provider_name == "anthropic":
        headers["x-api-key"] = config.api_key
        headers["anthropic-version"] = config.api_version or "2023-06-01"
        return headers
    if provider_name == "gemini":
        headers["x-goog-api-key"] = config.api_key
        return headers

    headers["Authorization"] = f"Bearer {config.api_key}"
    if config.organization:
        headers["OpenAI-Organization"] = config.organization
    if config.project:
        headers["OpenAI-Project"] = config.project
    return headers


def _post_json(
    *,
    provider: str,
    config: ProviderConfig,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    req = request.Request(
        _join_url(config.api_base, path),
        data=json.dumps(payload).encode("utf-8"),
        headers=_build_auth_headers(provider, config),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="ignore")
        detail = _summarize_error(raw_detail or str(exc.reason or "HTTP error"))
        code = _map_error_code(exc.code, detail)
        retryable = code in {"RATE_LIMIT", "PROVIDER_ERROR"}
        raise ProviderRequestError(
            f"{provider} 请求失败({exc.code}): {detail}",
            provider=normalize_provider_name(provider),
            code=code,
            retryable=retryable,
            status_code=exc.code,
            detail=detail,
            raw_response=raw_detail,
        ) from exc
    except URLError as exc:
        detail = _summarize_error(str(exc.reason or "network error"))
        raise ProviderRequestError(
            f"{provider} 连接失败: {detail}",
            provider=normalize_provider_name(provider),
            code="NETWORK_ERROR",
            retryable=True,
            detail=detail,
        ) from exc


def _model_path(model: str) -> str:
    return model if model.startswith("models/") else f"models/{model}"


class BaseProviderAdapter:
    provider_name = "base"
    capabilities = ModelCapability(
        supports_chat=False,
        supports_stream=False,
        supports_embeddings=False,
    )

    def _ensure_capability(self, capability_name: str, supported: bool) -> None:
        if supported:
            return
        raise ProviderRequestError(
            f"{self.provider_name} 不支持 {capability_name}",
            provider=self.provider_name,
            code="UNSUPPORTED_CAPABILITY",
            retryable=False,
            detail=f"{self.provider_name} 不支持 {capability_name}",
        )

    def generate(self, config: ProviderConfig, chat_request: ChatRequest) -> ChatResponse:
        self._ensure_capability("chat", self.capabilities.supports_chat)
        raise NotImplementedError

    def generate_stream(self, config: ProviderConfig, chat_request: ChatRequest) -> Any:
        self._ensure_capability("stream", self.capabilities.supports_stream)
        raise NotImplementedError

    def embed_texts(self, config: ProviderConfig, embed_request: EmbedRequest) -> EmbedResponse:
        self._ensure_capability("embeddings", self.capabilities.supports_embeddings)
        raise NotImplementedError

    def healthcheck(self, config: ProviderConfig) -> bool:
        if self.capabilities.supports_embeddings:
            self.embed_texts(
                config,
                EmbedRequest(provider=config.provider, model=config.model, inputs=["ping"]),
            )
            return True
        if self.capabilities.supports_chat:
            self.generate(
                config,
                ChatRequest(
                    provider=config.provider,
                    model=config.model,
                    messages=[ChatMessage(role="user", content="请仅回复 pong")],
                    max_tokens=32,
                ),
            )
            return True
        raise ProviderRequestError(
            f"{self.provider_name} 当前未实现 healthcheck",
            provider=self.provider_name,
            code="UNSUPPORTED_CAPABILITY",
            retryable=False,
        )


class OpenAIAdapter(BaseProviderAdapter):
    provider_name = "openai"
    capabilities = ModelCapability(
        supports_chat=True,
        supports_stream=False,
        supports_embeddings=True,
        supports_tools=True,
        supports_json_mode=True,
    )

    def generate(self, config: ProviderConfig, chat_request: ChatRequest) -> ChatResponse:
        input_messages: list[dict[str, Any]] = []
        if chat_request.system_prompt:
            input_messages.append(
                {"role": "system", "content": [{"type": "input_text", "text": chat_request.system_prompt}]}
            )
        for message in chat_request.messages:
            input_messages.append(
                {"role": message.role, "content": [{"type": "input_text", "text": message.content}]}
            )
        payload: dict[str, Any] = {
            "model": config.model,
            "input": input_messages,
            "temperature": chat_request.temperature,
            "stream": False,
        }
        if chat_request.max_tokens is not None:
            payload["max_output_tokens"] = chat_request.max_tokens
        if config.extra_params:
            payload.update(config.extra_params)
        if chat_request.extra_params:
            payload.update(chat_request.extra_params)

        data = _post_json(provider=self.provider_name, config=config, path="/responses", payload=payload)
        text = data.get("output_text")
        if not isinstance(text, str) or not text.strip():
            output = data.get("output") or []
            text_parts: list[str] = []
            for item in output:
                for content in item.get("content", []):
                    candidate = content.get("text")
                    if isinstance(candidate, str) and candidate.strip():
                        text_parts.append(candidate.strip())
            text = "\n".join(text_parts).strip()
        if not text:
            raise ProviderRequestError(
                "OpenAI 未返回有效文本内容",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                detail="OpenAI 未返回有效文本内容",
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        return ChatResponse(
            provider=self.provider_name,
            model=config.model,
            text=text,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            raw_response=data,
        )

    def embed_texts(self, config: ProviderConfig, embed_request: EmbedRequest) -> EmbedResponse:
        payload: dict[str, Any] = {"model": config.model, "input": embed_request.inputs}
        if config.extra_params:
            payload.update(config.extra_params)
        if embed_request.extra_params:
            payload.update(embed_request.extra_params)
        data = _post_json(provider=self.provider_name, config=config, path="/embeddings", payload=payload)
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderRequestError(
                "OpenAI Embedding 响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        embeddings = [item.get("embedding") for item in items]
        return EmbedResponse(
            provider=self.provider_name,
            model=config.model,
            embeddings=embeddings,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            raw_response=data,
        )


class OpenAICompatibleAdapter(BaseProviderAdapter):
    provider_name = "openai_compatible"
    capabilities = ModelCapability(
        supports_chat=True,
        supports_stream=False,
        supports_embeddings=True,
        supports_tools=False,
        supports_json_mode=False,
    )

    def generate(self, config: ProviderConfig, chat_request: ChatRequest) -> ChatResponse:
        payload_messages: list[dict[str, str]] = []
        if chat_request.system_prompt:
            payload_messages.append({"role": "system", "content": chat_request.system_prompt})
        payload_messages.extend({"role": msg.role, "content": msg.content} for msg in chat_request.messages)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": payload_messages,
            "temperature": chat_request.temperature,
        }
        if chat_request.max_tokens is not None:
            payload["max_tokens"] = chat_request.max_tokens
        if config.extra_params:
            payload.update(config.extra_params)
        if chat_request.extra_params:
            payload.update(chat_request.extra_params)
        data = _post_json(provider=self.provider_name, config=config, path="/chat/completions", payload=payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError(
                "兼容 OpenAI 的聊天响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, list):
            text = "\n".join(
                item.get("text", "").strip() for item in content if isinstance(item, dict) and item.get("text")
            ).strip()
        else:
            text = content.strip() if isinstance(content, str) else ""
        if not text:
            raise ProviderRequestError(
                "兼容 OpenAI 的聊天接口未返回有效文本",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        return ChatResponse(
            provider=self.provider_name,
            model=config.model,
            text=text,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            raw_response=data,
        )

    def embed_texts(self, config: ProviderConfig, embed_request: EmbedRequest) -> EmbedResponse:
        payload: dict[str, Any] = {"model": config.model, "input": embed_request.inputs}
        if config.extra_params:
            payload.update(config.extra_params)
        if embed_request.extra_params:
            payload.update(embed_request.extra_params)
        data = _post_json(provider=self.provider_name, config=config, path="/embeddings", payload=payload)
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderRequestError(
                "兼容 OpenAI 的 Embedding 响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        embeddings = [item.get("embedding") for item in items]
        return EmbedResponse(
            provider=self.provider_name,
            model=config.model,
            embeddings=embeddings,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            raw_response=data,
        )


class AnthropicAdapter(BaseProviderAdapter):
    provider_name = "anthropic"
    capabilities = ModelCapability(
        supports_chat=True,
        supports_stream=False,
        supports_embeddings=False,
        supports_tools=False,
        supports_json_mode=False,
    )

    def generate(self, config: ProviderConfig, chat_request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": msg.role, "content": [{"type": "text", "text": msg.content}]}
                for msg in chat_request.messages
                if msg.role != "system"
            ],
            "temperature": chat_request.temperature,
            "max_tokens": chat_request.max_tokens or 1024,
        }
        if chat_request.system_prompt:
            payload["system"] = chat_request.system_prompt
        if config.extra_params:
            payload.update(config.extra_params)
        if chat_request.extra_params:
            payload.update(chat_request.extra_params)
        data = _post_json(provider=self.provider_name, config=config, path="/messages", payload=payload)
        content_items = data.get("content")
        if not isinstance(content_items, list):
            raise ProviderRequestError(
                "Anthropic 响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        text = "\n".join(
            item.get("text", "").strip()
            for item in content_items
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
        ).strip()
        if not text:
            raise ProviderRequestError(
                "Anthropic 未返回有效文本内容",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        return ChatResponse(
            provider=self.provider_name,
            model=config.model,
            text=text,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            raw_response=data,
        )


class GeminiAdapter(BaseProviderAdapter):
    provider_name = "gemini"
    capabilities = ModelCapability(
        supports_chat=True,
        supports_stream=False,
        supports_embeddings=True,
        supports_tools=False,
        supports_json_mode=False,
    )

    def generate(self, config: ProviderConfig, chat_request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if msg.role == "assistant" else "user",
                    "parts": [{"text": msg.content}],
                }
                for msg in chat_request.messages
                if msg.role != "system"
            ],
            "generationConfig": {"temperature": chat_request.temperature},
        }
        if chat_request.max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = chat_request.max_tokens
        if chat_request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": chat_request.system_prompt}]}
        if config.extra_params:
            payload.update(config.extra_params)
        if chat_request.extra_params:
            payload.update(chat_request.extra_params)
        data = _post_json(
            provider=self.provider_name,
            config=config,
            path=f"/{_model_path(config.model)}:generateContent",
            payload=payload,
        )
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderRequestError(
                "Gemini 响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "\n".join(
            part.get("text", "").strip()
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ).strip()
        if not text:
            raise ProviderRequestError(
                "Gemini 未返回有效文本内容",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        return ChatResponse(
            provider=self.provider_name,
            model=config.model,
            text=text,
            usage=data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else None,
            raw_response=data,
        )

    def embed_texts(self, config: ProviderConfig, embed_request: EmbedRequest) -> EmbedResponse:
        payload: dict[str, Any] = {
            "requests": [
                {
                    "model": _model_path(config.model),
                    "content": {"parts": [{"text": text}]},
                }
                for text in embed_request.inputs
            ]
        }
        if config.extra_params:
            payload.update(config.extra_params)
        if embed_request.extra_params:
            payload.update(embed_request.extra_params)
        data = _post_json(
            provider=self.provider_name,
            config=config,
            path=f"/{_model_path(config.model)}:batchEmbedContents",
            payload=payload,
        )
        items = data.get("embeddings")
        if not isinstance(items, list):
            raise ProviderRequestError(
                "Gemini Embedding 响应格式不正确",
                provider=self.provider_name,
                code="BAD_RESPONSE",
                retryable=False,
                raw_response=json.dumps(data, ensure_ascii=False),
            )
        embeddings = [item.get("values") for item in items]
        return EmbedResponse(
            provider=self.provider_name,
            model=config.model,
            embeddings=embeddings,
            usage=data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else None,
            raw_response=data,
        )


def get_provider_adapter(provider: str | None) -> BaseProviderAdapter:
    normalized = normalize_provider_name(provider)
    if normalized == "openai":
        return OpenAIAdapter()
    if normalized == "anthropic":
        return AnthropicAdapter()
    if normalized == "gemini":
        return GeminiAdapter()
    return OpenAICompatibleAdapter()
