import math

from investment_assistant import portfolio


INSUFFICIENT_HISTORY_MESSAGE = "Insufficient historical data for this metric."


def _valid_price(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def generate_risk_intelligence(
    *,
    portfolio_data=None,
    analytics=None,
    performance_history=None,
    historical_summary=None,
):
    """Build factual risk and diversification measurements from app data."""
    if portfolio_data is None:
        portfolio_data = portfolio.calculate_portfolio_valuation()

    positions = portfolio_data.get("positions", {})
    price_overrides = {
        symbol: position["current_price"]
        for symbol, position in positions.items()
        if position.get("current_price") is not None
    }
    if analytics is None:
        analytics = portfolio.get_portfolio_analytics_summary(
            price_overrides=price_overrides,
        )
    if performance_history is None:
        performance_history = portfolio.get_portfolio_performance_history()
    if historical_summary is None:
        historical_summary = portfolio.get_historical_performance_summary()

    allocations = analytics.get("allocation", {})
    concentration = analytics.get("concentration", {})
    total_value = portfolio_data.get("total_current_value")
    missing_company_symbols = {
        symbol
        for symbol, position in positions.items()
        if not position.get("company_name")
    }
    company_names = {}
    if missing_company_symbols:
        for row in portfolio.get_opening_positions():
            symbol = row[1].strip().upper()
            if symbol in missing_company_symbols and row[2]:
                company_names[symbol] = row[2]
        for row in portfolio.get_transactions():
            symbol = row[1].strip().upper()
            if symbol in missing_company_symbols and row[2]:
                company_names[symbol] = row[2]

    exposures = []
    valid_price_count = 0
    unavailable_price_count = 0
    market_data_sources = set()

    for symbol, position in sorted(positions.items()):
        allocation = allocations.get(symbol, {})
        current_price = position.get("current_price")
        is_price_valid = _valid_price(current_price)
        if is_price_valid:
            valid_price_count += 1
        else:
            unavailable_price_count += 1

        source = position.get("source")
        if source:
            market_data_sources.add(source)

        exposures.append({
            "symbol": symbol,
            "company_name": (
                position.get("company_name")
                or company_names.get(symbol.strip().upper())
            ),
            "quantity": position.get("quantity"),
            "current_price": current_price if is_price_valid else None,
            "market_value": position.get("current_value"),
            "allocation_percent": allocation.get("allocation_percent"),
            "remaining_cost_basis": position.get(
                "remaining_cost_basis",
                position.get("invested_amount"),
            ),
            "unrealized_pnl": position.get("unrealized_pnl"),
            "total_pnl": position.get("total_pnl"),
            "market_data_source": source,
        })

    allocation_values = [
        (symbol, item.get("allocation_percent"))
        for symbol, item in allocations.items()
        if isinstance(item.get("allocation_percent"), (int, float))
        and math.isfinite(item["allocation_percent"])
    ]
    concentration_index = (
        sum(value ** 2 for _, value in allocation_values)
        if allocation_values
        else None
    )
    smallest_holding = (
        min(allocation_values, key=lambda item: item[1])
        if allocation_values else (None, None)
    )

    snapshot_count = len(performance_history)
    history_sufficient = snapshot_count >= 2
    if history_sufficient:
        previous_value = performance_history[-2].get(
            "total_current_value"
        )
        latest_value = performance_history[-1].get("total_current_value")
        value_change = (
            latest_value - previous_value
            if latest_value is not None and previous_value is not None
            else None
        )
        value_change_percent = (
            value_change / previous_value * 100
            if value_change is not None and previous_value != 0
            else None
        )
        max_drawdown = analytics.get("max_drawdown")
        if max_drawdown is None:
            max_drawdown = portfolio.calculate_max_drawdown()
        historical = {
            "available": True,
            "limitation": None,
            "snapshot_count": snapshot_count,
            "snapshot_dates": [
                snapshot.get("date") for snapshot in performance_history
            ],
            "latest_snapshot_date": (
                performance_history[-1].get("date")
            ),
            "previous_snapshot_date": (
                performance_history[-2].get("date")
            ),
            "latest_previous_value_change": value_change,
            "latest_previous_value_change_percent": value_change_percent,
            "highest_recorded_value": historical_summary.get(
                "highest_value"
            ),
            "highest_recorded_value_date": historical_summary.get(
                "highest_value_date"
            ),
            "lowest_recorded_value": historical_summary.get(
                "lowest_value"
            ),
            "lowest_recorded_value_date": historical_summary.get(
                "lowest_value_date"
            ),
            "maximum_drawdown": max_drawdown,
        }
    else:
        historical = {
            "available": False,
            "limitation": INSUFFICIENT_HISTORY_MESSAGE,
            "snapshot_count": snapshot_count,
            "snapshot_dates": [
                snapshot.get("date") for snapshot in performance_history
            ],
            "latest_snapshot_date": (
                performance_history[-1].get("date")
                if performance_history else None
            ),
            "previous_snapshot_date": None,
            "latest_previous_value_change": None,
            "latest_previous_value_change_percent": None,
            "highest_recorded_value": None,
            "highest_recorded_value_date": None,
            "lowest_recorded_value": None,
            "lowest_recorded_value_date": None,
            "maximum_drawdown": None,
        }

    if unavailable_price_count:
        price_limitation = (
            f"{unavailable_price_count} holding(s) have unavailable "
            "current prices."
        )
    else:
        price_limitation = None

    return {
        "portfolio_concentration": {
            "total_portfolio_value": total_value,
            "number_of_holdings": concentration.get(
                "holding_count",
                len(positions),
            ),
            "largest_holding_symbol": concentration.get(
                "largest_holding_symbol"
            ),
            "largest_holding_percentage": concentration.get(
                "largest_holding_percent"
            ),
            "smallest_holding_symbol": (
                smallest_holding[0]
            ),
            "smallest_holding_percentage": smallest_holding[1],
            "concentration_percentage": concentration.get(
                "largest_holding_percent"
            ),
            "hhi_style_concentration_index": concentration_index,
            "allocations": [
                {
                    "symbol": symbol,
                    "market_value": item.get("current_value"),
                    "allocation_percent": item.get("allocation_percent"),
                }
                for symbol, item in sorted(allocations.items())
            ],
        },
        "holding_exposure": exposures,
        "portfolio_composition": {
            "available_classifications": [],
            "classification_message": (
                "Sector, industry, and asset-class classifications are not "
                "available in the current portfolio data."
            ),
            "holdings_by_symbol": [
                {
                    "symbol": item["symbol"],
                    "company_name": item["company_name"],
                    "market_value": item["market_value"],
                    "allocation_percent": item["allocation_percent"],
                }
                for item in exposures
            ],
        },
        "historical_risk": historical,
        "data_quality": {
            "valid_current_price_count": valid_price_count,
            "unavailable_current_price_count": unavailable_price_count,
            "historical_data_sufficient": history_sufficient,
            "snapshot_count": snapshot_count,
            "snapshot_dates_used": historical["snapshot_dates"],
            "market_data_sources": sorted(market_data_sources),
            "limitations": [
                message
                for message in (
                    price_limitation,
                    historical["limitation"],
                )
                if message
            ],
        },
    }
