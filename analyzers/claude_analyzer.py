"""Claude (Anthropic) analyzer implementation."""

from __future__ import annotations

import os
import sys

import config
from analyzers.base import BaseAnalyzer

try:
    import anthropic
except ImportError:
    anthropic = None


class ClaudeAnalyzer(BaseAnalyzer):
    """Analyzer backed by the Anthropic Claude API."""

    def __init__(self):
        if anthropic is None:
            print("ERROR: anthropic package not installed. Run: pip install anthropic")
            sys.exit(1)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
            sys.exit(1)
        self._client = anthropic.Anthropic(api_key=api_key)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        message = self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CLAUDE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
