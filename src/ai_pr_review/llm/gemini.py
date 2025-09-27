import asyncio
import json
import time
from typing import Dict, List

from google import genai

from .base_llm import (
    AIAnalysisConfig,
    BaseLLMProvider,
    CodeReviewComment,
)
from .prompt_builder import PromptBuilder


class GeminiProvider(BaseLLMProvider):
    """Gemini AI provider for code review analysis."""

    def __init__(self, config: AIAnalysisConfig):
        super().__init__(config)
        self.prompt_builder = PromptBuilder()

        self._last_request_time = 0
        self._min_request_interval = config.min_request_interval
        self._retry_delay = config.retry_delay
        self._max_retries = config.max_retries

    @property
    def provider_name(self) -> str:
        return "Gemini"

    async def initialize(self) -> None:
        """Initialize the Gemini client."""
        self._client = genai.Client()

    async def generate_response(self, prompt: str) -> str:
        """Generate response from Gemini API."""
        if not self._client:
            await self.initialize()

        return await self._rate_limited_request(prompt)

    def parse_response(self, response: str) -> List[CodeReviewComment]:
        """Parse Gemini response into structured comments."""
        # Clean response text
        cleaned_text = self._clean_response_text(response)

        try:
            comments_data = json.loads(cleaned_text)
            if not isinstance(comments_data, list):
                raise ValueError("Gemini response is not a list")

            comments = []
            for comment_data in comments_data:
                comment = CodeReviewComment(
                    hunk_index=comment_data.get("hunk_index", 0),
                    old_file_path=comment_data.get("old_file_path", ""),
                    new_file_path=comment_data.get("new_file_path", ""),
                    new_line=comment_data.get("new_line", 0),
                    severity=comment_data.get("severity", "info"),
                    category=comment_data.get("category", "general"),
                    suggestion=comment_data.get("suggestion", ""),
                    rationale=comment_data.get("rationale", ""),
                    original_ai_line=comment_data.get("new_line"),
                    end_line=comment_data.get("end_line"),
                )
                comments.append(comment)

            return comments
        except Exception as e:
            print(f"Failed to parse Gemini comments: {e}\nRaw text: {response}")
            return []

    async def analyze_hunk(
        self, hunk: Dict, pr_title: str, pr_description: str, platform: str = "generic"
    ) -> List[CodeReviewComment]:
        """Analyze a single hunk using Gemini."""
        prompt = self.prompt_builder.create_review_prompt(
            hunk, pr_title, pr_description, platform
        )

        response = await self.generate_response(prompt)
        return self.parse_response(response)

    async def _rate_limited_request(self, prompt: str, max_retries: int = 3) -> str:
        """Make a rate-limited request with exponential backoff."""
        for attempt in range(max_retries):
            try:
                # Enforce minimum interval between requests
                current_time = time.time()
                time_since_last = current_time - self._last_request_time
                if time_since_last < self._min_request_interval:
                    sleep_time = self._min_request_interval - time_since_last
                    await asyncio.sleep(sleep_time)

                self._last_request_time = time.time()

                response = self._client.models.generate_content(
                    model=self.config.model, contents=prompt
                )
                resp_json = response.to_json_dict()

                candidates = resp_json.get("candidates")
                if not candidates or not candidates[0].get("content"):
                    raise RuntimeError(
                        f"Gemini API returned no candidates or content: {resp_json}"
                    )

                content = candidates[0]["content"]["parts"][0].get("text", "")
                if not content.strip():
                    raise RuntimeError(
                        f"Gemini API returned empty content: {resp_json}"
                    )

                return content

            except Exception as e:
                # Prefer structured error handling if available
                error_code = getattr(e, "code", None)
                # Fallback to string parsing if structured info is not available
                error_str = str(e)
                is_rate_limited = (
                    error_code == 429
                    or error_code == "RESOURCE_EXHAUSTED"
                    or "429" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str
                )
                if is_rate_limited:
                    if attempt < max_retries - 1:
                        retry_delay = self._retry_delay
                        # Try to extract retry delay from structured error if available
                        retry_delay_attr = getattr(e, "retry_delay", None)
                        if retry_delay_attr is not None:
                            retry_delay = retry_delay_attr
                        print(
                            f"Rate limit hit, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        raise RuntimeError(
                            f"Rate limit exceeded after {max_retries} attempts: {e}"
                        )
                else:
                    raise RuntimeError(f"Failed to get Gemini response: {e}")

        raise RuntimeError(f"Failed to get response after {max_retries} attempts")

    def _clean_response_text(self, text: str) -> str:
        """Clean Gemini response text by removing markdown code blocks."""
        text = text.strip()

        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        return text.strip()
