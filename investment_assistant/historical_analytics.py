from datetime import date, timedelta
import json
import math

from investment_assistant import portfolio


INSUFFICIENT_TREND_MESSAGE = (
    "Insufficient historical data for trend analysis."
)
INSUFFICIENT_DRAWDOWN_MESSAGE = (
    "Insufficient historical data for drawdown analysis."
)
EXACT_DATE_UNAVAILABLE_MESSAGE = (
    "Unavailable — no snapshot exists for the requested comparison date."
)


def _snapshot_fields(snapshot):
    if isinstance(snapshot, dict):
        return snapshot
    return {
        "date": snapshot[1],
        "total_invested": snapshot[2],
        "total_current_value": snapshot[3],
        "total_realized_pnl": snapshot[4],
        "total_unrealized_pnl": snapshot[5],
        "total_pnl": snapshot[6],
        "total_return_percent": snapshot[7],
        "holding_snapshot_json": snapshot[9] if len(snapshot) > 9 else None,
    }


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _change(previous, latest):
    if not _is_number(previous) or not _is_number(latest):
        return None, None
    absolute_change = latest - previous
    percentage_change = (
        absolute_change / previous * 100
        if previous != 0
        else None
    )
    return absolute_change, percentage_change


def _period_comparison(latest, history, days):
    latest_date = date.fromisoformat(latest["date"])
    comparison_date = (latest_date - timedelta(days=days)).isoformat()
    previous = next(
        (snapshot for snapshot in history if snapshot["date"] == comparison_date),
        None,
    )
    result = {
        "available": False,
        "days": days,
        "comparison_date": comparison_date,
        "latest_date": latest["date"],
        "previous_value": None,
        "latest_value": latest.get("total_current_value"),
        "value_change": None,
        "value_change_percent": None,
        "message": EXACT_DATE_UNAVAILABLE_MESSAGE,
    }
    if previous is None:
        return result

    absolute_change, percentage_change = _change(
        previous.get("total_current_value"),
        latest.get("total_current_value"),
    )
    result.update({
        "available": absolute_change is not None,
        "previous_value": previous.get("total_current_value"),
        "value_change": absolute_change,
        "value_change_percent": percentage_change,
        "message": None if absolute_change is not None else (
            "Unavailable — portfolio values are missing for the requested comparison."
        ),
    })
    return result


def _has_holding_detail(snapshot):
    value = snapshot.get("holding_snapshot_json")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    return isinstance(value, dict)


