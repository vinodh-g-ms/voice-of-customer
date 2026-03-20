"""GitHub Copilot (Models API) analyzer implementation."""

from __future__ import annotations

import os
import sys

import config
from analyzers.base import BaseAnalyzer

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class CopilotAnalyzer(BaseAnalyzer):
    """Analyzer backed by the GitHub Models API (OpenAI-compatible)."""

    def __init__(self):
        if OpenAI is None:
            print("ERROR: openai package not installed. Run: pip install openai")
            sys.exit(1)
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
        if not token:
            print("ERROR: GITHUB_TOKEN or GH_MODELS_TOKEN environment variable not set.")
            print("  Generate one at: https://github.com/settings/tokens")
            print("  Or run: export GITHUB_TOKEN=$(gh auth token)")
            sys.exit(1)
        self._client = OpenAI(
            base_url=config.COPILOT_BASE_URL,
            api_key=token,
        )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        # Newer models (gpt-5, o-series) require max_completion_tokens
        model = config.COPILOT_MODEL
        needs_new_param = any(k in model for k in ["gpt-5", "/o1", "/o3", "/o4"])
        token_kwarg = (
            {"max_completion_tokens": config.COPILOT_MAX_TOKENS}
            if needs_new_param
            else {"max_tokens": config.COPILOT_MAX_TOKENS}
        )
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **token_kwarg,
        )
        return response.choices[0].message.content
