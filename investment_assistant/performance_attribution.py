import math

from investment_assistant import alerts, portfolio


INSUFFICIENT_HISTORY_MESSAGE = (
    "Performance attribution requires at least two portfolio snapshots."
)
INSUFFICIENT_DETAIL_MESSAGE = (
    "Detailed holding-level attribution requires two snapshots containing "
    "holding details."
)
PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE = (
    "Price/transaction attribution unavailable with the currently stored "
    "snapshot data."
)


def _snapshot_value(snapshot):
    if isinstance(snapshot, dict):
        return snapshot
    return {
        "date": snapshot[1],
        "total_current_value": snapshot[3],
        "total_pnl": snapshot[6],
        "holding_snapshot_json": snapshot[9] if len(snapshot) > 9 else None,
    }


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _transactions_between(transactions, previous_date, latest_date):
    if not previous_date or not latest_date:
        return []
    return [
        {
            "symbol": str(row[1]).strip().upper(),
            "company_name": row[2],
            "transaction_type": str(row[3]).upper(),
            "quantity": row[4],
            "price": row[5],
            "transaction_date": row[6],
        }
        for row in transactions
        if previous_date < str(row[6]) <= latest_date
    ]


def _decompose_observed_change(holding):
    values = (
        holding.get("previous_quantity"),
        holding.get("latest_quantity"),
        holding.get("previous_current_price"),
        holding.get("latest_current_price"),
        holding.get("market_value_change"),
    )
    if not all(_finite_number(value) for value in values):
        return {
            "available": False,
            "price_related_movement": None,
            "quantity_related_movement": None,
            "other_unexplained_component": None,
            "message": PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE,
        }

    previous_quantity, latest_quantity, previous_price, latest_price, value_change = values
    price_component = (
        (latest_price - previous_price)
        * (previous_quantity + latest_quantity)
        / 2
    )
    quantity_component = (
        (latest_quantity - previous_quantity)
        * (previous_price + latest_price)
        / 2
    )
    other_component = value_change - price_component - quantity_component
    return {
        "available": True,
        "price_related_movement": price_component,
        "quantity_related_movement": quantity_component,
        "other_unexplained_component": other_component,
        "message": (
            "Endpoint-based arithmetic decomposition only; it does not "
            "establish causation or identify specific transaction effects."
        ),
    }


