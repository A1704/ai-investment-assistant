"""Read-only, deterministic checks of portfolio data availability."""

from datetime import date, datetime, timezone
import json
import math
from numbers import Real

from investment_assistant import portfolio
from investment_assistant.goals_intelligence import (
    get_portfolio_benchmarks,
    get_benchmark_observations,
    get_portfolio_goals,
)


MARKET_DATA_AGING_AFTER_HOURS = 24
MARKET_DATA_STALE_AFTER_HOURS = 72
VALUE_CONSISTENCY_TOLERANCE = 0.01
_DETAIL_UNAVAILABLE = (
    "Holding-level attribution is unavailable because the required snapshots "
    "do not both contain detailed holding data."
)


def _number(value):
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _snapshot(snapshot):
    if isinstance(snapshot, dict):
        result = dict(snapshot)
        if "date" not in result and "snapshot_date" in result:
            result["date"] = result["snapshot_date"]
        return result
    return {
        "date": snapshot[1],
        "total_current_value": snapshot[3],
        "total_pnl": snapshot[6],
        "holding_snapshot_json": snapshot[9] if len(snapshot) > 9 else None,
    }


def _parse_details(snapshot):
    details = snapshot.get("holding_snapshot_json")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except (TypeError, ValueError):
            return None, "Malformed holding-level snapshot JSON."
    if details is None:
        return None, None
    if not isinstance(details, dict):
        return None, "Holding-level snapshot data is not a JSON object."
    return details, None


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _freshness(position, now):
    market_timestamp = position.get("market_timestamp")
    retrieved_at = position.get("retrieved_at")
    parsed_market = _parse_timestamp(market_timestamp)
    parsed_retrieved = _parse_timestamp(retrieved_at)
    if parsed_market is None:
        return {
            "category": "UNKNOWN",
            "market_timestamp": market_timestamp,
            "retrieved_at": retrieved_at,
            "market_age_hours": None,
            "retrieval_age_hours": (
                max((now - parsed_retrieved).total_seconds(), 0) / 3600
                if parsed_retrieved
                else None
            ),
            "message": "Market timestamp is unavailable or invalid.",
        }

    age_hours = (now - parsed_market).total_seconds() / 3600
    if age_hours < 0:
        return {
            "category": "UNKNOWN",
            "market_timestamp": market_timestamp,
            "retrieved_at": retrieved_at,
            "market_age_hours": age_hours,
            "retrieval_age_hours": (
                max((now - parsed_retrieved).total_seconds(), 0) / 3600
                if parsed_retrieved
                else None
            ),
            "message": "Market timestamp is in the future.",
        }
    if age_hours <= MARKET_DATA_AGING_AFTER_HOURS:
        category = "FRESH"
    elif age_hours <= MARKET_DATA_STALE_AFTER_HOURS:
        category = "AGING"
    else:
        category = "STALE"
    return {
        "category": category,
        "market_timestamp": market_timestamp,
        "retrieved_at": retrieved_at,
        "market_age_hours": age_hours,
        "retrieval_age_hours": (
            max((now - parsed_retrieved).total_seconds(), 0) / 3600
            if parsed_retrieved
            else None
        ),
        "message": (
            f"Market timestamp age exceeds {MARKET_DATA_STALE_AFTER_HOURS} "
            "hours."
            if category == "STALE"
            else None
        ),
    }


def _issue(category, code, severity, message, *, affected=None, blocks=False, next_action=None):
    return {
        "category": category,
        "code": code,
        "severity": severity,
        "message": message,
        "affected_items": list(affected or []),
        "blocks_calculation": bool(blocks),
        "next_action": next_action,
    }


def _category(status, summary, details=None):
    return {
        "status": status,
        "summary": summary,
        "details": details or [],
    }


def _holding_snapshot_summary(snapshots):
    dated = []
    malformed = []
    for snapshot in snapshots:
        details, error = _parse_details(snapshot)
        if error:
            malformed.append(snapshot.get("date"))
        dated.append({
            "date": snapshot.get("date"),
            "detail_status": (
                "DETAILED" if details is not None
                else "INVALID" if error
                else "AGGREGATE_ONLY"
            ),
        })
    return dated, malformed


