"""News provider abstraction — swappable sources behind one interface.

Providers return plain Headline records; all scoring happens in
engine/news_score.py so a provider swap never changes the scoring model.

  YFinanceNewsProvider : default, free, no API key. Pulls headlines for the
                         market-relevant tickers the spec lists.
  NewsApiProvider      : used automatically when NEWS_API_KEY is set.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import requests

log = logging.getLogger(__name__)


@dataclass
class Headline:
    title: str
    url: str
    source: str | None
    published_utc: datetime
    summary: str | None = None
    raw: dict | None = None


class NewsProvider(Protocol):
    name: str

    def fetch_headlines(self) -> tuple[list[Headline], str | None]:
        """Returns (headlines, error_message). Never raises."""
        ...


# ---------------------------------------------------------------------------
DEFAULT_TICKERS = ["SPY", "QQQ", "^GSPC", "ES=F", "^VIX", "^TNX"]


class YFinanceNewsProvider:
    name = "yfinance"

    def __init__(self, tickers: list[str] | None = None, max_per_ticker: int = 10):
        self.tickers = tickers or DEFAULT_TICKERS
        self.max_per_ticker = max_per_ticker

    def fetch_headlines(self) -> tuple[list[Headline], str | None]:
        try:
            import yfinance as yf
        except ImportError:
            return [], "yfinance not installed"

        headlines: list[Headline] = []
        errors: list[str] = []
        seen_urls: set[str] = set()
        for ticker in self.tickers:
            try:
                items = yf.Ticker(ticker).news or []
            except Exception as exc:  # yfinance raises a zoo of exception types
                errors.append(f"{ticker}: {exc}")
                continue
            for item in items[: self.max_per_ticker]:
                h = self._parse_item(item)
                if h is None or h.url in seen_urls:
                    continue
                seen_urls.add(h.url)
                headlines.append(h)

        err = None
        if not headlines:
            err = "; ".join(errors) if errors else "yfinance returned no news"
        elif errors:
            log.warning("yfinance news partial errors: %s", "; ".join(errors))
        return headlines, err

    @staticmethod
    def _parse_item(item: dict) -> Headline | None:
        # yfinance >= 0.2.50 nests everything under "content"; older versions
        # are flat. Support both.
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = content.get("title")
        if not title:
            return None

        url = None
        canonical = content.get("canonicalUrl")
        if isinstance(canonical, dict):
            url = canonical.get("url")
        url = url or content.get("link") or item.get("link")
        if not url:
            return None

        published = None
        pub_date = content.get("pubDate") or content.get("displayTime")
        if pub_date:
            try:
                published = datetime.fromisoformat(str(pub_date).replace("Z", "+00:00"))
            except ValueError:
                published = None
        if published is None and item.get("providerPublishTime"):
            try:
                published = datetime.fromtimestamp(int(item["providerPublishTime"]), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None
        if published is None:
            published = datetime.now(timezone.utc)

        source = None
        provider = content.get("provider")
        if isinstance(provider, dict):
            source = provider.get("displayName")
        source = source or item.get("publisher")

        summary = content.get("summary") or content.get("description")
        return Headline(
            title=title, url=url, source=source,
            published_utc=published, summary=summary, raw=item,
        )


# ---------------------------------------------------------------------------
NEWSAPI_QUERY = (
    '"S&P 500" OR SPX OR "stock market" OR "Federal Reserve" OR FOMC OR CPI '
    'OR "treasury yields" OR VIX OR "rate decision" OR "jobs report"'
)


class NewsApiProvider:
    name = "newsapi"

    def __init__(self, api_key: str, query: str = NEWSAPI_QUERY, page_size: int = 50):
        self.api_key = api_key
        self.query = query
        self.page_size = page_size

    def fetch_headlines(self) -> tuple[list[Headline], str | None]:
        if not self.api_key:
            return [], "NEWS_API_KEY is not set"
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": self.query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": self.page_size,
                },
                headers={"X-Api-Key": self.api_key},
                timeout=20,
            )
        except requests.RequestException as exc:
            return [], f"NewsAPI request failed: {exc}"
        if resp.status_code == 429:
            return [], "NewsAPI rate limited (429)"
        if resp.status_code != 200:
            return [], f"NewsAPI HTTP {resp.status_code}: {resp.text[:200]}"
        try:
            payload = resp.json()
        except ValueError:
            return [], "NewsAPI returned non-JSON"

        headlines = []
        for a in payload.get("articles", []):
            title, url = a.get("title"), a.get("url")
            if not title or not url:
                continue
            try:
                published = datetime.fromisoformat(str(a.get("publishedAt")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                published = datetime.now(timezone.utc)
            headlines.append(
                Headline(
                    title=title, url=url,
                    source=(a.get("source") or {}).get("name"),
                    published_utc=published,
                    summary=a.get("description"), raw=a,
                )
            )
        return headlines, None


def build_provider(news_api_key: str) -> NewsProvider:
    if news_api_key:
        return NewsApiProvider(news_api_key)
    return YFinanceNewsProvider()