def generate_historical_analytics(
    *,
    history=None,
    snapshots=None,
    historical_summary=None,
    max_drawdown=None,
):
    """Summarize only portfolio snapshots actually stored by the application."""
    if history is None:
        history = portfolio.get_portfolio_performance_history()
    ordered_history = sorted(
        (dict(item) for item in history),
        key=lambda item: item["date"],
    )
    if snapshots is None:
        snapshots = portfolio.get_portfolio_snapshots()
    ordered_snapshots = sorted(
        (_snapshot_fields(item) for item in snapshots),
        key=lambda item: item["date"],
    )
    if historical_summary is None:
        historical_summary = portfolio.get_historical_performance_summary(
            ordered_history
        )

    count = len(ordered_history)
    trend_available = count >= 2
    if max_drawdown is None and trend_available:
        max_drawdown = portfolio.calculate_max_drawdown(ordered_history)
    first = ordered_history[0] if ordered_history else None
    latest = ordered_history[-1] if ordered_history else None

    first_change = None
    if trend_available:
        first_change, first_change_percent = _change(
            first.get("total_current_value"),
            latest.get("total_current_value"),
        )
    else:
        first_change_percent = None

    value_series = [
        snapshot["total_current_value"]
        for snapshot in ordered_history
        if _is_number(snapshot.get("total_current_value"))
    ]
    pnl_values = [
        snapshot["total_pnl"]
        for snapshot in ordered_history
        if _is_number(snapshot.get("total_pnl"))
    ]
    unrealized_return_values = [
        snapshot["total_return_percent"]
        for snapshot in ordered_history
        if _is_number(snapshot.get("total_return_percent"))
    ]
    realized_values = [
        snapshot["total_realized_pnl"]
        for snapshot in ordered_history
        if _is_number(snapshot.get("total_realized_pnl"))
    ]
    unrealized_values = [
        snapshot["total_unrealized_pnl"]
        for snapshot in ordered_history
        if _is_number(snapshot.get("total_unrealized_pnl"))
    ]

    if not trend_available:
        trend = "Insufficient history"
    else:
        changes = [
            current - previous
            for previous, current in zip(value_series, value_series[1:])
        ]
        if changes and all(change >= 0 for change in changes) and any(
            change > 0 for change in changes
        ):
            trend = "Increasing over available history"
        elif changes and all(change <= 0 for change in changes) and any(
            change < 0 for change in changes
        ):
            trend = "Decreasing over available history"
        else:
            trend = "Mixed / fluctuating"

    if trend_available:
        snapshot_change_history = portfolio.calculate_snapshot_changes(
            ordered_history
        )
        latest_vs_previous = (
            snapshot_change_history[-1]
            if snapshot_change_history
            else {}
        )
        previous_comparison = {
            "available": True,
            "previous_date": ordered_history[-2]["date"],
            "latest_date": latest["date"],
            "previous_value": ordered_history[-2].get(
                "total_current_value"
            ),
            "latest_value": latest.get("total_current_value"),
            "value_change": latest_vs_previous.get("value_change"),
            "value_change_percent": latest_vs_previous.get(
                "value_change_percent"
            ),
        }
        latest_first_comparison = {
            "available": first_change is not None,
            "previous_date": first["date"],
            "latest_date": latest["date"],
            "previous_value": first.get("total_current_value"),
            "latest_value": latest.get("total_current_value"),
            "value_change": first_change,
            "value_change_percent": first_change_percent,
        }
        comparison_periods = {
            "latest_vs_previous": previous_comparison,
            "latest_vs_first": latest_first_comparison,
            "latest_vs_7_days": _period_comparison(
                latest, ordered_history, 7
            ),
            "latest_vs_30_days": _period_comparison(
                latest, ordered_history, 30
            ),
        }
    else:
        unavailable_comparison = {
            "available": False,
            "message": INSUFFICIENT_TREND_MESSAGE,
        }
        comparison_periods = {
            "latest_vs_previous": unavailable_comparison,
            "latest_vs_first": unavailable_comparison,
            "latest_vs_7_days": {
                **unavailable_comparison,
                "days": 7,
                "message": EXACT_DATE_UNAVAILABLE_MESSAGE,
            },
            "latest_vs_30_days": {
                **unavailable_comparison,
                "days": 30,
                "message": EXACT_DATE_UNAVAILABLE_MESSAGE,
            },
        }

    drawdown_available = count >= 2
    drawdown = None
    if drawdown_available:
        required_drawdown_fields = (
            "max_drawdown_amount",
            "max_drawdown_percent",
            "peak_date",
            "trough_date",
        )
        if (
            not isinstance(max_drawdown, dict)
            or any(key not in max_drawdown for key in required_drawdown_fields)
        ):
            max_drawdown = portfolio.calculate_max_drawdown(ordered_history)
        drawdown = dict(max_drawdown or {})
        peak_date = drawdown.get("peak_date")
        trough_date = drawdown.get("trough_date")
        drawdown["peak_value"] = next(
            (
                snapshot["total_current_value"]
                for snapshot in ordered_history
                if snapshot["date"] == peak_date
            ),
            None,
        )
        drawdown["trough_value"] = next(
            (
                snapshot["total_current_value"]
                for snapshot in ordered_history
                if snapshot["date"] == trough_date
            ),
            None,
        )
        drawdown["available"] = True
        drawdown["message"] = None
    else:
        drawdown = {
            "available": False,
            "max_drawdown_amount": None,
            "max_drawdown_percent": None,
            "peak_date": None,
            "trough_date": None,
            "peak_value": None,
            "trough_value": None,
            "message": INSUFFICIENT_DRAWDOWN_MESSAGE,
        }

    detailed_count = sum(
        1 for snapshot in ordered_snapshots if _has_holding_detail(snapshot)
    )
    aggregate_only_count = len(ordered_snapshots) - detailed_count
    data_limitations = []
    if aggregate_only_count:
        data_limitations.append(
            f"{aggregate_only_count} snapshot(s) contain aggregate data only; "
            "holding-level history is unavailable for those dates."
        )
    if detailed_count == 0 and ordered_snapshots:
        data_limitations.append(
            "No stored snapshots contain detailed holding-level data."
        )
    if not trend_available:
        data_limitations.append(INSUFFICIENT_TREND_MESSAGE)
    if not drawdown_available:
        data_limitations.append(INSUFFICIENT_DRAWDOWN_MESSAGE)

    series = [
        {
            "date": item.get("date"),
            "total_invested": item.get("total_invested"),
            "total_current_value": item.get("total_current_value"),
            "total_realized_pnl": item.get("total_realized_pnl"),
            "total_unrealized_pnl": item.get("total_unrealized_pnl"),
            "total_pnl": item.get("total_pnl"),
            "total_return_percent": item.get("total_return_percent"),
        }
        for item in ordered_history
    ]

    return {
        "history": series,
        "trend_metrics": {
            "available": trend_available,
            "snapshot_count": count,
            "first_snapshot_date": first.get("date") if first else None,
            "latest_snapshot_date": latest.get("date") if latest else None,
            "first_recorded_value": (
                first.get("total_current_value") if first else None
            ),
            "latest_portfolio_value": (
                latest.get("total_current_value") if latest else None
            ),
            "first_to_latest_change": first_change,
            "first_to_latest_change_percent": first_change_percent,
            "highest_recorded_value": historical_summary.get(
                "highest_value"
            ) if count else None,
            "highest_recorded_value_date": historical_summary.get(
                "highest_value_date"
            ) if count else None,
            "lowest_recorded_value": historical_summary.get(
                "lowest_value"
            ) if count else None,
            "lowest_recorded_value_date": historical_summary.get(
                "lowest_value_date"
            ) if count else None,
            "highest_total_pnl": max(pnl_values) if pnl_values else None,
            "lowest_total_pnl": min(pnl_values) if pnl_values else None,
            "highest_unrealized_return_percent": (
                max(unrealized_return_values)
                if unrealized_return_values else None
            ),
            "lowest_unrealized_return_percent": (
                min(unrealized_return_values)
                if unrealized_return_values else None
            ),
            "trend": trend,
        },
        "period_comparisons": comparison_periods,
        "pnl_trend": {
            "total_pnl": pnl_values,
            "unrealized_pnl": unrealized_values,
            "realized_pnl": realized_values,
            "highest_total_pnl": max(pnl_values) if pnl_values else None,
            "lowest_total_pnl": min(pnl_values) if pnl_values else None,
            "latest_total_pnl_change": (
                latest.get("total_pnl") - ordered_history[-2].get("total_pnl")
                if trend_available
                and _is_number(latest.get("total_pnl"))
                and _is_number(ordered_history[-2].get("total_pnl"))
                else None
            ),
            "latest_unrealized_pnl_change": (
                latest.get("total_unrealized_pnl")
                - ordered_history[-2].get("total_unrealized_pnl")
                if trend_available
                and _is_number(latest.get("total_unrealized_pnl"))
                and _is_number(ordered_history[-2].get("total_unrealized_pnl"))
                else None
            ),
            "latest_realized_pnl_change": (
                latest.get("total_realized_pnl")
                - ordered_history[-2].get("total_realized_pnl")
                if trend_available
                and _is_number(latest.get("total_realized_pnl"))
                and _is_number(ordered_history[-2].get("total_realized_pnl"))
                else None
            ),
        },
        "drawdown": drawdown,
        "data_quality": {
            "snapshot_count": len(ordered_snapshots),
            "history_snapshot_count": count,
            "date_range_start": (
                ordered_history[0].get("date") if first else None
            ),
            "date_range_end": (
                ordered_history[-1].get("date") if latest else None
            ),
            "trend_analysis_sufficient": trend_available,
            "drawdown_analysis_sufficient": drawdown_available,
            "detailed_snapshot_count": detailed_count,
            "aggregate_only_snapshot_count": aggregate_only_count,
            "detailed_holding_history_available": detailed_count > 0,
            "limitations": data_limitations,
        },
    }
