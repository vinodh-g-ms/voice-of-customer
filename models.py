"""Data models for Customer Pulse v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Review:
    """A single customer feedback item from any source."""
    source: str          # "appstore", "reddit", "msqa"
    title: str
    body: str
    rating: Optional[int]  # 1-5 for App Store, None for others
    author: str
    date: Optional[datetime]
    country: str = ""
    url: str = ""
    version: str = ""    # app version from App Store (im:version)
    platform: str = ""   # "ios" or "mac"

    @property
    def text(self) -> str:
        parts = [p for p in [self.title, self.body] if p]
        return " — ".join(parts)

    def compact(self) -> str:
        rating_str = f" [{self.rating}★]" if self.rating else ""
        src = self.source
        if self.country:
            src = f"{src}/{self.country}"
        ver = f" v{self.version}" if self.version else ""
        return f"[{src}{rating_str}{ver}] {self.text}"

    def to_dict(self) -> dict:
        return {
            "source": self.source, "title": self.title, "body": self.body,
            "rating": self.rating, "author": self.author,
            "date": self.date.isoformat() if self.date else None,
            "country": self.country, "url": self.url,
            "version": self.version, "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        date = None
        if d.get("date"):
            try:
                date = datetime.fromisoformat(d["date"])
            except (ValueError, TypeError):
                pass
        return cls(
            source=d["source"], title=d.get("title", ""), body=d.get("body", ""),
            rating=d.get("rating"), author=d.get("author", ""), date=date,
            country=d.get("country", ""), url=d.get("url", ""),
            version=d.get("version", ""), platform=d.get("platform", ""),
        )


@dataclass
class ADOMatch:
    """A matching ADO work item (bug)."""
    work_item_id: int
    title: str
    state: str
    assigned_to: str = ""
    url: str = ""
    changed_date: Optional[datetime] = None

    @property
    def activity_age_days(self) -> Optional[int]:
        if self.changed_date is None:
            return None
        return max(0, (datetime.now(timezone.utc) - self.changed_date).days)

    @property
    def activity_label(self) -> str:
        age = self.activity_age_days
        if age is None:
            return ""
        if age == 0:
            return "today"
        if age == 1:
            return "yesterday"
        return f"{age}d ago"

    def to_dict(self) -> dict:
        return {
            "work_item_id": self.work_item_id, "title": self.title,
            "state": self.state, "assigned_to": self.assigned_to,
            "url": self.url,
            "changed_date": self.changed_date.isoformat() if self.changed_date else None,
        }


@dataclass
class TopicCluster:
    """A cluster of related feedback identified by Claude."""
    topic: str
    severity: str
    count: int
    sentiment_score: float
    summary: str
    quotes: list[str] = field(default_factory=list)
    source_breakdown: dict[str, int] = field(default_factory=dict)
    ado_matches: list[ADOMatch] = field(default_factory=list)
    version_breakdown: dict[str, int] = field(default_factory=dict)
    # Trend fields
    trend: str = ""              # "up", "down", "new", ""
    previous_count: int = 0
    count_delta: int = 0
    weekly_counts: dict[str, int] = field(default_factory=dict)
    matched_reviews: list = field(default_factory=list)  # actual reviews matched to this cluster

    def to_dict(self) -> dict:
        return {
            "topic": self.topic, "severity": self.severity,
            "count": self.count, "sentiment_score": self.sentiment_score,
            "summary": self.summary, "quotes": self.quotes,
            "source_breakdown": self.source_breakdown,
            "ado_matches": [m.to_dict() for m in self.ado_matches],
            "version_breakdown": self.version_breakdown,
            "trend": self.trend, "previous_count": self.previous_count,
            "count_delta": self.count_delta,
            "weekly_counts": self.weekly_counts,
        }


@dataclass
class PulseReport:
    """Analysis report for one platform + period combination."""
    generated_at: datetime
    days_analyzed: int
    total_reviews: int
    overall_sentiment: float
    overall_summary: str
    clusters: list[TopicCluster] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    data_quality_notes: list[str] = field(default_factory=list)
    platform: str = ""
    period_label: str = ""
    earliest_review_date: Optional[datetime] = None
    latest_review_date: Optional[datetime] = None
    weekly_volume: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "days_analyzed": self.days_analyzed,
            "total_reviews": self.total_reviews,
            "overall_sentiment": self.overall_sentiment,
            "overall_summary": self.overall_summary,
            "clusters": [c.to_dict() for c in self.clusters],
            "source_counts": self.source_counts,
            "data_quality_notes": self.data_quality_notes,
            "platform": self.platform, "period_label": self.period_label,
            "earliest_review_date": self.earliest_review_date.isoformat() if self.earliest_review_date else None,
            "latest_review_date": self.latest_review_date.isoformat() if self.latest_review_date else None,
            "weekly_volume": self.weekly_volume,
        }


@dataclass
class CompositePulseReport:
    """Container for all platform + period reports."""
    generated_at: datetime
    reports: dict[str, PulseReport] = field(default_factory=dict)

    def get(self, platform: str, period: str) -> Optional[PulseReport]:
        return self.reports.get(f"{platform}_{period}")

    def put(self, platform: str, period: str, report: PulseReport):
        self.reports[f"{platform}_{period}"] = report

    @property
    def platforms(self) -> list[str]:
        seen = []
        for key in self.reports:
            plat = key.split("_")[0]
            if plat not in seen:
                seen.append(plat)
        return seen

    @property
    def periods(self) -> list[str]:
        seen = []
        for key in self.reports:
            period = key.split("_", 1)[1]
            if period not in seen:
                seen.append(period)
        return seen
