"""Configuration constants for Customer Pulse v3."""

import os

# ── App Store (iOS + Mac) ─────────────────────────────────────────
APPSTORE_PLATFORMS = {
    "ios": {"app_id": "951937596", "name": "Microsoft Outlook for iOS"},
    "mac": {"app_id": "985367838", "name": "Microsoft Outlook for macOS"},
}
APPSTORE_COUNTRIES = ["us", "gb", "au", "ca", "in"]
APPSTORE_PAGES = 10
APPSTORE_DELAY = 1.1

# ── Google Play Store (Android) ───────────────────────────────────
PLAYSTORE_APP_ID = "com.microsoft.office.outlook"
PLAYSTORE_REVIEWS_PER_COUNTRY = 200
PLAYSTORE_COUNTRIES = ["us", "gb", "au", "ca", "in"]

# ── Time Windows ──────────────────────────────────────────────────
TIME_WINDOWS = [
    {"name": "90d", "days": 90},
    {"name": "15d", "days": 15},
]

# ── Reddit (platform-aware queries) ───────────────────────────────
REDDIT_SUBREDDITS = ["Outlook", "microsoft365", "Office365"]
REDDIT_PLATFORM_QUERIES = {
    "ios": "outlook ios OR outlook iphone OR outlook mobile",
    "mac": "outlook mac OR outlook macos OR outlook desktop mac",
    "android": "outlook android OR outlook mobile android",
}
REDDIT_USER_AGENT = "CustomerPulse/3.0 (Outlook feedback aggregator)"
REDDIT_POSTS_PER_QUERY = 100
REDDIT_DELAY = 6.0

# ── MS Q&A (platform-aware) ───────────────────────────────────────
MSQA_PLATFORM_URLS = {
    "ios": "https://learn.microsoft.com/en-us/answers/tags/456/outlook-mobile",
    "mac": "https://learn.microsoft.com/en-us/answers/tags/456/outlook-mobile",
    "android": "https://learn.microsoft.com/en-us/answers/tags/456/outlook-mobile",
}
MSQA_MAX_PAGES = 5

# ── Analysis Provider ──────────────────────────────────────────────
# Set ANALYSIS_PROVIDER env var: "claude" (default) or "copilot"

# Claude (Anthropic)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 16384
CLAUDE_MAX_REVIEWS = 500

# GitHub Copilot (Models API)
COPILOT_BASE_URL = "https://models.github.ai/inference"
COPILOT_MODEL = os.environ.get("COPILOT_MODEL") or "openai/gpt-4.1"
COPILOT_MAX_TOKENS = 16384
COPILOT_MAX_REVIEWS = int(os.environ.get("COPILOT_MAX_REVIEWS") or 100)

# ── Azure DevOps ───────────────────────────────────────────────────
ADO_ORG_URL = "https://office.visualstudio.com"
ADO_PROJECT = "Outlook Mobile"
ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"
ADO_SEARCH_URL = "https://almsearch.dev.azure.com"
ADO_MAX_RESULTS = 15
# Area paths per platform for filtering ADO results
ADO_AREA_PATHS = {
    "ios": ["Outlook Mobile\\iOS"],
    "mac": ["Outlook Mobile\\OS X"],
    "android": ["Outlook Mobile\\Android"],
}

# ── Cache ──────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 12

# ── Defaults ───────────────────────────────────────────────────────
DEFAULT_DAYS = 90
DEFAULT_PLATFORMS = ["ios", "mac", "android"]
DEFAULT_SOURCES = ["appstore", "playstore", "reddit", "msqa"]
