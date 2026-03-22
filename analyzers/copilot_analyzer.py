"""GitHub Copilot API analyzer implementation.

Supports two API formats:
  - /responses endpoint (GPT-5.x models) — uses the Responses API
  - /chat/completions endpoint (GPT-4.x and older) — uses the Chat Completions API
"""

from __future__ import annotations

import os
import sys

import requests as http_requests

import config
from analyzers.base import BaseAnalyzer

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class CopilotAnalyzer(BaseAnalyzer):
    """Analyzer backed by the GitHub Copilot API."""

    def __init__(self):
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
        if not token:
            print("ERROR: GITHUB_TOKEN or GH_MODELS_TOKEN environment variable not set.")
            print("  Generate one at: https://github.com/settings/tokens")
            print("  Or run: export GITHUB_TOKEN=$(gh auth token)")
            sys.exit(1)
        self._token = token
        self._use_responses_api = "gpt-5" in config.COPILOT_MODEL

        if not self._use_responses_api:
            if OpenAI is None:
                print("ERROR: openai package not installed. Run: pip install openai")
                sys.exit(1)
            self._client = OpenAI(
                base_url=config.COPILOT_BASE_URL,
                api_key=token,
            )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if self._use_responses_api:
            return self._call_responses_api(system_prompt, user_prompt)
        return self._call_chat_completions(system_prompt, user_prompt)

    def _call_responses_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call the /responses endpoint for GPT-5.x models."""
        url = f"{config.COPILOT_BASE_URL}/responses"
        resp = http_requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.COPILOT_MODEL,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_output_tokens": config.COPILOT_MAX_TOKENS,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        # Extract text from the responses API output format
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text", "")
        raise RuntimeError(f"No text output in response: {data}")

    def _call_chat_completions(self, system_prompt: str, user_prompt: str) -> str:
        """Call the /chat/completions endpoint for older models."""
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
