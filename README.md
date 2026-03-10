# Voice of Customer — Outlook

An automated AI-powered pipeline that collects customer feedback from multiple sources, analyzes it using Claude AI, correlates findings with Azure DevOps bugs, and publishes a live dashboard — every day at 6 AM UTC.

**Live Dashboard:** [vinodh-g-ms.github.io/voice-of-customer](https://vinodh-g-ms.github.io/voice-of-customer/)

**FHL26 Submission:** "Voice of Customer - Outlook" — *Changing how we work in the era of AI*

---

## What It Does

| Step | Action | Details |
|------|--------|---------|
| **Fetch** | Collects ~2,900 reviews daily | App Store (iOS + Mac), Google Play (Android), Reddit, Microsoft Q&A |
| **Analyze** | Claude AI clusters feedback | Sentiment scoring, topic clustering, severity ranking, trend analysis |
| **Correlate** | Links to engineering work | Searches ADO Outlook Mobile project for matching bugs |
| **Report** | Publishes live dashboard | Self-contained HTML on GitHub Pages + Teams notification |

## Platforms & Sources

| Platform | Sources | Typical Volume |
|----------|---------|---------------|
| iOS | App Store, Reddit, MS Q&A | ~1,350 reviews |
| macOS | App Store, Reddit, MS Q&A | ~450 reviews |
| Android | Google Play, Reddit, MS Q&A | ~1,100 reviews |

## Architecture

**Pattern:** Batch ETL Pipeline + Static Site Generation

```
Fetch (4 sources) → Analyze (Claude AI) → Correlate (ADO) → Report (HTML + Teams)
```

- **Schedule:** GitHub Actions cron, daily 6 AM UTC
- **AI Model:** Claude Sonnet 4 (Anthropic API)
- **Hosting:** GitHub Pages (static HTML)
- **Notifications:** Microsoft Teams via Incoming Webhook
- **Bug Linking:** Azure DevOps Work Item Search API

## Quick Start

### Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run full pipeline (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY="sk-ant-..."
python main.py

# Run for a single platform
python main.py --platforms ios

# Skip ADO correlation (no PAT needed)
python main.py --skip-ado

# Use cached data (faster re-runs)
python main.py  # automatically uses 12-hour cache
```

### CLI Options

| Flag | Description | Example |
|------|-------------|---------|
| `--platforms` | Comma-separated platforms | `--platforms ios,mac` |
| `--sources` | Comma-separated sources | `--sources appstore,reddit` |
| `--topic` | Focus analysis on a topic | `--topic "calendar sync"` |
| `--skip-ado` | Skip ADO bug correlation | `--skip-ado` |
| `--no-cache` | Force fresh data fetch | `--no-cache` |

### Output

```
output_v3/
  pulse_dashboard_v3.html   # Interactive HTML dashboard (~495KB, self-contained)
  pulse_report_v3_{ts}.md   # Markdown report for archival
  architecture.html          # Architecture documentation page
```

## GitHub Actions Pipeline

The pipeline runs automatically via `.github/workflows/daily-voc.yml`:

1. **Install dependencies** — Python 3.11 + pip
2. **Run VoC Pipeline** — `main.py` (falls back to error dashboard on failure)
3. **Send Teams Notification** — Adaptive Card with summary
4. **Upload Artifact** — Saves output for 30 days
5. **Deploy to GitHub Pages** — Pushes dashboard to `gh-pages` branch

### Required Secrets

| Secret | Purpose | Required? |
|--------|---------|-----------|
| `ANTHROPIC_API_KEY` | Claude AI API access | **Yes** |
| `ADO_PAT` | Azure DevOps bug search | Optional (expires every 7 days) |
| `TEAMS_WEBHOOK_URL` | Teams channel notifications | Optional |

Configure at: [Settings → Secrets → Actions](https://github.com/vinodh-g-ms/voice-of-customer/settings/secrets/actions)

### When Something Breaks

If the pipeline fails (usually an expired token), it automatically generates an **error dashboard** with:
- Health check table showing which integrations are down
- Step-by-step fix instructions (no coding required)
- Direct links to update secrets and re-run the pipeline

## Project Structure

```
├── main.py                 # Pipeline orchestrator
├── analysis.py             # Claude AI analysis & trend computation
├── report.py               # HTML dashboard & markdown generation
├── models.py               # Data classes (Review, TopicCluster, PulseReport)
├── config.py               # App IDs, API endpoints, constants
├── cache.py                # 12-hour TTL file cache
├── ado_search.py           # Azure DevOps Work Item Search
├── error_dashboard.py      # Error page generator (self-healing UX)
├── notify_teams.py         # Teams webhook notification
├── upload_to_sharepoint.py # SharePoint upload (optional)
├── requirements.txt        # Python dependencies
├── sources/
│   ├── appstore.py         # Apple App Store RSS feed
│   ├── playstore.py        # Google Play Store scraper
│   ├── reddit.py           # Reddit search API
│   └── msqa.py             # Microsoft Q&A scraper
└── .github/
    └── workflows/
        └── daily-voc.yml   # GitHub Actions daily pipeline
```

## Contributing

1. Fork this repo
2. Make changes
3. Test locally: `python main.py --platforms ios --skip-ado`
4. Submit a pull request

Common contributions:
- **Add a data source** — Create a new file in `sources/`, return `list[Review]`
- **Update tokens** — Go to Settings → Secrets (no code needed)
- **Improve the dashboard** — Modify `report.py`

## Owner

**Vinodhswamy** — Outlook iOS Team, FHL26
