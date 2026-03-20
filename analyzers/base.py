"""Base analyzer interface for pluggable LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAnalyzer(ABC):
    """Abstract base class for LLM-based review analyzers.

    Subclasses only need to implement `_call_llm` — the actual API call.
    Prompt construction and response parsing are handled here.
    """

    @abstractmethod
    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Send prompts to the LLM and return the raw text response."""
        ...

    def analyze(self, review_text: str, platform: str, period_label: str,
                topic: str, review_count: int) -> str:
        """Build prompts and call the LLM. Returns raw text response."""
        system_prompt = self._build_system_prompt(platform, period_label)
        user_prompt = self._build_user_prompt(
            review_text, platform, period_label, topic, review_count,
        )
        return self._call_llm(system_prompt, user_prompt)

    @staticmethod
    def _build_system_prompt(platform: str = "", period_label: str = "") -> str:
        platform_name = {
            "ios": "iOS (iPhone/iPad)",
            "mac": "macOS (Mac desktop app)",
            "android": "Android",
        }.get(platform, "all platforms")

        period_desc = ""
        if period_label == "15d":
            period_desc = " Focus on recent and emerging issues."
        elif period_label == "90d":
            period_desc = " Provide a broad landscape view of persistent themes."

        return f"""You are an expert product analyst for Microsoft Outlook on {platform_name}.
You analyze customer feedback to identify actionable themes.{period_desc}

Analyze the provided customer reviews and return a JSON object with this EXACT schema:

{{
  "overall_sentiment": <float from -1.0 (very negative) to 1.0 (very positive)>,
  "overall_summary": "<2-3 sentence summary of the feedback landscape>",
  "clusters": [
    {{
      "topic": "<short topic name, e.g. 'Calendar sync failures'>",
      "severity": "<critical|high|medium|low>",
      "count": <number of reviews in this cluster>,
      "sentiment_score": <float -1.0 to 1.0>,
      "summary": "<1-2 sentence description of the issue>",
      "quotes": ["<exact quote 1>", "<exact quote 2>"],
      "source_breakdown": {{"appstore": 5, "reddit": 3, "msqa": 1}},
      "version_breakdown": {{"4.2411.0": 3, "4.2412.1": 7}}
    }}
  ]
}}

Rules:
- Return ONLY valid JSON, no markdown fences or extra text
- Create 5-15 clusters, sorted by severity then count (descending)
- Each cluster should have 2-4 representative quotes (exact text from reviews)
- Severity: critical = app-breaking/data loss, high = major workflow blocker,
  medium = annoying but workaround exists, low = cosmetic/minor
- Merge similar topics
- source_breakdown counts should sum to the cluster's count
- version_breakdown: count reviews per app version when version info is available
- If a topic filter was specified, focus clusters on that topic area"""

    @staticmethod
    def _build_user_prompt(review_text: str, platform: str, period_label: str,
                           topic: str, review_count: int) -> str:
        plat = f" ({platform})" if platform else ""
        per = f" [{period_label}]" if period_label else ""
        prompt = f"Analyze these {review_count} customer reviews{plat}{per}"
        if topic:
            prompt += f" (focus on: {topic})"
        prompt += f":\n\n{review_text}"
        return prompt
