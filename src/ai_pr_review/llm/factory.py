import re
from typing import Dict, Type

from .base_llm import AIAnalysisConfig, BaseLLMProvider
from .gemini import GeminiProvider


class LLMProviderFactory:
    """Factory for creating LLM providers."""

    _providers: Dict[str, Type[BaseLLMProvider]] = {
        "gemini": GeminiProvider,
        # Future providers can be added here:
        # "openai": OpenAIProvider,
        # "claude": ClaudeProvider,
        # "cohere": CohereProvider,
    }

    _model_patterns = {
        "gemini": re.compile(r"^gemini-.*", re.IGNORECASE),
        "openai": re.compile(r"^(gpt-|openai-|text-davinci|text-curie)", re.IGNORECASE),
        "claude": re.compile(r"^claude-.*", re.IGNORECASE),
        "cohere": re.compile(r"^(command|cohere)-.*", re.IGNORECASE),
    }

    @classmethod
    def create_provider_from_model(cls, config: AIAnalysisConfig) -> BaseLLMProvider:
        """Create an LLM provider instance from model name."""
        provider_name = cls.extract_provider_name(config.model)
        return cls.create_provider(provider_name, config)

    @classmethod
    def create_provider(
        cls, provider_name: str, config: AIAnalysisConfig
    ) -> BaseLLMProvider:
        """Create an LLM provider instance."""
        provider_class = cls._providers.get(provider_name.lower())
        if not provider_class:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unknown provider '{provider_name}'. Available providers: {available}"
            )

        return provider_class(config)

    @classmethod
    def extract_provider_name(cls, model_name: str) -> str:
        """Extract provider name from model name using pattern matching."""
        for provider, pattern in cls._model_patterns.items():
            if pattern.match(model_name):
                return provider

        # Fallback to simple split method
        return model_name.split("-")[0].lower()
