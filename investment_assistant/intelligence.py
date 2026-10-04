from urllib.parse import urlsplit

from investment_assistant import alerts, news, portfolio


def _safe_news_url(value):
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return value.strip()


def _price_overrides(portfolio_data):
    return {
        symbol: position["current_price"]
        for symbol, position in portfolio_data.get("positions", {}).items()
        if position.get("current_price") is not None
    }


def _collect_news(symbols):
    articles = []
    failures = []
    for symbol in symbols:
        try:
            results = news.get_company_news(
                symbol,
                max_items=5,
                days=7,
            )
        except Exception as error:
            failures.append(f"{symbol}: {error}")
            continue

        for item in results:
            headline = item.get("title") or item.get("headline")
            if not headline:
                continue
            articles.append({
                "symbol": symbol,
                "headline": headline,
                "source": item.get("source"),
                "publication_date": (
                    item.get("published") or item.get("publication_date")
                ),
                "url": _safe_news_url(item.get("link") or item.get("url")),
            })
    return articles, failures


def _normalize_news(news_by_symbol):
    articles = []
    for symbol, items in (news_by_symbol or {}).items():
        for item in items or []:
            headline = item.get("title") or item.get("headline")
            if not headline:
                continue
            articles.append({
                "symbol": symbol,
                "headline": headline,
                "source": item.get("source"),
                "publication_date": (
                    item.get("published") or item.get("publication_date")
                ),
                "url": _safe_news_url(item.get("link") or item.get("url")),
            })
    return articles


def _build_contributors(change_report):
    if not change_report.get("holding_comparison_available"):
        return None

    contributions = [
        {
            "symbol": holding["symbol"],
            "company_name": holding["company_name"],
            "market_value_change": holding.get("market_value_change"),
            "status": holding["status"],
        }
        for holding in change_report.get("holding_changes", [])
        if holding.get("market_value_change") is not None
    ]
    positive = [item for item in contributions if item["market_value_change"] > 0]
    negative = [item for item in contributions if item["market_value_change"] < 0]
    return {
        "available": True,
        "largest_positive": (
            max(positive, key=lambda item: item["market_value_change"])
            if positive else None
        ),
        "largest_negative": (
            min(negative, key=lambda item: item["market_value_change"])
            if negative else None
        ),
        "contributions": contributions,
        "method": (
            "Holding market-value differences between the latest two "
            "detailed snapshots; this is contribution context, not causation."
        ),
    }


def _build_monitor_items(change_report, articles, concentration, limitations):
    items = []
    for alert in change_report.get("alerts", []):
        items.append({
            "type": "alert",
            "severity": alert.get("severity"),
            "symbol": alert.get("symbol"),
            "description": alert.get("message"),
        })

    if concentration.get("largest_holding_symbol"):
        items.append({
            "type": "concentration",
            "severity": "INFO",
            "symbol": concentration["largest_holding_symbol"],
            "description": (
                f"{concentration['largest_holding_symbol']} represents "
                f"{concentration['largest_holding_percent']:.2f}% of "
                "current portfolio value."
            ),
        })
    for article in articles:
        items.append({
            "type": "news",
            "severity": "INFO",
            "symbol": article["symbol"],
            "description": article["headline"],
        })
    for limitation in limitations:
        items.append({
            "type": "data_limitation",
            "severity": "INFO",
            "symbol": None,
            "description": limitation,
        })
    return items