def _date_gaps(snapshots):
    dates = []
    for item in snapshots:
        try:
            dates.append(date.fromisoformat(item["date"]))
        except (KeyError, TypeError, ValueError):
            continue
    dates = sorted(set(dates))
    gaps = []
    for previous, current in zip(dates, dates[1:]):
        intervening = (current - previous).days - 1
        if intervening > 0:
            gaps.append({
                "after": previous.isoformat(),
                "before": current.isoformat(),
                "unrecorded_calendar_days": intervening,
                "interpretation": (
                    "No snapshot recorded on intervening dates; snapshot "
                    "cadence is not assumed."
                ),
            })
    return gaps


def _status_for_historical(metric):
    if metric:
        return "AVAILABLE"
    return "UNAVAILABLE"


def generate_data_quality_report(
    *,
    portfolio_data=None,
    snapshots=None,
    historical_report=None,
    attribution_report=None,
    risk_report=None,
    goals_report=None,
    goals=None,
    benchmarks=None,
    observations_by_benchmark=None,
    news_by_symbol=None,
    news_errors=None,
    market_data_error=None,
    now=None,
):
    """Inspect supplied/current application data without changing any records."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if portfolio_data is None:
        try:
            portfolio_data = portfolio.calculate_portfolio_valuation()
        except RuntimeError as error:
            market_data_error = str(error)
            portfolio_data = {
                "positions": {},
                "total_current_value": None,
                "total_invested": None,
                "total_pnl": None,
            }
    portfolio_data = portfolio_data or {}
    positions = portfolio_data.get("positions") or {}
    company_names = {}
    for row in portfolio.get_opening_positions():
        company_names[row[1].strip().upper()] = row[2]
    for row in portfolio.get_transactions():
        company_names[row[1].strip().upper()] = row[2]
    issues = []

    portfolio_findings = []
    invalid_quantity = []
    missing_quantity = []
    missing_cost = []
    invalid_cost = []
    missing_company = []
    missing_price = []
    missing_value = []
    inconsistent = []
    for symbol, position in positions.items():
        normalized_symbol = str(symbol).strip().upper()
        company_name = (
            position.get("company_name")
            or company_names.get(normalized_symbol)
        )
        quantity = position.get("quantity")
        cost_basis = position.get(
            "remaining_cost_basis",
            position.get("invested_amount"),
        )
        if quantity is None:
            missing_quantity.append(symbol)
        elif not _number(quantity) or quantity < 0:
            invalid_quantity.append(symbol)
        if cost_basis is None:
            missing_cost.append(symbol)
        elif not _number(cost_basis) or cost_basis < 0:
            invalid_cost.append(symbol)
        if not isinstance(company_name, str) or not company_name.strip():
            missing_company.append(symbol)
        current_holding = _number(quantity) and quantity > 0
        if current_holding and (
            not _number(position.get("current_price"))
            or position.get("current_price") < 0
        ):
            missing_price.append(symbol)
        if current_holding and not _number(position.get("current_value")):
            missing_value.append(symbol)
        if (
            _number(quantity)
            and _number(position.get("current_price"))
            and _number(position.get("current_value"))
            and abs(
                quantity * position["current_price"]
                - position["current_value"]
            ) > VALUE_CONSISTENCY_TOLERANCE
        ):
            inconsistent.append(symbol)
        if (
            _number(position.get("current_value"))
            and _number(cost_basis)
            and _number(position.get("unrealized_pnl"))
            and abs(
                position["current_value"]
                - cost_basis
                - position["unrealized_pnl"]
            ) > VALUE_CONSISTENCY_TOLERANCE
        ):
            inconsistent.append(symbol)

    valuation_value = portfolio_data.get("total_current_value")
    valuation_available = _number(valuation_value)
    total_pnl = portfolio_data.get("total_pnl")
    realized_pnl = portfolio_data.get("total_realized_pnl")
    unrealized_pnl = portfolio_data.get("total_unrealized_pnl")
    aggregate_pnl_inconsistent = (
        all(_number(value) for value in (
            total_pnl,
            realized_pnl,
            unrealized_pnl,
        ))
        and abs(total_pnl - realized_pnl - unrealized_pnl)
        > VALUE_CONSISTENCY_TOLERANCE
    )
    if not valuation_available:
        issues.append(_issue(
            "portfolio",
            "PORTFOLIO_VALUATION_UNAVAILABLE",
            "CRITICAL",
            market_data_error
            or "Portfolio valuation is unavailable.",
            affected=list(positions),
            blocks=True,
            next_action="Resolve missing valuation inputs before relying on current portfolio totals.",
        ))
    for symbols, code, severity, message, blocks in (
        (missing_quantity, "MISSING_QUANTITY", "CRITICAL", "Quantity is missing for one or more positions.", True),
        (invalid_quantity, "INVALID_QUANTITY", "CRITICAL", "Quantity is invalid for one or more positions.", True),
        (missing_cost, "MISSING_COST_BASIS", "CRITICAL", "Cost basis is missing for one or more positions.", True),
        (invalid_cost, "INVALID_COST_BASIS", "CRITICAL", "Cost basis is invalid for one or more positions.", True),
        (missing_company, "MISSING_COMPANY_NAME", "WARNING", "Company name is unavailable for one or more holdings.", False),
        (missing_value, "MISSING_CURRENT_VALUE", "CRITICAL", "Current market value is unavailable for one or more holdings.", True),
        (inconsistent, "POSITION_VALUE_INCONSISTENT", "CRITICAL", "Quantity multiplied by current price does not match current value within the configured tolerance.", True),
    ):
        affected_symbols = sorted(set(symbols), key=str)
        if affected_symbols:
            issues.append(_issue(
                "portfolio",
                code,
                severity,
                message,
                affected=affected_symbols,
                blocks=blocks,
                next_action=(
                    "Review the source position and market data; no automatic correction was made."
                ),
            ))
    if aggregate_pnl_inconsistent:
        issues.append(_issue(
            "portfolio",
            "AGGREGATE_PNL_INCONSISTENT",
            "CRITICAL",
            "Total P&L does not equal realized plus unrealized P&L within the configured tolerance.",
            blocks=True,
        ))

    invalid_aggregate = [
        key for key in (
            "total_invested",
            "total_current_value",
            "total_realized_pnl",
            "total_unrealized_pnl",
            "total_pnl",
        )
        if portfolio_data.get(key) is None or not _number(portfolio_data.get(key))
    ]
    current_value_complete = (
        valuation_available
        and not missing_price
        and not missing_value
        and not invalid_quantity
        and not missing_quantity
        and not inconsistent
    )
    cost_complete = not missing_cost and not invalid_cost
    pnl_available = (
        current_value_complete
        and cost_complete
        and _number(portfolio_data.get("total_pnl"))
    )
    portfolio_status = (
        "AVAILABLE"
        if current_value_complete and cost_complete and not missing_company
        else "LIMITED"
        if valuation_available or positions
        else "UNAVAILABLE"
    )
    if missing_company:
        portfolio_findings.append("Company names are missing for some holdings.")
    if invalid_aggregate:
        portfolio_findings.append(
            "One or more aggregate portfolio metrics are unavailable."
        )
    portfolio_report = _category(
        portfolio_status,
        f"{len(positions)} holding(s); valuation "
        f"{'available' if valuation_available else 'unavailable'}; "
        f"P&L {'available' if pnl_available else 'limited or unavailable'}.",
        portfolio_findings,
    )

    market_rows = []
    missing_market_metadata = []
    for symbol, position in positions.items():
        quantity = position.get("quantity")
        if not _number(quantity) or quantity <= 0:
            continue
        freshness = _freshness(position, now)
        row = {
            "symbol": symbol,
            "price": (
                position.get("current_price")
                if _number(position.get("current_price"))
                else None
            ),
            "price_available": _number(position.get("current_price")),
            "source": position.get("source"),
            "retrieved_at": position.get("retrieved_at"),
            "market_timestamp": position.get("market_timestamp"),
            "currency": position.get("currency"),
            "exchange": position.get("exchange"),
            "freshness": freshness,
            "status": (
                "AVAILABLE"
                if _number(position.get("current_price"))
                and position.get("source")
                else "LIMITED"
                if _number(position.get("current_price"))
                else "UNAVAILABLE"
            ),
        }
        market_rows.append(row)
        if not row["price_available"]:
            issues.append(_issue(
                "market_price",
                "MISSING_MARKET_PRICE",
                "CRITICAL",
                f"Current price is unavailable for {symbol}.",
                affected=[symbol],
                blocks=True,
                next_action="Check the configured market-data source before relying on valuation.",
            ))
        elif row["freshness"]["category"] == "UNKNOWN":
            issues.append(_issue(
                "market_price",
                "MARKET_TIMESTAMP_UNKNOWN",
                "INFO",
                f"Market timestamp is unavailable or invalid for {symbol}; freshness cannot be classified.",
                affected=[symbol],
                blocks=False,
            ))
        elif row["freshness"]["category"] == "STALE":
            issues.append(_issue(
                "market_price",
                "PRICE_TIMESTAMP_STALE",
                "WARNING",
                f"Market timestamp for {symbol} is older than {MARKET_DATA_STALE_AFTER_HOURS} hours; stale describes timestamp age only.",
                affected=[symbol],
                blocks=False,
                next_action="Review the timestamp and source; no alternate price was substituted.",
            ))
        elif row["freshness"]["category"] == "AGING":
            issues.append(_issue(
                "market_price",
                "PRICE_TIMESTAMP_AGING",
                "INFO",
                f"Market timestamp for {symbol} is older than {MARKET_DATA_AGING_AFTER_HOURS} hours.",
                affected=[symbol],
                blocks=False,
            ))
        if row["price_available"] and (
            not row["source"]
            or not row["retrieved_at"]
            or not row["currency"]
            or not row["exchange"]
        ):
            missing_market_metadata.append(symbol)
    if missing_market_metadata:
        issues.append(_issue(
            "market_price",
            "MARKET_METADATA_INCOMPLETE",
            "WARNING",
            "Source, retrieval timestamp, currency, or exchange metadata is incomplete for one or more prices.",
            affected=missing_market_metadata,
            blocks=False,
        ))
    provider_notice = (
        "Yahoo Finance chart endpoint is a best-effort source and is not "
        "an exchange-authoritative real-time feed."
    )
    market_status = (
        "UNAVAILABLE"
        if positions and missing_price
        else "LIMITED"
        if missing_market_metadata
        or any(item["freshness"]["category"] in ("AGING", "STALE", "UNKNOWN") for item in market_rows)
        else "AVAILABLE"
        if market_rows
        else "UNKNOWN"
    )
    market_report = _category(
        market_status,
        f"{sum(row['price_available'] for row in market_rows)} of "
        f"{len(market_rows)} current holdings have a price. {provider_notice}",
        [provider_notice],
    )
    if market_data_error:
        market_report["details"].append(
            f"Market-data retrieval limitation: {market_data_error}"
        )

    if snapshots is None:
        snapshots = portfolio.get_portfolio_snapshots()
    normalized_snapshots = sorted(
        (_snapshot(item) for item in snapshots),
        key=lambda item: item.get("date") or "",
    )
    performance_history = portfolio.get_portfolio_performance_history()
    if historical_report is None:
        from investment_assistant.historical_analytics import (
            generate_historical_analytics,
        )

        historical_report = generate_historical_analytics(
            history=performance_history,
            snapshots=normalized_snapshots,
            historical_summary=portfolio.get_historical_performance_summary(
                performance_history
            ),
        )
    if attribution_report is None:
        from investment_assistant.performance_attribution import (
            generate_performance_attribution,
        )

        attribution_report = generate_performance_attribution(
            snapshots=normalized_snapshots,
            transactions=portfolio.get_transactions(),
        )
    invalid_snapshot_dates = []
    exact_dates = []
    exact_value_dates = []
    for item in normalized_snapshots:
        snapshot_date = item.get("date")
        try:
            parsed_date = date.fromisoformat(snapshot_date)
        except (TypeError, ValueError):
            invalid_snapshot_dates.append(snapshot_date)
        else:
            if parsed_date.isoformat() != snapshot_date:
                invalid_snapshot_dates.append(snapshot_date)
            else:
                exact_dates.append(snapshot_date)
                if _number(item.get("total_current_value")):
                    exact_value_dates.append(snapshot_date)
    detail_states, malformed_details = _holding_snapshot_summary(
        normalized_snapshots
    )
    detailed_count = sum(
        item["detail_status"] == "DETAILED" for item in detail_states
    )
    aggregate_count = sum(
        item["detail_status"] == "AGGREGATE_ONLY" for item in detail_states
    )
    history_data_quality = historical_report.get("data_quality", {})
    trend_available = bool(
        historical_report.get("trend_metrics", {}).get("available")
    )
    drawdown_available = bool(
        historical_report.get("drawdown", {}).get("available")
    )
    attribution_available = bool(
        (attribution_report or {}).get("available")
        and (attribution_report or {}).get(
            "holding_attribution", {}
        ).get("available")
    )
    attribution_message = (
        _DETAIL_UNAVAILABLE
        if len(normalized_snapshots) >= 2
        else "Holding-level attribution is unavailable because at least two portfolio snapshots are required."
    )
    history_findings = []
    if len(normalized_snapshots) == 0:
        history_findings.append("No snapshot recorded.")
        history_status = "UNAVAILABLE"
    elif len(normalized_snapshots) == 1:
        history_findings.append(
            "Trend analysis is limited because only one snapshot exists."
        )
        history_status = "LIMITED"
    else:
        history_status = (
            "AVAILABLE"
            if trend_available and drawdown_available
            else "LIMITED"
        )
    if aggregate_count:
        history_findings.append(
            f"{aggregate_count} aggregate-only snapshot(s); holding detail is unavailable for those dates."
        )
    if detailed_count:
        history_findings.append(
            f"{detailed_count} detailed holding snapshot(s) are stored."
        )
    if malformed_details:
        issues.append(_issue(
            "holding_history",
            "INVALID_HOLDING_SNAPSHOT_DETAIL",
            "WARNING",
            "Holding-level snapshot detail could not be read for one or more snapshots.",
            affected=malformed_details,
            blocks=False,
        ))
    if invalid_snapshot_dates:
        issues.append(_issue(
            "snapshot_history",
            "INVALID_SNAPSHOT_DATE",
            "WARNING",
            "One or more saved snapshots have dates that are not valid YYYY-MM-DD calendar dates.",
            affected=invalid_snapshot_dates,
            blocks=False,
        ))
    if not attribution_available:
        history_findings.append(attribution_message)
    if len(normalized_snapshots) < 2:
        issues.append(_issue(
            "snapshot_history",
            "INSUFFICIENT_SNAPSHOT_HISTORY",
            "INFO",
            (
                "No snapshot recorded."
                if not normalized_snapshots
                else "Only one snapshot is recorded; historical comparisons need at least two."
            ),
            affected=exact_dates,
            blocks=False,
        ))
    snapshot_report = {
        "status": history_status,
        "summary": f"{len(normalized_snapshots)} stored snapshot(s).",
        "snapshot_count": len(normalized_snapshots),
        "invalid_snapshot_dates": invalid_snapshot_dates,
        "earliest_snapshot_date": exact_dates[0] if exact_dates else None,
        "latest_snapshot_date": exact_dates[-1] if exact_dates else None,
        "date_range_days": (
            (
                date.fromisoformat(exact_dates[-1])
                - date.fromisoformat(exact_dates[0])
            ).days
            if len(exact_dates) >= 2
            else 0 if exact_dates else None
        ),
        "snapshots": detail_states,
        "detailed_snapshot_count": detailed_count,
        "aggregate_only_snapshot_count": aggregate_count,
        "missing_date_intervals": _date_gaps(normalized_snapshots),
        "trend_analysis": {
            "status": "AVAILABLE" if trend_available else "LIMITED" if normalized_snapshots else "UNAVAILABLE",
            "message": (
                None if trend_available
                else "Trend analysis is limited because only one snapshot exists."
                if len(normalized_snapshots) == 1
                else "No snapshot recorded."
            ),
        },
        "first_to_latest_comparison": {
            "status": (
                "AVAILABLE"
                if historical_report.get("trend_metrics", {}).get(
                    "first_to_latest_change"
                ) is not None
                else "LIMITED"
                if len(normalized_snapshots) >= 2
                else "UNAVAILABLE"
            ),
        },
        "previous_snapshot_comparison": {
            "status": (
                "AVAILABLE"
                if len(normalized_snapshots) >= 2
                and all(
                    _number(item.get("total_current_value"))
                    and _number(item.get("total_pnl"))
                    for item in normalized_snapshots[-2:]
                )
                else "LIMITED"
                if len(normalized_snapshots) >= 2
                else "UNAVAILABLE"
            ),
        },
        "drawdown_analysis": {
            "status": "AVAILABLE" if drawdown_available else "LIMITED" if normalized_snapshots else "UNAVAILABLE",
        },
        "holding_level_attribution": {
            "status": "AVAILABLE" if attribution_available else "UNAVAILABLE",
            "message": None if attribution_available else attribution_message,
        },
        "exact_date_questions": {
            "status": "AVAILABLE" if exact_value_dates else "UNAVAILABLE",
            "available_snapshot_dates": exact_value_dates,
            "message": (
                "Only exact dates with stored portfolio values are available; no nearby-date substitution is used."
                if exact_value_dates
                else "No snapshot recorded."
                if not normalized_snapshots
                else "No saved snapshot contains a valid portfolio value."
            ),
        },
        "details": history_findings + [
            item for item in history_data_quality.get("limitations", [])
            if item not in history_findings
        ],
    }

    if goals is None:
        goals = get_portfolio_goals(active_only=False)
    if goals_report is None:
        from investment_assistant.goals_intelligence import (
            generate_goals_intelligence,
        )

        goals_report = generate_goals_intelligence(
            portfolio_data=portfolio_data,
            history=performance_history,
        )
    active_goal_ids = {
        item.get("id") for item in goals_report.get("goals", [])
    }
    goal_issues = []
    active_goals = [item for item in goals if item.get("is_active", 1)]
    for goal in active_goals:
        goal_id = goal.get("id")
        goal_type = goal.get("target_type")
        target = goal.get("target_value")
        if goal_type not in (
            "PORTFOLIO_VALUE",
            "ABSOLUTE_PNL",
            "RETURN_PERCENT",
        ) or not _number(target) or target < 0:
            goal_issues.append(goal_id or goal.get("goal_name"))
        target_date = goal.get("target_date")
        if target_date:
            try:
                date.fromisoformat(target_date)
            except (TypeError, ValueError):
                goal_issues.append(goal_id or goal.get("goal_name"))
        if goal_id not in active_goal_ids and goal_report_has_no_current_value(goals_report, goal):
            goal_issues.append(goal_id or goal.get("goal_name"))
    no_current_goal_values = [
        item.get("id")
        for item in goals_report.get("goals", [])
        if item.get("current_value") is None
    ]
    missing_goal_dates = [
        goal.get("id") or goal.get("goal_name")
        for goal in active_goals
        if not goal.get("target_date")
    ]
    if not valuation_available:
        no_current_goal_values.extend(
            goal.get("id") or goal.get("goal_name")
            for goal in active_goals
            if (goal.get("id") or goal.get("goal_name"))
            not in no_current_goal_values
        )
    goal_issues.extend(no_current_goal_values)
    if goal_issues:
        issues.append(_issue(
            "goals",
            "GOAL_DATA_LIMITATION",
            "WARNING",
            "One or more goals contain invalid fields or have no current valuation available.",
            affected=goal_issues,
            blocks=False,
        ))
    if missing_goal_dates:
        issues.append(_issue(
            "goals",
            "GOAL_TARGET_DATE_NOT_SET",
            "INFO",
            "A target date is optional and is not set for one or more active goals.",
            affected=missing_goal_dates,
            blocks=False,
        ))
    goal_status = (
        "UNKNOWN" if not goals
        else "LIMITED" if goal_issues or missing_goal_dates
        else "AVAILABLE"
    )
    goal_report = _category(
        goal_status,
        f"{len(active_goals)} active goal(s).",
        [
            "Target dates are not set for some goals."
            if missing_goal_dates
            else "",
            "Goal data is checked for completeness only; goal suitability is not evaluated.",
        ],
    )
    goal_report["details"] = [
        detail for detail in goal_report["details"] if detail
    ]

    if benchmarks is None:
        benchmarks = get_portfolio_benchmarks(active_only=False)
    if observations_by_benchmark is None:
        observations_by_benchmark = {}
        for benchmark in benchmarks:
            observations_by_benchmark[benchmark["id"]] = (
                get_benchmark_observations(benchmark["id"])
            )
    benchmark_rows = []
    benchmark_issues = []
    active_benchmarks = [
        item for item in benchmarks if item.get("is_active", 1)
    ]
    snapshot_dates = set(exact_dates)
    for benchmark in benchmarks:
        observations = list(
            observations_by_benchmark.get(benchmark.get("id"), [])
        )
        observed_dates = []
        future_dates = []
        invalid_values = []
        for observation in observations:
            observed_date = observation.get("date")
            try:
                parsed_date = date.fromisoformat(observed_date)
            except (TypeError, ValueError):
                invalid_values.append(observed_date)
                continue
            if parsed_date.isoformat() != observed_date:
                invalid_values.append(observed_date)
                continue
            if parsed_date > now.date():
                future_dates.append(observed_date)
            value = observation.get("value")
            is_return = benchmark.get("benchmark_type") == "USER_PROVIDED_RETURN"
            if (
                not _number(value)
                or (is_return and value < -100)
                or (not is_return and value <= 0)
            ):
                invalid_values.append(observed_date)
                continue
            if parsed_date <= now.date():
                observed_dates.append(observed_date)
        matched_dates = sorted(snapshot_dates.intersection(observed_dates))
        goal_benchmark = next(
            (
                item for item in goals_report.get("benchmarks", [])
                if item.get("id") == benchmark.get("id")
            ),
            {},
        )
        comparison = goal_benchmark.get("comparison", {})
        row_status = (
            "UNAVAILABLE"
            if not benchmark.get("is_active", 1)
            else "LIMITED"
            if future_dates or invalid_values
            else "AVAILABLE"
            if comparison.get("available")
            else "LIMITED"
        )
        benchmark_rows.append({
            "id": benchmark.get("id"),
            "name": benchmark.get("benchmark_name"),
            "type": benchmark.get("benchmark_type"),
            "active": bool(benchmark.get("is_active", 1)),
            "observation_count": len(observed_dates),
            "earliest_observation_date": min(observed_dates) if observed_dates else None,
            "latest_observation_date": max(observed_dates) if observed_dates else None,
            "matching_snapshot_dates": matched_dates,
            "missing_matching_snapshot_dates": sorted(snapshot_dates - set(observed_dates)),
            "future_observation_dates": future_dates,
            "invalid_observation_dates": invalid_values,
            "comparison_status": row_status,
            "comparison_message": comparison.get("message"),
        })
        if future_dates:
            benchmark_issues.append(benchmark.get("id"))
        if invalid_values:
            benchmark_issues.append(benchmark.get("id"))
        if benchmark.get("is_active", 1) and not comparison.get("available"):
            benchmark_issues.append(benchmark.get("id"))
    if benchmark_issues:
        issues.append(_issue(
            "benchmarks",
            "BENCHMARK_COMPARISON_LIMITED",
            "WARNING",
            "One or more configured benchmarks have invalid/future observations or lack two exact matching observations.",
            affected=sorted(set(benchmark_issues), key=str),
            blocks=False,
            next_action="Enter actual observations for exact portfolio snapshot dates; no values were fetched or interpolated.",
        ))
    benchmark_status = (
        "UNKNOWN" if not benchmarks
        else "LIMITED" if benchmark_issues
        else "AVAILABLE"
    )
    benchmark_report = _category(
        benchmark_status,
        f"{len(active_benchmarks)} active of {len(benchmarks)} configured benchmark(s).",
        [
            "No portfolio benchmarks configured."
            if not benchmarks
            else "Only actual user-provided benchmark observations are used."
        ],
    )

    news_was_supplied = news_by_symbol is not None
    news_by_symbol = news_by_symbol or {}
    news_errors = list(news_errors or [])
    news_rows = []
    for symbol in positions if news_was_supplied else ():
        articles = news_by_symbol.get(symbol) or []
        news_rows.append({
            "symbol": symbol,
            "relevant_item_count": len(articles),
            "status": "AVAILABLE" if articles else "LIMITED",
            "message": (
                None
                if articles
                else "No relevant news items were available for this holding."
            ),
        })
    news_status = (
        "UNKNOWN" if not news_rows and not news_errors
        else "LIMITED" if news_errors or any(not item["relevant_item_count"] for item in news_rows)
        else "AVAILABLE"
    )
    news_report = _category(
        news_status,
        f"{sum(item['relevant_item_count'] for item in news_rows)} relevant item(s) for {len(news_rows)} holding(s).",
        [*news_errors],
    )
    news_report["holdings"] = news_rows
    news_report["duplicate_syndicated_filtering"] = {
        "status": "APPLIED",
        "removed_item_count": None,
        "message": (
            "The news retrieval layer filters duplicate/syndicated headlines; "
            "the number filtered is not exposed."
        ),
    }

    optional_inputs = {
        "historical_data": history_status,
        "risk_data": (
            "AVAILABLE" if (risk_report or {}).get("data_quality") else "UNKNOWN"
        ),
        "attribution_data": (
            "AVAILABLE" if attribution_available
            else "LIMITED" if attribution_report
            else "UNKNOWN"
        ),
        "goal_data": goal_status,
        "benchmark_data": benchmark_status,
        "news_data": news_status,
    }
    ai_status = (
        "AVAILABLE"
        if portfolio_status == "AVAILABLE"
        else "LIMITED"
        if positions or valuation_available
        else "UNAVAILABLE"
    )
    ai_report = {
        "status": ai_status,
        "can_generate_explanation": bool(positions or valuation_available),
        "inputs": optional_inputs,
        "limitations": [
            f"{key.replace('_', ' ')}: {status}"
            for key, status in optional_inputs.items()
            if status in ("LIMITED", "UNAVAILABLE")
        ],
        "message": (
            "Optional missing inputs are disclosed and do not alone block an explanation."
            if ai_status != "UNAVAILABLE"
            else "Structured portfolio inputs are unavailable."
        ),
    }

    source_limitations = [
        provider_notice,
        "Price freshness is classified from market_timestamp, not retrieval time.",
        (
            f"Freshness thresholds: FRESH up to {MARKET_DATA_AGING_AFTER_HOURS} "
            f"hours; AGING up to {MARKET_DATA_STALE_AFTER_HOURS} hours; "
            f"STALE above {MARKET_DATA_STALE_AFTER_HOURS} hours."
        ),
    ]
    category_reports = {
        "portfolio": portfolio_report,
        "market_price": market_report,
        "snapshot_history": _category(
            history_status,
            snapshot_report["summary"],
            history_findings,
        ),
        "holding_history": _category(
            "AVAILABLE" if detailed_count else "LIMITED" if normalized_snapshots else "UNAVAILABLE",
            f"{detailed_count} detailed and {aggregate_count} aggregate-only snapshot(s).",
            history_findings,
        ),
        "goals": goal_report,
        "benchmarks": benchmark_report,
        "news": news_report,
        "ai_analysis_inputs": _category(ai_status, ai_report["message"], ai_report["limitations"]),
        "data_source_limitations": _category(
            "LIMITED",
            "Market-data source and freshness thresholds are disclosed.",
            source_limitations,
        ),
    }
    blocking_issues = [
        issue for issue in issues if issue["blocks_calculation"]
    ]
    if not valuation_available or blocking_issues:
        overall_status = "INSUFFICIENT DATA"
    elif (
        portfolio_status != "AVAILABLE"
        or market_status != "AVAILABLE"
        or history_status != "AVAILABLE"
        or goal_status == "LIMITED"
        or benchmark_status == "LIMITED"
        or news_status == "LIMITED"
    ):
        overall_status = "LIMITED"
    else:
        overall_status = "READY"

    return {
        "overall_status": overall_status,
        "summary": (
            f"Data status: {overall_status}. "
            f"{len(issues)} data-quality issue(s) identified."
        ),
        "categories": category_reports,
        "portfolio": {
            "status": portfolio_status,
            "holding_count": len(positions),
            "valuation_available": valuation_available,
            "cost_basis_available": cost_complete,
            "pnl_available": pnl_available,
            "current_quantities_valid": not (
                invalid_quantity or missing_quantity
            ),
            "company_names_available": not missing_company,
            "current_values_available": not missing_value,
        },
        "market_data": {
            "status": market_status,
            "source_limitation": provider_notice,
            "freshness_thresholds_hours": {
                "fresh_through": MARKET_DATA_AGING_AFTER_HOURS,
                "aging_through": MARKET_DATA_STALE_AFTER_HOURS,
                "stale_after": MARKET_DATA_STALE_AFTER_HOURS,
            },
            "holdings": market_rows,
            "price_count": sum(row["price_available"] for row in market_rows),
            "missing_price_count": len(missing_price),
            "freshness_counts": {
                label: sum(
                    row["freshness"]["category"] == label
                    for row in market_rows
                )
                for label in ("FRESH", "AGING", "STALE", "UNKNOWN")
            },
        },
        "snapshot_history": snapshot_report,
        "goals": {
            "status": goal_status,
            "active_goal_count": len(active_goals),
            "goals_without_target_date": missing_goal_dates,
            "invalid_goal_ids": sorted(set(goal_issues), key=str),
            "goals_without_current_value": no_current_goal_values,
        },
        "benchmarks": {
            "status": benchmark_status,
            "configured_count": len(benchmarks),
            "active_count": len(active_benchmarks),
            "items": benchmark_rows,
        },
        "news": news_report,
        "ai_analysis_inputs": ai_report,
        "source_limitations": source_limitations,
        "issues": issues,
        "issue_counts": {
            severity: sum(
                issue["severity"] == severity for issue in issues
            )
            for severity in ("INFO", "WARNING", "CRITICAL")
        },
        "generated_at": now.isoformat(),
        "automatic_repairs_performed": False,
    }


def goal_report_has_no_current_value(goals_report, goal):
    return any(
        item.get("id") == goal.get("id")
        and item.get("current_value") is None
        for item in goals_report.get("goals", [])
    )