def generate_performance_attribution(
    *,
    snapshots=None,
    transactions=None,
):
    """Report observed snapshot movement and detailed holding contributions."""
    if snapshots is None:
        snapshots = portfolio.get_portfolio_snapshots()
    normalized = sorted(
        (_snapshot_value(item) for item in snapshots),
        key=lambda item: item["date"],
    )
    if transactions is None:
        transactions = portfolio.get_transactions()

    changes = alerts.calculate_portfolio_changes(snapshots)
    if not changes.get("available"):
        return {
            "available": False,
            "reason": INSUFFICIENT_HISTORY_MESSAGE,
            "portfolio_movement": None,
            "holding_attribution": {
                "available": False,
                "reason": INSUFFICIENT_DETAIL_MESSAGE,
                "holdings": [],
            },
            "summary": None,
            "price_transaction_attribution": {
                "available": False,
                "reason": PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE,
                "transactions_between_snapshots": [],
                "holdings": [],
            },
            "limitations": [INSUFFICIENT_HISTORY_MESSAGE],
        }

    previous, latest = normalized[-2:]
    portfolio_value = changes["portfolio_value"]
    total_pnl = changes["total_pnl"]
    portfolio_movement = {
        "previous_date": changes["previous_date"],
        "latest_date": changes["latest_date"],
        "previous_value": portfolio_value["previous"],
        "latest_value": portfolio_value["current"],
        "value_change": portfolio_value["change"],
        "value_change_percent": portfolio_value["change_percent"],
        "previous_total_pnl": total_pnl["previous"],
        "latest_total_pnl": total_pnl["current"],
        "total_pnl_change": total_pnl["change"],
    }

    detailed_dates_match = (
        changes.get("holding_comparison_available")
        and changes.get("holding_comparison_previous_date")
        == previous.get("date")
        and changes.get("holding_comparison_latest_date")
        == latest.get("date")
    )
    limitations = []
    if not detailed_dates_match:
        holding_attribution = {
            "available": False,
            "reason": INSUFFICIENT_DETAIL_MESSAGE,
            "previous_date": None,
            "latest_date": None,
            "holdings": [],
        }
        summary = {
            "total_portfolio_value_change": portfolio_value["change"],
            "holding_market_value_change_sum": None,
            "reconciliation_difference": None,
            "reconciles_to_portfolio_change": None,
            "largest_positive_contributor": None,
            "largest_negative_contributor": None,
            "increased_value_holdings": [],
            "decreased_value_holdings": [],
            "unchanged_value_holdings": [],
            "added_holdings": [],
            "removed_holdings": [],
        }
        limitations.append(INSUFFICIENT_DETAIL_MESSAGE)
        holding_rows = []
    else:
        holding_rows = []
        for item in changes["holding_changes"]:
            holding = {
                "symbol": item["symbol"],
                "company_name": item.get("company_name"),
                "status": item["status"],
                "previous_market_value": item.get("previous_market_value"),
                "latest_market_value": item.get("current_market_value"),
                "market_value_change": item.get("market_value_change"),
                "market_value_change_percent": item.get(
                    "market_value_change_percent"
                ),
                "previous_quantity": item.get("previous_quantity"),
                "latest_quantity": item.get("current_quantity"),
                "quantity_change": item.get("quantity_change"),
                "previous_current_price": item.get(
                    "previous_current_price"
                ),
                "latest_current_price": item.get("current_current_price"),
                "price_change": item.get("current_price_change"),
                "previous_allocation_percent": item.get(
                    "previous_allocation_percent"
                ),
                "latest_allocation_percent": item.get(
                    "current_allocation_percent"
                ),
                "allocation_change_percentage_points": item.get(
                    "allocation_change_percentage_points"
                ),
                "contribution_to_portfolio_change": item.get(
                    "market_value_change"
                ),
                "contribution_to_portfolio_change_percent": (
                    item["market_value_change"]
                    / portfolio_value["change"] * 100
                    if item.get("market_value_change") is not None
                    and portfolio_value["change"] != 0
                    else None
                ),
            }
            holding_rows.append(holding)

        deltas = [
            item["market_value_change"]
            for item in holding_rows
            if item["market_value_change"] is not None
        ]
        complete_deltas = len(deltas) == len(holding_rows)
        change_sum = sum(deltas) if complete_deltas else None
        reconciliation = (
            portfolio_value["change"] - change_sum
            if change_sum is not None
            else None
        )
        summary = {
            "total_portfolio_value_change": portfolio_value["change"],
            "holding_market_value_change_sum": change_sum,
            "reconciliation_difference": reconciliation,
            "reconciles_to_portfolio_change": (
                math.isclose(
                    change_sum,
                    portfolio_value["change"],
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                )
                if change_sum is not None
                else None
            ),
            "largest_positive_contributor": max(
                (
                    item for item in holding_rows
                    if item["market_value_change"] is not None
                    and item["market_value_change"] > 0
                ),
                key=lambda item: item["market_value_change"],
                default=None,
            ),
            "largest_negative_contributor": min(
                (
                    item for item in holding_rows
                    if item["market_value_change"] is not None
                    and item["market_value_change"] < 0
                ),
                key=lambda item: item["market_value_change"],
                default=None,
            ),
            "increased_value_holdings": [
                item["symbol"] for item in holding_rows
                if item["market_value_change"] is not None
                and item["market_value_change"] > 0
            ],
            "decreased_value_holdings": [
                item["symbol"] for item in holding_rows
                if item["market_value_change"] is not None
                and item["market_value_change"] < 0
            ],
            "unchanged_value_holdings": [
                item["symbol"] for item in holding_rows
                if item["market_value_change"] == 0
            ],
            "added_holdings": [
                item["symbol"] for item in holding_rows
                if item["status"] == "added"
            ],
            "removed_holdings": [
                item["symbol"] for item in holding_rows
                if item["status"] == "removed"
            ],
        }
        holding_attribution = {
            "available": True,
            "reason": None,
            "previous_date": changes["holding_comparison_previous_date"],
            "latest_date": changes["holding_comparison_latest_date"],
            "holdings": holding_rows,
        }

    transaction_rows = _transactions_between(
        transactions,
        previous.get("date"),
        latest.get("date"),
    )
    decompositions = []
    for item in holding_rows:
        decomposition = _decompose_observed_change(item)
        decompositions.append({
            "symbol": item["symbol"],
            **decomposition,
        })
    price_available = bool(decompositions) and all(
        item["available"] for item in decompositions
    )
    price_transaction = {
        "available": price_available,
        "reason": (
            None
            if price_available
            else PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE
        ),
        "method": (
            "Symmetric endpoint arithmetic: price change times average "
            "quantity; quantity change times average price. Components are observed "
            "decomposition, not causal attribution."
            if price_available
            else None
        ),
        "transactions_between_snapshots": transaction_rows,
        "holdings": decompositions,
    }
    if not price_available:
        limitations.append(PRICE_ATTRIBUTION_UNAVAILABLE_MESSAGE)

    if (
        holding_attribution["available"]
        and summary["reconciliation_difference"] is not None
        and not summary["reconciles_to_portfolio_change"]
    ):
        limitations.append(
            "Detailed holding-value changes do not fully reconcile to the "
            "aggregate portfolio value change; the difference is reported "
            "without assigning a cause."
        )

    return {
        "available": True,
        "reason": None,
        "portfolio_movement": portfolio_movement,
        "holding_attribution": holding_attribution,
        "summary": summary,
        "price_transaction_attribution": price_transaction,
        "limitations": limitations,
    }