def get_portfolio_change_summary(change_report):
    """Return a deterministic, structured summary of the supplied changes."""
    available = bool(change_report.get("available"))
    value_change = change_report.get("portfolio_value", {})
    pnl_change = change_report.get("total_pnl", {})
    holding_changes = change_report.get("holding_changes", [])
    concentration_changes = change_report.get(
        "concentration_changes",
        [],
    )
    return {
        "available": available,
        "limitation": change_report.get("message"),
        "previous_snapshot_date": change_report.get("previous_date"),
        "latest_snapshot_date": change_report.get("latest_date"),
        "holding_comparison_previous_date": change_report.get(
            "holding_comparison_previous_date"
        ),
        "holding_comparison_latest_date": change_report.get(
            "holding_comparison_latest_date"
        ),
        "portfolio_value_change": (
            value_change.get("change") if available else None
        ),
        "portfolio_value_change_percent": (
            value_change.get("change_percent") if available else None
        ),
        "total_pnl_change": pnl_change.get("change") if available else None,
        "holding_changes": holding_changes,
        "concentration_changes": concentration_changes,
        "added_or_removed_holdings": [
            item for item in holding_changes
            if item.get("status") in ("added", "removed")
        ],
        "alerts": change_report.get("alerts", []),
        "contributors": _build_contributors(change_report),
    }


