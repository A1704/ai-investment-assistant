from datetime import datetime, timedelta, timezone

import feedparser


NEWS_QUERIES = {
    "COCHINSHIP": "Cochin Shipyard",
    "HINDZINC": "Hindustan Zinc",
    "SILVERBEES": '"Nippon India Silver ETF"',
}


def get_company_news(symbol, max_items=5, days=7):
    """
    Fetch recent news headlines for a portfolio holding.

    Returns:
        title
        source
        link
        published
    """

    if symbol not in NEWS_QUERIES:
        raise ValueError(f"Unsupported portfolio symbol: {symbol}")

    query = NEWS_QUERIES[symbol]

    feed_url = (
        "https://news.google.com/rss/search"
        f"?q={query.replace(' ', '+')}"
        "&hl=en-IN"
        "&gl=IN"
        "&ceid=IN:en"
    )

    feed = feedparser.parse(feed_url)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    articles = []
    seen_titles = set()

    for entry in feed.entries:

        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        published = entry.get("published", "").strip()

        if not title or not link:
            continue

        # Remove duplicate headlines.
        title_key = title.lower()

        if title_key in seen_titles:
            continue

        # Try to check publication date.
        published_time = entry.get("published_parsed")

        if published_time:
            published_datetime = datetime(
                published_time.tm_year,
                published_time.tm_mon,
                published_time.tm_mday,
                published_time.tm_hour,
                published_time.tm_min,
                published_time.tm_sec,
                tzinfo=timezone.utc,
            )

            if published_datetime < cutoff:
                continue

        # Google News usually puts the source after " - ".
        if " - " in title:
            clean_title, source = title.rsplit(" - ", 1)
        else:
            clean_title = title
            source = "Unknown"

        seen_titles.add(title_key)

        articles.append(
            {
                "title": clean_title.strip(),
                "source": source.strip(),
                "link": link,
                "published": published,
            }
        )

        if len(articles) >= max_items:
            break

    return articles


def test_news():
    symbols = [
        "COCHINSHIP",
        "HINDZINC",
        "SILVERBEES",
    ]

    for symbol in symbols:

        print("\n" + "=" * 70)
        print(f"NEWS: {symbol}")
        print("=" * 70)

        try:
            articles = get_company_news(symbol)

            if not articles:
                print("No recent news found.")
                continue

            for index, article in enumerate(articles, start=1):

                print(f"\n{index}. {article['title']}")
                print(f"   Source: {article['source']}")
                print(f"   Published: {article['published']}")
                print(f"   Link: {article['link']}")

        except Exception as exc:
            print(f"ERROR: {exc}")


if __name__ == "__main__":
    test_news()