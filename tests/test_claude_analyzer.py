"""Tests for Claude (Anthropic) analyzer."""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest


class TestClaudeAnalyzer:
    def test_missing_package_exits(self):
        with patch("analyzers.claude_analyzer.anthropic", None):
            with pytest.raises(SystemExit):
                from analyzers.claude_analyzer import ClaudeAnalyzer
                ClaudeAnalyzer()

    def test_missing_api_key_exits(self):
        with patch("analyzers.claude_analyzer.anthropic") as mock_anthropic, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            mock_anthropic.Anthropic = MagicMock()
            with pytest.raises(SystemExit):
                from analyzers.claude_analyzer import ClaudeAnalyzer
                ClaudeAnalyzer()

    def test_call_llm_success(self):
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text='{"result": "ok"}')]
        mock_client.messages.create.return_value = mock_message

        with patch("analyzers.claude_analyzer.anthropic") as mock_anthropic, \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            mock_anthropic.Anthropic.return_value = mock_client
            from analyzers.claude_analyzer import ClaudeAnalyzer
            analyzer = ClaudeAnalyzer()
            result = analyzer._call_llm("system prompt", "user prompt")

        assert result == '{"result": "ok"}'
        mock_client.messages.create.assert_called_once()

    def test_api_error_propagates(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API Error")

        with patch("analyzers.claude_analyzer.anthropic") as mock_anthropic, \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            mock_anthropic.Anthropic.return_value = mock_client
            from analyzers.claude_analyzer import ClaudeAnalyzer
            analyzer = ClaudeAnalyzer()
            with pytest.raises(Exception, match="API Error"):
                analyzer._call_llm("system", "user")