def generate_portfolio_intelligence(
    *,
    portfolio_data=None,
    analytics=None,
    performance_history=None,
    historical_summary=None,
    portfolio_changes=None,
    news_by_symbol=None,
    news_errors=None,
    market_data_error=None,
):
    """Build a factual portfolio-intelligence report from existing services."""
    limitations = []
    market_data_unavailable = False
    if market_data_error:
        limitations.append(
            f"Current market data is unavailable: {market_data_error}"
        )
    if portfolio_data is None and market_data_error:
        market_data_unavailable = True
        portfolio_data = {
            "positions": {},
            "total_invested": None,
            "total_current_value": None,
            "total_realized_pnl": None,
            "total_unrealized_pnl": None,
            "total_pnl": None,
            "total_return_percent": None,
        }
    elif portfolio_data is None:
        try:
            portfolio_data = portfolio.calculate_portfolio_valuation()
        except RuntimeError as error:
            market_data_unavailable = True
            portfolio_data = {
                "positions": {},
                "total_invested": None,
                "total_current_value": None,
                "total_realized_pnl": None,
                "total_unrealized_pnl": None,
                "total_pnl": None,
                "total_return_percent": None,
            }
            limitations.append(f"Market data is unavailable: {error}")

    positions = portfolio_data.get("positions", {})
    overrides = _price_overrides(portfolio_data)
    if analytics is None:
        if market_data_unavailable or market_data_error:
            analytics = {
                "allocation": {},
                "concentration": {
                    "holding_count": len(positions),
                    "largest_holding_symbol": None,
                    "largest_holding_percent": None,
                    "largest_holding_value": None,
                },
                "max_drawdown": portfolio.calculate_max_drawdown(),
            }
        else:
            analytics = portfolio.get_portfolio_analytics_summary(
                price_overrides=overrides,
            )
    if performance_history is None:
        performance_history = portfolio.get_portfolio_performance_history()
    if historical_summary is None:
        historical_summary = portfolio.get_historical_performance_summary()
    if portfolio_changes is None:
        portfolio_changes = alerts.get_portfolio_change_report()

    concentration = analytics.get("concentration", {})
    allocation = analytics.get("allocation", {})
    max_drawdown = analytics.get("max_drawdown", {})
    if not performance_history:
        limitations.append(
            "Historical performance is unavailable because no snapshots "
            "have been recorded."
        )
    elif len(performance_history) == 1:
        limitations.append(
            "Historical performance is limited because only one snapshot "
            "is available."
        )

    if not portfolio_changes.get("available"):
        limitations.append(
            portfolio_changes.get(
                "message",
                "Not enough historical snapshots to calculate changes.",
            )
        )
    elif not portfolio_changes.get("holding_comparison_available"):
        limitations.append(
            portfolio_changes.get(
                "holding_comparison_message",
                "Detailed holding-level history is unavailable.",
            )
        )
    elif (
        portfolio_changes.get("holding_comparison_latest_date")
        and portfolio_changes.get("latest_date")
        and portfolio_changes["holding_comparison_latest_date"]
        != portfolio_changes["latest_date"]
    ):
        limitations.append(
            "The latest aggregate snapshot has no holding details; "
            "holding comparisons use the latest two detailed snapshots."
        )

    if news_by_symbol is None:
        articles, news_failures = _collect_news(positions)
        news_failures.extend(news_errors or [])
    else:
        articles = _normalize_news(news_by_symbol)
        news_failures = list(news_errors or [])
    if not articles and not news_failures:
        limitations.append(
            "No relevant recent news was found for the current holdings."
        )
    elif news_failures:
        limitations.append(
            "Some news could not be retrieved: "
            + "; ".join(news_failures)
        )

    current_total_value = portfolio_data.get("total_current_value")
    overview = {
        "current_cost_basis": portfolio_data.get("total_invested"),
        "current_portfolio_value": current_total_value,
        "realized_pnl": portfolio_data.get("total_realized_pnl"),
        "unrealized_pnl": portfolio_data.get("total_unrealized_pnl"),
        "total_pnl": portfolio_data.get("total_pnl"),
        "unrealized_return_percent": portfolio_data.get(
            "total_return_percent"
        ),
        "holding_count": concentration.get(
            "holding_count",
            len(positions),
        ),
        "largest_holding_symbol": concentration.get(
            "largest_holding_symbol"
        ),
        "largest_holding_allocation_percent": concentration.get(
            "largest_holding_percent"
        ),
    }

    changes_available = bool(portfolio_changes.get("available"))
    performance = {
        "available": (
            len(performance_history) >= 2 and changes_available
        ),
        "snapshot_count": len(performance_history),
        "latest_snapshot_date": portfolio_changes.get("latest_date"),
        "previous_snapshot_date": portfolio_changes.get("previous_date"),
        "portfolio_value_change": (
            portfolio_changes.get("portfolio_value", {}).get("change")
            if changes_available else None
        ),
        "portfolio_value_change_percent": (
            portfolio_changes.get("portfolio_value", {}).get("change_percent")
            if changes_available else None
        ),
        "total_pnl_change": (
            portfolio_changes.get("total_pnl", {}).get("change")
            if changes_available else None
        ),
        "max_drawdown": max_drawdown,
        "historical_summary": historical_summary,
    }
    holding_changes = {
        "available": bool(
            portfolio_changes.get("holding_comparison_available")
        ),
        "limitation": portfolio_changes.get(
            "holding_comparison_message"
        ),
        "previous_date": portfolio_changes.get(
            "holding_comparison_previous_date"
        ),
        "latest_date": portfolio_changes.get(
            "holding_comparison_latest_date"
        ),
        "items": portfolio_changes.get("holding_changes", []),
        "concentration_changes": portfolio_changes.get(
            "concentration_changes", []
        ),
    }
    summary = get_portfolio_change_summary(portfolio_changes)
    contributors = summary["contributors"]
    concentration_report = {
        "largest_holding_symbol": concentration.get(
            "largest_holding_symbol"
        ),
        "largest_holding_value": concentration.get("largest_holding_value"),
        "largest_holding_percent": concentration.get(
            "largest_holding_percent"
        ),
        "allocations": [
            {
                "symbol": symbol,
                "current_value": item.get("current_value"),
                "allocation_percent": item.get("allocation_percent"),
            }
            for symbol, item in sorted(allocation.items())
        ],
        "observation": (
            f"{concentration['largest_holding_symbol']} represents "
            f"{concentration['largest_holding_percent']:.2f}% of current "
            "portfolio value."
            if concentration.get("largest_holding_symbol")
            else "No current holding allocation is available."
        ),
    }
    alert_items = portfolio_changes.get("alerts", [])
    monitor_items = _build_monitor_items(
        portfolio_changes,
        articles,
        concentration,
        limitations,
    )
    return {
        "portfolio_overview": overview,
        "performance": performance,
        "holding_level_changes": holding_changes,
        "contributors": contributors,
        "concentration": concentration_report,
        "alerts": alert_items,
        "relevant_news": {
            "available": bool(articles),
            "items": articles,
            "message": None if articles else "No relevant recent news is available.",
        },
        "things_to_monitor": monitor_items,
        "data_limitations": limitations,
        "what_changed": summary,
    }
