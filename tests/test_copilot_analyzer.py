"""Tests for GitHub Copilot analyzer (Responses API + Chat Completions)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses as resp_lib

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestCopilotAnalyzer:
    def test_missing_token_exits(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            with pytest.raises(SystemExit):
                from analyzers.copilot_analyzer import CopilotAnalyzer
                CopilotAnalyzer()

    def test_gpt5_uses_responses_api(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-5.4"):
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            assert analyzer._use_responses_api is True

    def test_gpt4_uses_chat_completions(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-4o"), \
             patch("analyzers.copilot_analyzer.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            assert analyzer._use_responses_api is False

    @resp_lib.activate
    def test_responses_api_success(self):
        fixture = json.loads((FIXTURES_DIR / "copilot_responses.json").read_text())
        resp_lib.add(
            resp_lib.POST,
            "https://api.githubcopilot.com/responses",
            json=fixture,
            status=200,
        )
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-5.4"):
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            result = analyzer._call_responses_api("system", "user")
        assert "overall_sentiment" in result

    @resp_lib.activate
    def test_responses_api_no_text_raises(self):
        resp_lib.add(
            resp_lib.POST,
            "https://api.githubcopilot.com/responses",
            json={"output": [{"type": "other", "content": []}]},
            status=200,
        )
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-5.4"):
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            with pytest.raises(RuntimeError, match="No text output"):
                analyzer._call_responses_api("system", "user")

    def test_chat_completions_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-4o"), \
             patch("analyzers.copilot_analyzer.OpenAI", return_value=mock_client):
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            result = analyzer._call_chat_completions("system", "user")
        assert result == '{"result": "ok"}'

    def test_chat_completions_token_param_gpt5(self):
        """GPT-5 models use max_completion_tokens instead of max_tokens."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("config.COPILOT_MODEL", "gpt-4o"), \
             patch("analyzers.copilot_analyzer.OpenAI", return_value=mock_client):
            from analyzers.copilot_analyzer import CopilotAnalyzer
            analyzer = CopilotAnalyzer()
            analyzer._call_chat_completions("system", "user")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "max_tokens" in call_kwargs
