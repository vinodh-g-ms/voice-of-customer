#!/usr/bin/env python3
"""Generate an error dashboard when the VoC pipeline fails.

Called by the GitHub Actions workflow when main.py exits with non-zero status.
Produces a self-contained HTML page with error details, health checks,
and step-by-step fix instructions designed for non-developers.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output_v3"

GITHUB_REPO = "vinodh-g-ms/voice-of-customer"


def detect_errors() -> list[dict]:
    """Detect which keys/configs are broken based on environment and exit code."""
    errors = []

    # Check Anthropic API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        errors.append({
            "title": "Anthropic API Key Missing",
            "icon": "\u26d4",
            "severity": "blocking",
            "time_to_fix": "~5 minutes",
            "description": "The Claude AI API key is not set. Without it, the pipeline cannot analyze customer reviews.",
            "fix": [
                'Go to <a href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com/settings/keys</a> and sign in',
                "Click <strong>Create Key</strong> or copy your existing key",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/settings/secrets/actions" target="_blank">GitHub Repo &rarr; Settings &rarr; Secrets</a>',
                'Click <strong>New repository secret</strong> (or update existing)',
                'Name: <code>ANTHROPIC_API_KEY</code>, paste your key as the value',
                'Click <strong>Add secret</strong>',
                f'Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">Actions tab</a> and click <strong>Run workflow</strong> to retry',
            ],
        })
    elif api_key.startswith("sk-ant-"):
        errors.append({
            "title": "Anthropic API Key May Be Invalid",
            "icon": "\u26a0\ufe0f",
            "severity": "likely",
            "time_to_fix": "~5 minutes",
            "description": "The API key is set but the pipeline still failed. The key may be expired, revoked, or out of credits.",
            "fix": [
                'Go to <a href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com/settings/keys</a>',
                "Check your key is <strong>Active</strong> (not revoked)",
                'Check your <a href="https://console.anthropic.com/settings/billing" target="_blank">billing page</a> for available credits',
                "If needed, create a new key",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/settings/secrets/actions" target="_blank">GitHub Repo &rarr; Settings &rarr; Secrets</a>',
                "Update the <code>ANTHROPIC_API_KEY</code> secret with the new key",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">Actions tab</a> and click <strong>Run workflow</strong>',
            ],
        })

    # Check ADO PAT
    ado_pat = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    if not ado_pat:
        errors.append({
            "title": "ADO Access Token Missing",
            "icon": "\u26a0\ufe0f",
            "severity": "optional",
            "time_to_fix": "~3 minutes",
            "description": "The Azure DevOps token is not set. Bug correlation will be skipped, but everything else still works.",
            "fix": [
                'Go to <a href="https://office.visualstudio.com/_usersSettings/tokens" target="_blank">office.visualstudio.com &rarr; Personal Access Tokens</a>',
                'Click <strong>+ New Token</strong>',
                'Name: <code>VoC-Pipeline</code>, Expiration: <strong>7 days</strong> (max allowed)',
                'Scope: check <strong>Work Items &rarr; Read</strong>',
                "Click <strong>Create</strong> and <strong>copy the token</strong> (you won't see it again!)",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/settings/secrets/actions" target="_blank">GitHub Repo &rarr; Settings &rarr; Secrets</a>',
                "Create/update secret named <code>ADO_PAT</code> with the token",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">Actions tab</a> and click <strong>Run workflow</strong>',
            ],
        })
    else:
        errors.append({
            "title": "ADO Token May Be Expired",
            "icon": "\u26a0\ufe0f",
            "severity": "likely",
            "time_to_fix": "~3 minutes",
            "description": "ADO tokens in this org expire every <strong>7 days</strong>. If bugs aren't showing up, the token likely needs renewal.",
            "fix": [
                'Go to <a href="https://office.visualstudio.com/_usersSettings/tokens" target="_blank">office.visualstudio.com &rarr; Personal Access Tokens</a>',
                'Find your <code>VoC-Pipeline</code> token &mdash; check if it says <strong>Expired</strong>',
                "If expired: click <strong>Regenerate</strong> and copy the new token",
                "If no token exists: click <strong>+ New Token</strong> (Name: VoC-Pipeline, Scope: Work Items Read)",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/settings/secrets/actions" target="_blank">GitHub Repo &rarr; Settings &rarr; Secrets</a>',
                "Update the <code>ADO_PAT</code> secret with the new token",
                f'Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">Actions tab</a> and click <strong>Run workflow</strong>',
            ],
        })

    if not errors:
        errors.append({
            "title": "Unknown Pipeline Error",
            "icon": "\u274c",
            "severity": "unknown",
            "time_to_fix": "Varies",
            "description": "The pipeline failed for an unexpected reason. Check the logs for details.",
            "fix": [
                f'Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">GitHub Actions</a>',
                "Click the latest failed workflow run",
                'Expand the <strong>Run VoC Pipeline</strong> step to see the error message',
                "Common issues: network timeout, API rate limit, Python import error",
                'If stuck, <a href="https://github.com/{GITHUB_REPO}/issues/new" target="_blank">create a GitHub Issue</a> with the error text',
            ],
        })

    return errors


def _health_checks() -> list[dict]:
    """Run health checks on all integrations."""
    checks = []

    # Anthropic API Key
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    checks.append({
        "name": "Claude AI (Anthropic)",
        "status": "configured" if key else "missing",
        "required": True,
        "detail": "API key is set" if key else "ANTHROPIC_API_KEY secret not found",
    })

    # ADO PAT
    pat = os.environ.get("SYSTEM_ACCESSTOKEN", "")
    checks.append({
        "name": "Azure DevOps (Bug Linking)",
        "status": "configured" if pat else "not configured",
        "required": False,
        "detail": "PAT is set (expires every 7 days)" if pat else "ADO_PAT secret not found &mdash; bug linking will be skipped",
    })

    # Teams Webhook
    teams = os.environ.get("TEAMS_WEBHOOK_URL", "")
    checks.append({
        "name": "Microsoft Teams Notifications",
        "status": "configured" if teams else "not configured",
        "required": False,
        "detail": "Webhook URL is set" if teams else "TEAMS_WEBHOOK_URL secret not found &mdash; Teams alerts will be skipped",
    })

    # SharePoint
    graph = os.environ.get("GRAPH_CLIENT_ID", "")
    checks.append({
        "name": "SharePoint Upload",
        "status": "configured" if graph else "not configured",
        "required": False,
        "detail": "Graph API credentials set" if graph else "GRAPH_CLIENT_ID not found &mdash; SharePoint upload will be skipped",
    })

    return checks


def generate_error_html(errors: list[dict], checks: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%B %d, %Y &middot; %H:%M UTC")

    # Health check table
    check_rows = ""
    for ch in checks:
        if ch["status"] == "configured":
            status_html = '<span class="status-ok">Configured</span>'
        elif ch["status"] == "missing":
            status_html = '<span class="status-error">Missing</span>'
        else:
            status_html = '<span class="status-skip">Not Set Up</span>'

        req = '<span class="req-yes">Required</span>' if ch["required"] else '<span class="req-no">Optional</span>'
        check_rows += f"""
        <tr>
            <td class="check-name">{ch['name']}</td>
            <td>{status_html}</td>
            <td>{req}</td>
            <td class="check-detail">{ch['detail']}</td>
        </tr>"""

    # Error cards
    error_cards = ""
    for i, err in enumerate(errors, 1):
        sev_class = {"blocking": "sev-blocking", "likely": "sev-likely", "optional": "sev-optional"}.get(err.get("severity", ""), "sev-unknown")

        steps_html = ""
        for j, step in enumerate(err["fix"], 1):
            steps_html += f"""
            <div class="step">
                <div class="step-num">{j}</div>
                <div class="step-text">{step}</div>
            </div>"""

        error_cards += f"""
        <div class="error-card {sev_class}">
            <div class="error-top">
                <span class="error-icon">{err['icon']}</span>
                <div class="error-title-wrap">
                    <h2>{err['title']}</h2>
                    <div class="error-meta">
                        <span class="fix-time">Estimated fix: {err.get('time_to_fix', 'Unknown')}</span>
                    </div>
                </div>
            </div>
            <p class="error-desc">{err['description']}</p>
            <div class="fix-section">
                <h3>Step-by-step fix:</h3>
                {steps_html}
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Customer Pulse &mdash; Pipeline Needs Attention</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
        background: #fbfbfd; color: #1d1d1f;
        min-height: 100vh; padding: 0;
        -webkit-font-smoothing: antialiased;
    }}

    /* Hero */
    .hero {{
        background: linear-gradient(135deg, #1d1d1f, #2c2c2e);
        color: #f5f5f7; text-align: center;
        padding: 64px 20px 48px;
    }}
    .hero h1 {{
        font-size: 40px; font-weight: 700;
        background: linear-gradient(135deg, #FF9500, #FF3B30);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }}
    .hero .sub {{ color: #a1a1a6; font-size: 17px; }}
    .hero .timestamp {{ color: #6e6e73; font-size: 14px; margin-top: 12px; }}

    .container {{ max-width: 780px; margin: 0 auto; padding: 0 24px; }}

    /* Quick Actions */
    .quick-actions {{
        display: flex; gap: 12px; justify-content: center;
        padding: 24px 20px; flex-wrap: wrap;
    }}
    .quick-btn {{
        display: inline-flex; align-items: center; gap: 8px;
        padding: 12px 24px; border-radius: 12px;
        font-size: 14px; font-weight: 600;
        text-decoration: none; transition: all 0.2s;
        border: 1px solid transparent;
    }}
    .quick-btn-primary {{
        background: #0071e3; color: #fff;
    }}
    .quick-btn-primary:hover {{ background: #0077ED; transform: translateY(-1px); }}
    .quick-btn-secondary {{
        background: #fff; color: #0071e3; border-color: #d2d2d7;
    }}
    .quick-btn-secondary:hover {{ background: #f5f5f7; }}

    /* Health Table */
    .health-section {{
        padding: 32px 0;
    }}
    .section-title {{
        font-size: 24px; font-weight: 700;
        margin-bottom: 20px; letter-spacing: -0.02em;
    }}
    .health-table {{
        width: 100%; border-collapse: collapse;
        background: #fff; border-radius: 16px;
        overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        border: 1px solid rgba(0,0,0,0.04);
    }}
    .health-table th {{
        text-align: left; padding: 14px 18px;
        border-bottom: 2px solid #f0f0f5;
        font-size: 11px; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.06em;
        color: #86868b;
    }}
    .health-table td {{
        padding: 14px 18px; border-bottom: 1px solid #f5f5f7;
        font-size: 14px;
    }}
    .health-table tr:last-child td {{ border-bottom: none; }}
    .check-name {{ font-weight: 600; }}
    .check-detail {{ color: #86868b; font-size: 13px; }}
    .status-ok {{
        background: #e8fae8; color: #248A3D; padding: 3px 10px;
        border-radius: 8px; font-size: 12px; font-weight: 600;
    }}
    .status-error {{
        background: #fff1f0; color: #FF3B30; padding: 3px 10px;
        border-radius: 8px; font-size: 12px; font-weight: 600;
    }}
    .status-skip {{
        background: #f5f5f7; color: #86868b; padding: 3px 10px;
        border-radius: 8px; font-size: 12px; font-weight: 600;
    }}
    .req-yes {{ color: #FF3B30; font-size: 12px; font-weight: 600; }}
    .req-no {{ color: #86868b; font-size: 12px; }}

    /* Error Cards */
    .errors-section {{ padding: 8px 0 32px; }}
    .error-card {{
        background: #fff; border-radius: 20px; padding: 0;
        margin-bottom: 20px; box-shadow: 0 2px 16px rgba(0,0,0,0.05);
        overflow: hidden;
    }}
    .sev-blocking {{ border-top: 4px solid #FF3B30; }}
    .sev-likely {{ border-top: 4px solid #FF9500; }}
    .sev-optional {{ border-top: 4px solid #FFCC00; }}
    .sev-unknown {{ border-top: 4px solid #86868b; }}

    .error-top {{
        display: flex; align-items: flex-start; gap: 16px;
        padding: 28px 28px 0;
    }}
    .error-icon {{ font-size: 36px; flex-shrink: 0; }}
    .error-title-wrap {{ flex: 1; }}
    .error-title-wrap h2 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
    .error-meta {{ display: flex; gap: 16px; }}
    .fix-time {{
        font-size: 13px; color: #86868b;
        background: #f5f5f7; padding: 2px 10px; border-radius: 8px;
    }}

    .error-desc {{
        color: #424245; line-height: 1.6;
        padding: 12px 28px 0; font-size: 15px;
    }}

    .fix-section {{
        margin: 20px 28px 28px; padding: 24px;
        background: #f5f5f7; border-radius: 16px;
    }}
    .fix-section h3 {{
        font-size: 14px; font-weight: 700;
        color: #1d1d1f; margin-bottom: 16px;
        text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .step {{
        display: flex; gap: 14px; margin-bottom: 14px;
        align-items: flex-start;
    }}
    .step:last-child {{ margin-bottom: 0; }}
    .step-num {{
        width: 28px; height: 28px; border-radius: 50%;
        background: #0071e3; color: #fff;
        font-size: 14px; font-weight: 700;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
    }}
    .step-text {{
        font-size: 14px; color: #424245; line-height: 1.6;
        padding-top: 3px;
    }}
    .step-text a {{ color: #0071e3; text-decoration: none; }}
    .step-text a:hover {{ text-decoration: underline; }}
    .step-text code {{
        background: #e8e8ed; padding: 2px 6px; border-radius: 4px;
        font-family: 'SF Mono', 'Menlo', monospace; font-size: 13px;
    }}

    /* Help Section */
    .help-section {{
        padding: 32px 0;
    }}
    .help-grid {{
        display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
    }}
    .help-card {{
        background: #fff; border-radius: 16px; padding: 24px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.04);
        border: 1px solid rgba(0,0,0,0.04);
    }}
    .help-card h3 {{ font-size: 16px; font-weight: 600; margin-bottom: 8px; }}
    .help-card p {{ font-size: 14px; color: #424245; line-height: 1.5; }}
    .help-card a {{ color: #0071e3; text-decoration: none; }}
    .help-card a:hover {{ text-decoration: underline; }}

    .footer {{
        text-align: center; padding: 32px 20px;
        color: #86868b; font-size: 13px;
        border-top: 1px solid #e8e8ed; margin-top: 24px;
    }}

    @media (max-width: 768px) {{
        .hero h1 {{ font-size: 28px; }}
        .help-grid {{ grid-template-columns: 1fr; }}
        .error-top {{ padding: 20px 20px 0; }}
        .error-desc {{ padding: 12px 20px 0; }}
        .fix-section {{ margin: 16px 20px 20px; padding: 16px; }}
        .health-table {{ font-size: 13px; }}
    }}
</style>
</head>
<body>

<div class="hero">
    <h1>Pipeline Needs Attention</h1>
    <p class="sub">Customer Pulse encountered an issue. Here's what happened and how to fix it.</p>
    <p class="timestamp">{now}</p>
</div>

<div class="quick-actions">
    <a href="https://github.com/{GITHUB_REPO}/settings/secrets/actions" target="_blank" class="quick-btn quick-btn-primary">
        Update Secrets
    </a>
    <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank" class="quick-btn quick-btn-secondary">
        View Logs &amp; Re-run
    </a>
    <a href="https://github.com/{GITHUB_REPO}/issues/new?title=Pipeline+Error&body=The+daily+pipeline+failed.+Please+check." target="_blank" class="quick-btn quick-btn-secondary">
        Report Issue
    </a>
</div>

<div class="container">

    <div class="health-section">
        <h2 class="section-title">System Health Check</h2>
        <table class="health-table">
            <thead>
                <tr>
                    <th>Integration</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {check_rows}
            </tbody>
        </table>
    </div>

    <div class="errors-section">
        <h2 class="section-title">Issues Found</h2>
        {error_cards}
    </div>

    <div class="help-section">
        <h2 class="section-title">Need Help?</h2>
        <div class="help-grid">
            <div class="help-card">
                <h3>What is this dashboard?</h3>
                <p>Customer Pulse automatically collects and analyzes Outlook customer reviews every day. When something goes wrong (usually an expired token), this page appears instead of the normal dashboard.</p>
            </div>
            <div class="help-card">
                <h3>I'm not a developer. Can I fix this?</h3>
                <p><strong>Yes!</strong> Most issues are expired tokens that just need renewal. Follow the numbered steps above &mdash; each one links directly to the page you need. No coding required.</p>
            </div>
            <div class="help-card">
                <h3>How do I re-run the pipeline?</h3>
                <p>Go to <a href="https://github.com/{GITHUB_REPO}/actions" target="_blank">GitHub Actions</a>, click on <strong>"Customer Pulse - Daily VoC"</strong>, then click <strong>"Run workflow"</strong> (blue button on the right).</p>
            </div>
            <div class="help-card">
                <h3>Want to contribute?</h3>
                <p>The code is at <a href="https://github.com/{GITHUB_REPO}" target="_blank">github.com/{GITHUB_REPO}</a>. Fork it, make changes, and submit a pull request. See the README for setup instructions.</p>
            </div>
        </div>
    </div>

</div>

<div class="footer">
    <p>Customer Pulse v3 &middot; Voice of Customer &middot; Outlook Team</p>
    <p style="margin-top: 4px;">After fixing the issue, go to GitHub Actions and click <strong>"Run workflow"</strong> to retry.</p>
</div>

</body>
</html>"""


def main():
    exit_code = sys.argv[1] if len(sys.argv) > 1 else "1"
    print(f"\n  Pipeline failed (exit code {exit_code}). Generating error dashboard...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    errors = detect_errors()
    checks = _health_checks()
    html = generate_error_html(errors, checks)

    out_path = OUTPUT_DIR / "pulse_dashboard_v3.html"
    out_path.write_text(html)
    print(f"  Error dashboard: {out_path}")

    for err in errors:
        print(f"  {err['icon']} {err['title']}")


if __name__ == "__main__":
    main()
