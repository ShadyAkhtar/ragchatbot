"""
Adapters for constructing an Anthropic-compatible client.

The `anthropic` SDK exposes the same `messages.create()` interface and response
shape regardless of which backend serves the request - direct Anthropic API,
AWS Bedrock, or (in future) Google Vertex AI. `AIGenerator` is written against
that shared interface, so switching backends is just a matter of swapping which
`LLMProvider` builds the client and which model id gets passed to it.

Only the client/model resolution is adapted here - not tool-calling or response
parsing, since those already work identically across every Anthropic entry point.
A genuinely different-shaped vendor (e.g. OpenAI) would need more than a new
provider class here; this seam is where that work would start, not where it ends.
"""

from abc import ABC, abstractmethod
import anthropic


class LLMProvider(ABC):
    """Builds the Anthropic-compatible client and resolves the model id to call it with."""

    @abstractmethod
    def build_client(self) -> anthropic.Anthropic: ...

    @abstractmethod
    def resolve_model(self) -> str: ...


class AnthropicAPIProvider(LLMProvider):
    """Talks to Claude directly via an Anthropic API key (console.anthropic.com)."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic"
            )
        self.api_key = api_key
        self.model = model

    def build_client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=self.api_key)

    def resolve_model(self) -> str:
        return self.model


class BedrockProvider(LLMProvider):
    """Talks to Claude via AWS Bedrock, using the standard AWS credential chain."""

    def __init__(self, aws_region: str, model: str):
        self.aws_region = aws_region
        self.model = model

    def build_client(self) -> anthropic.Anthropic:
        return anthropic.AnthropicBedrock(aws_region=self.aws_region)

    def resolve_model(self) -> str:
        return self.model


def create_provider(config) -> LLMProvider:
    """Pick and construct the configured LLMProvider from app config."""
    provider_name = config.LLM_PROVIDER.lower()

    if provider_name == "bedrock":
        return BedrockProvider(config.AWS_REGION, config.BEDROCK_MODEL)

    if provider_name == "anthropic":
        return AnthropicAPIProvider(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL)

    raise ValueError(
        f"Unknown LLM_PROVIDER '{config.LLM_PROVIDER}' - expected 'bedrock' or 'anthropic'"
    )
