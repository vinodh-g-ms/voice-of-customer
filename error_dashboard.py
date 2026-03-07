#!/usr/bin/env python3
"""Generate an error dashboard when the VoC pipeline fails.

Called by the GitHub Actions workflow when main.py exits with non-zero status.
Produces a self-contained HTML page with error details and fix instructions.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output_v3"


def detect_errors() -> list[dict]:
    """Detect which keys/configs are broken based on environment and exit code."""
    errors = []

    # Check Anthropic API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        errors.append({
            "title": "Anthropic API Key Missing",
            "icon": "\u26d4",
            "description": "The ANTHROPIC_API_KEY secret is not set. Claude API analysis cannot run without it.",
            "fix": [
                "Go to <a href='https://console.anthropic.com/settings/keys'>console.anthropic.com/settings/keys</a>",
                "Create or copy your API key",
                "Go to your GitHub repo \u2192 Settings \u2192 Secrets and variables \u2192 Actions",
                "Update the <code>ANTHROPIC_API_KEY</code> secret with the new key",
                "Re-run the pipeline",
            ],
        })
    elif api_key.startswith("sk-ant-"):
        # Key exists but might be expired/invalid (pipeline still failed)
        errors.append({
            "title": "Anthropic API Key May Be Invalid or Expired",
            "icon": "\u26a0\ufe0f",
            "description": "The ANTHROPIC_API_KEY is set but the pipeline failed. The key may be expired, revoked, or have insufficient credits.",
            "fix": [
                "Go to <a href='https://console.anthropic.com/settings/keys'>console.anthropic.com/settings/keys</a>",
                "Verify your key is active and has available credits",
                "If needed, create a new key",
                "Go to your GitHub repo \u2192 Settings \u2192 Secrets and variables \u2192 Actions",
                "Update the <code>ANTHROPIC_API_KEY</code> secret",
                "Re-run the pipeline",
            ],
        })

    # Check ADO PAT
    ado_pat = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    if not ado_pat:
        errors.append({
            "title": "ADO Personal Access Token Missing",
            "icon": "\u26d4",
            "description": "The ADO_PAT secret is not set. ADO bug correlation cannot run without it.",
            "fix": [
                "Go to <a href='https://office.visualstudio.com/_usersSettings/tokens'>office.visualstudio.com \u2192 Personal Access Tokens</a>",
                "Click <strong>New Token</strong>",
                "Name: <code>VoC-Pipeline</code>, Scope: <strong>Work Items \u2192 Read</strong>",
                "Copy the generated token",
                "Go to your GitHub repo \u2192 Settings \u2192 Secrets and variables \u2192 Actions",
                "Update the <code>ADO_PAT</code> secret with the new token",
                "Re-run the pipeline",
            ],
        })
    else:
        errors.append({
            "title": "ADO Personal Access Token May Be Expired",
            "icon": "\u26a0\ufe0f",
            "description": "The ADO_PAT is set but may have expired (PATs in this org expire every 7 days). Regenerate it.",
            "fix": [
                "Go to <a href='https://office.visualstudio.com/_usersSettings/tokens'>office.visualstudio.com \u2192 Personal Access Tokens</a>",
                "Check if your <code>VoC-Pipeline</code> token has expired",
                "If expired, click <strong>Regenerate</strong> or create a new one (Scope: Work Items \u2192 Read)",
                "Go to your GitHub repo \u2192 Settings \u2192 Secrets and variables \u2192 Actions",
                "Update the <code>ADO_PAT</code> secret with the new token",
                "Re-run the pipeline",
            ],
        })

    if not errors:
        errors.append({
            "title": "Pipeline Failed — Unknown Error",
            "icon": "\u274c",
            "description": "The pipeline failed for an unexpected reason. Check the GitHub Actions logs for details.",
            "fix": [
                "Go to your GitHub repo \u2192 Actions tab",
                "Click the latest failed run",
                "Check the <strong>Run VoC Pipeline</strong> step logs for error details",
                "Fix the issue and re-run the pipeline",
            ],
        })

    return errors


def generate_error_html(errors: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    error_cards = ""
    for err in errors:
        steps_html = "".join(f"<li>{s}</li>" for s in err["fix"])
        error_cards += f"""
        <div class="error-card">
            <div class="error-header">
                <span class="error-icon">{err['icon']}</span>
                <h2>{err['title']}</h2>
            </div>
            <p class="error-desc">{err['description']}</p>
            <div class="fix-steps">
                <h3>How to fix:</h3>
                <ol>{steps_html}</ol>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Customer Pulse — Pipeline Error</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
        background: #f5f5f7; color: #1d1d1f;
        min-height: 100vh; padding: 40px 20px;
    }}
    .container {{ max-width: 720px; margin: 0 auto; }}
    .header {{
        text-align: center; margin-bottom: 40px;
    }}
    .header h1 {{
        font-size: 32px; font-weight: 700; margin-bottom: 8px;
        background: linear-gradient(135deg, #FF3B30, #FF9500);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }}
    .header .timestamp {{ color: #86868b; font-size: 14px; }}
    .error-card {{
        background: #fff; border-radius: 16px; padding: 28px;
        margin-bottom: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        border-left: 4px solid #FF3B30;
    }}
    .error-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
    .error-icon {{ font-size: 28px; }}
    .error-header h2 {{ font-size: 20px; font-weight: 600; }}
    .error-desc {{ color: #424245; line-height: 1.5; margin-bottom: 16px; }}
    .fix-steps {{
        background: #f5f5f7; border-radius: 12px; padding: 20px;
    }}
    .fix-steps h3 {{ font-size: 15px; font-weight: 600; margin-bottom: 12px; color: #1d1d1f; }}
    .fix-steps ol {{ padding-left: 20px; }}
    .fix-steps li {{
        color: #424245; line-height: 1.6; margin-bottom: 8px; font-size: 14px;
    }}
    .fix-steps code {{
        background: #e8e8ed; padding: 2px 6px; border-radius: 4px;
        font-family: 'SF Mono', 'Menlo', monospace; font-size: 13px;
    }}
    .fix-steps a {{ color: #0066CC; text-decoration: none; }}
    .fix-steps a:hover {{ text-decoration: underline; }}
    .footer {{
        text-align: center; margin-top: 32px; color: #86868b; font-size: 13px;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Pipeline Error</h1>
        <p class="timestamp">Customer Pulse failed on {now}</p>
    </div>
    {error_cards}
    <div class="footer">
        <p>After fixing the issue, go to GitHub Actions and click <strong>"Run workflow"</strong> to retry.</p>
    </div>
</div>
</body>
</html>"""


def main():
    exit_code = sys.argv[1] if len(sys.argv) > 1 else "1"
    print(f"\n  Pipeline failed (exit code {exit_code}). Generating error dashboard...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    errors = detect_errors()
    html = generate_error_html(errors)

    out_path = OUTPUT_DIR / "pulse_dashboard_v3.html"
    out_path.write_text(html)
    print(f"  Error dashboard: {out_path}")

    for err in errors:
        print(f"  {err['icon']} {err['title']}")


if __name__ == "__main__":
    main()
