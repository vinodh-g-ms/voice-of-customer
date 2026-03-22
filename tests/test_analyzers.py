"""Tests for analyzer factory and base prompts."""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from analyzers.base import BaseAnalyzer


class TestAnalyzerFactory:
    def test_get_analyzer_claude(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "claude", "ANTHROPIC_API_KEY": "test"}):
            with patch("analyzers.claude_analyzer.anthropic") as mock_anthropic:
                mock_anthropic.Anthropic.return_value = MagicMock()
                from analyzers import get_analyzer
                analyzer = get_analyzer()
                assert analyzer.__class__.__name__ == "ClaudeAnalyzer"

    def test_get_analyzer_copilot(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot", "GITHUB_TOKEN": "test"}):
            with patch("analyzers.copilot_analyzer.OpenAI") as mock_openai:
                mock_openai.return_value = MagicMock()
                from analyzers import get_analyzer
                analyzer = get_analyzer()
                assert analyzer.__class__.__name__ == "CopilotAnalyzer"

    def test_get_analyzer_unknown_exits(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "unknown"}):
            with pytest.raises(SystemExit):
                from analyzers import get_analyzer
                get_analyzer()


class TestBasePrompts:
    def test_system_prompt_ios(self):
        prompt = BaseAnalyzer._build_system_prompt("ios", "15d")
        assert "iOS" in prompt
        assert "emerging" in prompt.lower()

    def test_system_prompt_mac(self):
        prompt = BaseAnalyzer._build_system_prompt("mac", "90d")
        assert "macOS" in prompt or "Mac" in prompt
        assert "landscape" in prompt.lower()

    def test_system_prompt_android(self):
        prompt = BaseAnalyzer._build_system_prompt("android", "15d")
        assert "Android" in prompt

    def test_user_prompt_with_topic(self):
        prompt = BaseAnalyzer._build_user_prompt("review text", "ios", "15d", "calendar", 50)
        assert "calendar" in prompt
        assert "50" in prompt
        assert "review text" in prompt

    def test_user_prompt_without_topic(self):
        prompt = BaseAnalyzer._build_user_prompt("review text", "ios", "15d", "", 50)
        assert "focus on" not in prompt.lower()
        assert "50" in prompt

    def test_system_prompt_unknown_platform(self):
        prompt = BaseAnalyzer._build_system_prompt("", "15d")
        assert "all platforms" in prompt

    def test_system_prompt_no_period(self):
        prompt = BaseAnalyzer._build_system_prompt("ios", "")
        # No period-specific guidance should be present
        assert "Focus on recent" not in prompt
        assert "landscape view" not in prompt
