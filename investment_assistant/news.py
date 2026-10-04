import feedparser
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


NEWS_QUERIES = {
    "COCHINSHIP": '"Cochin Shipyard"',
    "HINDZINC": '"Hindustan Zinc"',
    "SILVERBEES": '"Nippon India Silver ETF" OR "Silver ETF"'
}


# Headlines containing these phrases are usually recommendation/opinion
# articles rather than factual company or market developments.
EXCLUDED_PHRASES = [
    "buy or sell",
    "buy, sell or hold",
    "buy sell or hold",
    "should you buy",
    "should i buy",
    "stock to buy",
    "stocks to buy",
    "top stock to buy",
    "best stock to buy",
    "target price",
    "price target",
    "buy call",
    "sell call",
    "hold call",
    "buy recommendation",
    "sell recommendation",
    "negative breakout",
    "positive breakout",
    "breakout",
    "breakdown",
    "200 dma",
    "200-day moving average",
    "52-week high",
    "52-week low",
    "technical analysis",
    "technical setup",
    "resistance level",
    "support level",
]


def is_recommendation_headline(title):
    """
    Return True when a headline looks primarily like
    an investment recommendation or technical analysis.
    """

    title_lower = title.lower()

    return any(
        phrase in title_lower
        for phrase in EXCLUDED_PHRASES
    )


def normalize_title(title):
    """
    Normalize a headline so that the same story published
    by different sources can be detected as a duplicate.
    """

    normalized = title.lower().strip()

    # Remove common source suffixes after " - "
    if " - " in normalized:
        normalized = normalized.rsplit(" - ", 1)[0]

    # Remove common punctuation
    for character in [
        ".",
        ",",
        ":",
        ";",
        "!",
        "?",
        "(",
        ")",
        "[",
        "]",
    ]:
        normalized = normalized.replace(character, "")

    # Normalize whitespace
    normalized = " ".join(normalized.split())

    return normalized


def get_company_news(symbol, max_items=5, days=7):

    query = NEWS_QUERIES.get(symbol)

    if not query:
        return []

    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(query)}"
        "&hl=en-IN"
        "&gl=IN"
        "&ceid=IN:en"
    )

    feed = feedparser.parse(url)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    results = []
    seen_titles = set()

    for entry in feed.entries:

        title = entry.get("title", "").strip()
        source = entry.get("source", {}).get("title", "").strip()
        link = entry.get("link", "").strip()
        published = entry.get("published", "")

        if not title:
            continue

        # Filter recommendation/opinion headlines
        if is_recommendation_headline(title):
            continue

        # Parse publication date when available
        published_dt = None

        if published:

            try:
                published_dt = datetime(
                    *entry.published_parsed[:6]
                ).replace(
                    tzinfo=timezone.utc
                )

            except (AttributeError, TypeError, ValueError):
                published_dt = None

        # Ignore articles outside requested time window
        if published_dt and published_dt < cutoff:
            continue

        # Remove duplicate/syndicated headlines
        normalized = normalize_title(title)

        if normalized in seen_titles:
            continue

        seen_titles.add(normalized)

        results.append(
            {
                "title": title,
                "source": source or "Unknown",
                "link": link,
                "published": published,
            }
        )

        if len(results) >= max_items:
            break

    return results