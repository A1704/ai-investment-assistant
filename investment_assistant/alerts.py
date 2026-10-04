import json
import math
from dataclasses import dataclass

from investment_assistant.portfolio import get_portfolio_snapshots


@dataclass(frozen=True)
class AlertThresholds:
    portfolio_value_percent: float = 2.0
    holding_value_percent: float = 5.0
    pnl_amount: float = 500.0
    allocation_change_percentage_points: float = 5.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be greater than zero.")


DEFAULT_THRESHOLDS = AlertThresholds()
INSUFFICIENT_HISTORY_MESSAGE = (
    "Not enough historical snapshots to calculate portfolio changes yet."
)


def _snapshot_fields(snapshot):
    if isinstance(snapshot, dict):
        return snapshot
    return {
        "date": snapshot[1],
        "total_current_value": snapshot[3],
        "total_pnl": snapshot[6],
        "holding_snapshot_json": snapshot[9] if len(snapshot) > 9 else None,
    }


def _severity(magnitude, threshold):
    return "IMPORTANT" if magnitude >= threshold * 2 else "NOTICE"


def _holding_data(snapshot):
    value = snapshot.get("holding_snapshot_json")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return None
    normalized = {}
    for symbol, holding in value.items():
        if not isinstance(holding, dict):
            raise ValueError(
                f"Snapshot holding data for {symbol} must be an object."
            )
        normalized_symbol = str(
            holding.get("symbol", symbol)
        ).strip().upper()
        if not normalized_symbol:
            raise ValueError("Snapshot holding symbol cannot be empty.")
        market_value = holding.get(
            "market_value",
            holding.get("current_value"),
        )
        normalized[normalized_symbol] = {
            "symbol": normalized_symbol,
            "company_name": holding.get("company_name"),
            "quantity": holding.get("quantity"),
            "current_price": holding.get("current_price"),
            "market_value": market_value,
            "remaining_cost_basis": holding.get("remaining_cost_basis"),
            "unrealized_pnl": holding.get("unrealized_pnl"),
            "total_pnl": holding.get("total_pnl"),
            "allocation_percent": holding.get("allocation_percent"),
        }
    return normalized


