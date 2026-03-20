"""Pluggable analyzer factory.

Set the ANALYSIS_PROVIDER env var to choose the LLM backend:
  - "claude"  → Anthropic Claude API (requires ANTHROPIC_API_KEY)
  - "copilot" → GitHub Models API (requires GITHUB_TOKEN)
"""

from __future__ import annotations

import os
import sys

from analyzers.base import BaseAnalyzer

_PROVIDERS = {
    "claude": "analyzers.claude_analyzer.ClaudeAnalyzer",
    "copilot": "analyzers.copilot_analyzer.CopilotAnalyzer",
}


def get_analyzer() -> BaseAnalyzer:
    """Return an analyzer instance based on ANALYSIS_PROVIDER env var."""
    provider = os.environ.get("ANALYSIS_PROVIDER", "claude").lower()
    if provider not in _PROVIDERS:
        print(f"ERROR: Unknown ANALYSIS_PROVIDER '{provider}'. Choose from: {', '.join(_PROVIDERS)}")
        sys.exit(1)

    module_path, class_name = _PROVIDERS[provider].rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    print(f"  Using analysis provider: {provider}")
    return cls()
