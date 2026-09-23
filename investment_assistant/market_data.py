import warnings

# Suppress the Requests dependency warning.
# The market-data requests themselves are working correctly.
warnings.filterwarnings(
    "ignore",
    category=Warning,
    module="requests",
)

import time
from datetime import datetime, timezone

import requests


YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


SYMBOL_MAP = {
    "COCHINSHIP": "COCHINSHIP.NS",
    "HINDZINC": "HINDZINC.NS",
    "SILVERBEES": "SILVERBEES.NS",
}


def get_yahoo_quote(symbol: str) -> dict:
    """
    Fetch the latest available Yahoo Finance quote metadata.

    This is a best-effort market-data source.
    It is not an exchange-authoritative real-time feed.
    """

    if symbol not in SYMBOL_MAP:
        raise ValueError(f"Unsupported portfolio symbol: {symbol}")

    yahoo_symbol = SYMBOL_MAP[symbol]
    url = f"{YAHOO_BASE_URL}/{yahoo_symbol}"

    params = {
        "range": "1d",
        "interval": "1d",
    }

    try:
        response = requests.get(
            url,
            headers=YAHOO_HEADERS,
            params=params,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        chart = data.get("chart", {})
        results = chart.get("result")

        if not results:
            error = chart.get("error")
            raise RuntimeError(
                f"No market data returned for {symbol}: {error}"
            )

        meta = results[0].get("meta", {})

        price = meta.get("regularMarketPrice")

        if price is None:
            raise RuntimeError(
                f"No current price found for {symbol}"
            )

        market_timestamp = meta.get("regularMarketTime")

        if market_timestamp:
            market_time = datetime.fromtimestamp(
                market_timestamp,
                tz=timezone.utc,
            ).isoformat()
        else:
            market_time = None

        return {
            "symbol": symbol,
            "yahoo_symbol": yahoo_symbol,
            "price": float(price),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "market_timestamp": market_time,
            "source": "Yahoo Finance chart endpoint",
            "retrieved_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not retrieve market data for {symbol}: {exc}"
        ) from exc


def test_prices() -> None:
    """Test all three portfolio symbols."""

    symbols = [
        "COCHINSHIP",
        "HINDZINC",
        "SILVERBEES",
    ]

    print("\nFetching market prices...\n")

    for symbol in symbols:
        try:
            quote = get_yahoo_quote(symbol)

            print(
                f"{symbol:<12} "
                f"₹{quote['price']:,.2f} | "
                f"{quote['exchange']} | "
                f"{quote['market_timestamp']}"
            )

            time.sleep(1)

        except Exception as exc:
            print(f"{symbol:<12} ERROR: {exc}")


if __name__ == "__main__":
    test_prices()