def calculate_portfolio_changes(
    snapshots,
    thresholds=DEFAULT_THRESHOLDS,
):
    """Compare the two most recent saved snapshots without side effects."""
    normalized = [_snapshot_fields(item) for item in snapshots]
    normalized.sort(key=lambda item: item["date"])
    if len(normalized) < 2:
        return {
            "available": False,
            "message": INSUFFICIENT_HISTORY_MESSAGE,
            "alerts": [],
            "holding_changes": [],
            "concentration_changes": [],
        }

    previous, latest = normalized[-2:]
    previous_value = float(previous["total_current_value"])
    latest_value = float(latest["total_current_value"])
    value_change = latest_value - previous_value
    value_change_percent = (
        value_change / abs(previous_value) * 100
        if previous_value != 0
        else None
    )
    previous_pnl = float(previous["total_pnl"])
    latest_pnl = float(latest["total_pnl"])
    pnl_change = latest_pnl - previous_pnl

    report = {
        "available": True,
        "message": None,
        "latest_date": latest.get("date"),
        "previous_date": previous.get("date"),
        "portfolio_value": {
            "previous": previous_value,
            "current": latest_value,
            "change": value_change,
            "change_percent": value_change_percent,
        },
        "total_pnl": {
            "previous": previous_pnl,
            "current": latest_pnl,
            "change": pnl_change,
        },
        "holding_changes": [],
        "concentration_changes": [],
        "holding_comparison_available": False,
        "holding_comparison_message": (
            "Holding-level changes require two snapshots with holding details."
        ),
        "holding_comparison_previous_date": None,
        "holding_comparison_latest_date": None,
        "alerts": [],
    }

    if (
        value_change_percent is not None
        and abs(value_change_percent) >= thresholds.portfolio_value_percent
    ):
        report["alerts"].append({
            "severity": _severity(
                abs(value_change_percent),
                thresholds.portfolio_value_percent,
            ),
            "type": "portfolio_value",
            "threshold": thresholds.portfolio_value_percent,
            "threshold_unit": "percent",
            "message": (
                f"Portfolio value changed by ₹{value_change:,.2f} "
                f"({value_change_percent:+.2f}%) between snapshots."
            ),
        })

    if abs(pnl_change) >= thresholds.pnl_amount:
        report["alerts"].append({
            "severity": _severity(
                abs(pnl_change),
                thresholds.pnl_amount,
            ),
            "type": "total_pnl",
            "threshold": thresholds.pnl_amount,
            "threshold_unit": "currency",
            "message": (
                f"Total P&L changed by ₹{pnl_change:,.2f} "
                "between snapshots."
            ),
        })

    detailed_snapshots = [
        (item, _holding_data(item))
        for item in normalized
    ]
    detailed_snapshots = [
        (item, holdings)
        for item, holdings in detailed_snapshots
        if holdings is not None
    ]
    if len(detailed_snapshots) >= 2:
        previous_detailed, previous_holdings = detailed_snapshots[-2]
        latest_detailed, current_holdings = detailed_snapshots[-1]
        report["holding_comparison_available"] = True
        report["holding_comparison_message"] = None
        report["holding_comparison_previous_date"] = (
            previous_detailed.get("date")
        )
        report["holding_comparison_latest_date"] = (
            latest_detailed.get("date")
        )
        symbols = sorted(set(previous_holdings) | set(current_holdings))

        for symbol in symbols:
            old_exists = symbol in previous_holdings
            current_exists = symbol in current_holdings
            old = previous_holdings.get(symbol, {})
            current = current_holdings.get(symbol, {})
            status = (
                "added" if not old_exists
                else "removed" if not current_exists
                else "unchanged"
            )
            old_value = old.get("market_value")
            current_value = current.get("market_value")
            if not old_exists and current_value is not None:
                old_value = 0.0
            if not current_exists and old_value is not None:
                current_value = 0.0
            old_value = float(old_value) if old_value is not None else None
            current_value = (
                float(current_value) if current_value is not None else None
            )
            value_delta = (
                current_value - old_value
                if old_value is not None and current_value is not None
                else None
            )
            value_percent = (
                value_delta / abs(old_value) * 100
                if old_value not in (None, 0) and value_delta is not None
                else None
            )
            old_pnl = old.get("unrealized_pnl")
            current_pnl = current.get("unrealized_pnl")
            if not old_exists and current_pnl is not None:
                old_pnl = 0.0
            if not current_exists and old_pnl is not None:
                current_pnl = 0.0
            old_pnl = float(old_pnl) if old_pnl is not None else None
            current_pnl = (
                float(current_pnl) if current_pnl is not None else None
            )
            pnl_delta = (
                current_pnl - old_pnl
                if old_pnl is not None and current_pnl is not None
                else None
            )
            old_total_pnl = old.get("total_pnl")
            current_total_pnl = current.get("total_pnl")
            if not old_exists and current_total_pnl is not None:
                old_total_pnl = 0.0
            if not current_exists and old_total_pnl is not None:
                current_total_pnl = 0.0
            old_total_pnl = (
                float(old_total_pnl) if old_total_pnl is not None else None
            )
            current_total_pnl = (
                float(current_total_pnl)
                if current_total_pnl is not None else None
            )
            total_pnl_delta = (
                current_total_pnl - old_total_pnl
                if old_total_pnl is not None
                and current_total_pnl is not None
                else None
            )
            old_allocation = old.get("allocation_percent")
            current_allocation = current.get("allocation_percent")
            if not old_exists and current_allocation is not None:
                old_allocation = 0.0
            if not current_exists and old_allocation is not None:
                current_allocation = 0.0
            old_allocation = (
                float(old_allocation)
                if old_allocation is not None else None
            )
            current_allocation = (
                float(current_allocation)
                if current_allocation is not None else None
            )
            allocation_delta = (
                current_allocation - old_allocation
                if old_allocation is not None
                and current_allocation is not None
                else None
            )
            old_quantity = old.get("quantity")
            current_quantity = current.get("quantity")
            old_price = old.get("current_price")
            current_price = current.get("current_price")
            if not old_exists and current_quantity is not None:
                old_quantity = 0.0
            if not current_exists and old_quantity is not None:
                current_quantity = 0.0
            quantity_delta = (
                float(current_quantity) - float(old_quantity)
                if old_quantity is not None and current_quantity is not None
                else None
            )
            price_delta = (
                float(current_price) - float(old_price)
                if old_price is not None and current_price is not None
                else None
            )
            numeric_deltas = (
                value_delta,
                pnl_delta,
                total_pnl_delta,
                allocation_delta,
                quantity_delta,
                price_delta,
            )
            if status == "unchanged" and any(
                delta is not None and delta != 0
                for delta in numeric_deltas
            ):
                status = "changed"
            change = {
                "symbol": symbol,
                "company_name": (
                    current.get("company_name")
                    or old.get("company_name")
                    or symbol
                ),
                "status": status,
                "previous_quantity": old_quantity,
                "current_quantity": current_quantity,
                "quantity_change": (
                    quantity_delta
                ),
                "previous_current_price": old_price,
                "current_current_price": current_price,
                "current_price_change": price_delta,
                "previous_value": old_value,
                "current_value": current_value,
                "value_change": value_delta,
                "value_change_percent": value_percent,
                "previous_market_value": old_value,
                "current_market_value": current_value,
                "market_value_change": value_delta,
                "market_value_change_percent": value_percent,
                "previous_unrealized_pnl": old_pnl,
                "current_unrealized_pnl": current_pnl,
                "unrealized_pnl_change": pnl_delta,
                "previous_total_pnl": old_total_pnl,
                "current_total_pnl": current_total_pnl,
                "total_pnl_change": total_pnl_delta,
                "previous_allocation_percent": old_allocation,
                "current_allocation_percent": current_allocation,
                "allocation_change_percentage_points": allocation_delta,
            }
            report["holding_changes"].append(change)

            if status == "added":
                report["alerts"].append({
                    "severity": "INFO",
                    "type": "holding_added",
                    "symbol": symbol,
                    "message": f"{symbol} appears in the latest snapshot.",
                })
            elif status == "removed":
                report["alerts"].append({
                    "severity": "INFO",
                    "type": "holding_removed",
                    "symbol": symbol,
                    "message": f"{symbol} does not appear in the latest snapshot.",
                })

            if (
                status in ("unchanged", "changed")
                and
                value_percent is not None
                and abs(value_percent) >= thresholds.holding_value_percent
            ):
                report["alerts"].append({
                    "severity": _severity(
                        abs(value_percent),
                        thresholds.holding_value_percent,
                    ),
                    "type": "holding_value",
                    "symbol": symbol,
                    "threshold": thresholds.holding_value_percent,
                    "threshold_unit": "percent",
                    "message": (
                        f"{symbol} value changed by ₹{value_delta:,.2f} "
                        f"({value_percent:+.2f}%)."
                    ),
                })

            if (
                status in ("unchanged", "changed")
                and pnl_delta is not None
                and abs(pnl_delta) >= thresholds.pnl_amount
            ):
                report["alerts"].append({
                    "severity": _severity(
                        abs(pnl_delta),
                        thresholds.pnl_amount,
                    ),
                    "type": "holding_pnl",
                    "symbol": symbol,
                    "threshold": thresholds.pnl_amount,
                    "threshold_unit": "currency",
                    "message": (
                        f"{symbol} unrealized P&L changed by "
                        f"₹{pnl_delta:,.2f}."
                    ),
                })

            if (
                status in ("unchanged", "changed")
                and allocation_delta is not None
                and
                abs(allocation_delta)
                >= thresholds.allocation_change_percentage_points
            ):
                concentration = {
                    "symbol": symbol,
                    "previous_allocation_percent": old_allocation,
                    "current_allocation_percent": current_allocation,
                    "change_percentage_points": allocation_delta,
                }
                report["concentration_changes"].append(concentration)
                report["alerts"].append({
                    "severity": _severity(
                        abs(allocation_delta),
                        thresholds.allocation_change_percentage_points,
                    ),
                    "type": "concentration",
                    "symbol": symbol,
                    "threshold": (
                        thresholds.allocation_change_percentage_points
                    ),
                    "threshold_unit": "percentage_points",
                    "message": (
                        f"{symbol} portfolio allocation changed by "
                        f"{allocation_delta:+.2f} percentage points."
                    ),
                })

    return report


def get_portfolio_change_report(thresholds=DEFAULT_THRESHOLDS):
    """Load saved snapshots and return their deterministic comparison."""
    return calculate_portfolio_changes(
        get_portfolio_snapshots(),
        thresholds=thresholds,
    )
