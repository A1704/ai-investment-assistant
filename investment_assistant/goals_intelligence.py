"""Deterministic portfolio goal progress and user-configured benchmark data.

USER_PROVIDED_VALUE observations are positive index/value levels.
USER_PROVIDED_RETURN observations are cumulative return percentages measured
from a consistent user-selected baseline.
"""

from datetime import date, datetime
import math
from numbers import Real
import sqlite3

from investment_assistant import portfolio
from investment_assistant.database import get_connection


SUPPORTED_GOAL_TYPES = {
    "PORTFOLIO_VALUE",
    "ABSOLUTE_PNL",
    "RETURN_PERCENT",
}
SUPPORTED_BENCHMARK_TYPES = {
    "USER_PROVIDED_RETURN",
    "USER_PROVIDED_VALUE",
}
BENCHMARK_UNAVAILABLE_MESSAGE = (
    "Benchmark comparison unavailable because matching benchmark "
    "observations are not available."
)

_UNSET = object()


def _validate_name(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty.")
    return value.strip()


def _validate_id(value, field_name):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _validate_date(value, field_name, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
    return value


def _validate_finite_value(value, field_name, minimum=0):
    if (
        not isinstance(value, Real)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < minimum
    ):
        if minimum == 0:
            raise ValueError(f"{field_name} must be a finite value >= 0.")
        raise ValueError(
            f"{field_name} must be a finite value >= {minimum}."
        )
    return float(value)


def _row_to_dict(row, fields):
    return dict(zip(fields, row))


def create_portfolio_goal(
    goal_name,
    target_type,
    target_value,
    target_date=None,
):
    goal_name = _validate_name(goal_name, "Goal name")
    if not isinstance(target_type, str):
        raise ValueError("Target type is not supported.")
    target_type = target_type.strip().upper()
    if target_type not in SUPPORTED_GOAL_TYPES:
        raise ValueError("Target type is not supported.")
    target_value = _validate_finite_value(target_value, "Target value")
    target_date = _validate_date(
        target_date,
        "Target date",
        optional=True,
    )

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_goals (
                goal_name, target_type, target_value, target_date
            )
            VALUES (?, ?, ?, ?)
            """,
            (goal_name, target_type, target_value, target_date),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_portfolio_goals(active_only=False):
    conn = get_connection()
    try:
        query = """
            SELECT id, goal_name, target_type, target_value,
                   target_date, is_active, created_at
            FROM portfolio_goals
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        rows = conn.execute(query).fetchall()
        fields = (
            "id",
            "goal_name",
            "target_type",
            "target_value",
            "target_date",
            "is_active",
            "created_at",
        )
        return [_row_to_dict(row, fields) for row in rows]
    finally:
        conn.close()


def get_active_portfolio_goals():
    return get_portfolio_goals(active_only=True)


def update_portfolio_goal(
    goal_id,
    *,
    goal_name=None,
    target_type=None,
    target_value=None,
    target_date=_UNSET,
):
    goal_id = _validate_id(goal_id, "Goal ID")
    updates = {}
    if goal_name is not None:
        updates["goal_name"] = _validate_name(goal_name, "Goal name")
    if target_type is not None:
        if not isinstance(target_type, str):
            raise ValueError("Target type is not supported.")
        target_type = target_type.strip().upper()
        if target_type not in SUPPORTED_GOAL_TYPES:
            raise ValueError("Target type is not supported.")
        updates["target_type"] = target_type
    if target_value is not None:
        updates["target_value"] = _validate_finite_value(
            target_value,
            "Target value",
        )
    if target_date is not _UNSET:
        updates["target_date"] = _validate_date(
            target_date,
            "Target date",
            optional=True,
        )
    if not updates:
        raise ValueError("At least one goal field must be supplied.")

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE portfolio_goals SET {assignments} WHERE id = ?",
            (*updates.values(), goal_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Portfolio goal {goal_id} does not exist.")
    finally:
        conn.close()


def deactivate_portfolio_goal(goal_id):
    goal_id = _validate_id(goal_id, "Goal ID")
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE portfolio_goals SET is_active = 0 WHERE id = ?",
            (goal_id,),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Portfolio goal {goal_id} does not exist.")
    finally:
        conn.close()


def delete_portfolio_goal(goal_id):
    goal_id = _validate_id(goal_id, "Goal ID")
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM portfolio_goals WHERE id = ?",
            (goal_id,),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Portfolio goal {goal_id} does not exist.")
    finally:
        conn.close()


def create_portfolio_benchmark(
    benchmark_name,
    benchmark_type,
    benchmark_symbol=None,
):
    benchmark_name = _validate_name(benchmark_name, "Benchmark name")
    if not isinstance(benchmark_type, str):
        raise ValueError("Benchmark type is not supported.")
    benchmark_type = benchmark_type.strip().upper()
    if benchmark_type not in SUPPORTED_BENCHMARK_TYPES:
        raise ValueError("Benchmark type is not supported.")
    if benchmark_symbol is not None:
        benchmark_symbol = _validate_name(
            benchmark_symbol,
            "Benchmark symbol",
        )

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO portfolio_benchmarks (
                benchmark_name, benchmark_symbol, benchmark_type
            )
            VALUES (?, ?, ?)
            """,
            (benchmark_name, benchmark_symbol, benchmark_type),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_portfolio_benchmarks(active_only=False):
    conn = get_connection()
    try:
        query = """
            SELECT id, benchmark_name, benchmark_symbol, benchmark_type,
                   is_active, created_at
            FROM portfolio_benchmarks
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        rows = conn.execute(query).fetchall()
        fields = (
            "id",
            "benchmark_name",
            "benchmark_symbol",
            "benchmark_type",
            "is_active",
            "created_at",
        )
        return [_row_to_dict(row, fields) for row in rows]
    finally:
        conn.close()


def add_benchmark_observation(
    benchmark_id,
    observation_date,
    value,
    *,
    as_of_date=None,
):
    benchmark_id = _validate_id(benchmark_id, "Benchmark ID")
    observation_date = _validate_date(
        observation_date,
        "Observation date",
    )
    as_of_date = as_of_date or date.today()
    if isinstance(as_of_date, datetime):
        as_of_date = as_of_date.date()
    if not isinstance(as_of_date, date):
        raise ValueError("as_of_date must be a date.")
    if date.fromisoformat(observation_date) > as_of_date:
        raise ValueError("Future benchmark observations are not allowed.")

    conn = get_connection()
    try:
        benchmark = conn.execute(
            """
            SELECT benchmark_type
            FROM portfolio_benchmarks
            WHERE id = ?
            """,
            (benchmark_id,),
        ).fetchone()
        if benchmark is None:
            raise ValueError(
                f"Portfolio benchmark {benchmark_id} does not exist."
            )
        minimum = -100 if benchmark[0] == "USER_PROVIDED_RETURN" else 0
        value = _validate_finite_value(
            value,
            "Observation value",
            minimum=minimum,
        )
        if (
            benchmark[0] == "USER_PROVIDED_VALUE"
            and value == 0
        ):
            raise ValueError(
                "Value/index observations must be greater than 0."
            )
        existing = conn.execute(
            """
            SELECT 1
            FROM portfolio_benchmark_observations
            WHERE benchmark_id = ? AND observation_date = ?
            """,
            (benchmark_id, observation_date),
        ).fetchone()
        if existing is not None:
            raise ValueError(
                "An observation already exists for this benchmark date."
            )
        try:
            conn.execute(
                """
                INSERT INTO portfolio_benchmark_observations (
                    benchmark_id, observation_date, value
                )
                VALUES (?, ?, ?)
                """,
                (benchmark_id, observation_date, value),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "An observation already exists for this benchmark date."
            ) from error
        conn.commit()
    finally:
        conn.close()


def get_benchmark_observations(benchmark_id):
    benchmark_id = _validate_id(benchmark_id, "Benchmark ID")
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT observation_date, value
            FROM portfolio_benchmark_observations
            WHERE benchmark_id = ?
            ORDER BY observation_date
            """,
            (benchmark_id,),
        ).fetchall()
        return [
            {"date": observation_date, "value": value}
            for observation_date, value in rows
        ]
    finally:
        conn.close()


def _number(value):
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _goal_progress(goal, portfolio_data, history, as_of_date):
    target_type = goal["target_type"]
    if target_type == "PORTFOLIO_VALUE":
        current = portfolio_data.get("total_current_value")
        current_label = "Latest portfolio value"
        unit = "currency"
        history_key = "total_current_value"
    elif target_type == "ABSOLUTE_PNL":
        current = portfolio_data.get("total_pnl")
        current_label = "Latest total P&L"
        unit = "currency"
        history_key = "total_pnl"
    else:
        current = portfolio_data.get("total_return_percent")
        current_label = "Latest portfolio return"
        unit = "percent"
        history_key = "total_return_percent"

    latest_data_date = as_of_date.isoformat() if _number(current) else None
    if not _number(current):
        historical = next(
            (
                item for item in reversed(history)
                if _number(item.get(history_key))
            ),
            None,
        )
        if historical is not None:
            current = historical[history_key]
            latest_data_date = historical.get("date")

    target = float(goal["target_value"])
    available = _number(current)
    current = float(current) if available else None
    difference = current - target if available else None
    if difference is not None and not _number(difference):
        difference = None
    progress_percent = None
    if available and target > 0:
        candidate_progress = current / target * 100
        if _number(candidate_progress):
            progress_percent = candidate_progress
    reached = available and current >= target
    if target_type == "RETURN_PERCENT":
        difference_unit = "percentage_points"
    else:
        difference_unit = "currency"

    target_date = goal["target_date"]
    target_date_arrived = (
        date.fromisoformat(target_date) <= as_of_date
        if target_date
        else None
    )
    if not available:
        status = (
            "Insufficient historical data"
            if target_type == "RETURN_PERCENT" and not history
            else "No current valuation available"
        )
    elif reached:
        status = "Reached"
    elif target_date and not target_date_arrived:
        status = "In progress"
    else:
        status = "Below target"

    remaining_amount = (
        max(target - current, 0)
        if available and target_type == "PORTFOLIO_VALUE"
        else None
    )
    if remaining_amount is not None and not _number(remaining_amount):
        remaining_amount = None

    return {
        **goal,
        "target_value": target,
        "current_value": current,
        "current_value_label": current_label,
        "unit": unit,
        "difference": difference,
        "difference_unit": difference_unit,
        "progress_percent": progress_percent,
        "remaining_amount": remaining_amount,
        "target_reached": bool(reached),
        "target_date_arrived": target_date_arrived,
        "target_date_status": (
            "Target date has not yet arrived."
            if target_date and not target_date_arrived
            else "Target date has arrived."
            if target_date
            else None
        ),
        "latest_portfolio_data_date": latest_data_date,
        "status": status,
    }


def _portfolio_value_by_date(history):
    return {
        item.get("date"): item.get("total_current_value")
        for item in history
        if isinstance(item.get("date"), str)
    }


def _benchmark_comparison(benchmark, observations, portfolio_history):
    observations_by_date = {
        item["date"]: item["value"]
        for item in observations
    }
    portfolio_by_date = _portfolio_value_by_date(portfolio_history)
    shared_dates = sorted(
        set(observations_by_date).intersection(portfolio_by_date)
    )
    base = {
        "available": False,
        "period_start_date": None,
        "period_end_date": None,
        "portfolio_return_percent": None,
        "benchmark_return_percent": None,
        "difference_percentage_points": None,
        "portfolio_value_change": None,
        "benchmark_value_change": None,
        "portfolio_return_basis": (
            "Portfolio value change between exact matching snapshots; "
            "transaction cash flows are not adjusted."
        ),
        "message": BENCHMARK_UNAVAILABLE_MESSAGE,
    }
    if len(shared_dates) < 2:
        return base

    start_date, end_date = shared_dates[0], shared_dates[-1]
    portfolio_start = portfolio_by_date[start_date]
    portfolio_end = portfolio_by_date[end_date]
    benchmark_start = observations_by_date[start_date]
    benchmark_end = observations_by_date[end_date]
    if not all(
        _number(value)
        for value in (
            portfolio_start,
            portfolio_end,
            benchmark_start,
            benchmark_end,
        )
    ) or portfolio_start == 0:
        return base

    portfolio_change = portfolio.calculate_snapshot_changes([
        {
            "date": start_date,
            "total_current_value": portfolio_start,
        },
        {
            "date": end_date,
            "total_current_value": portfolio_end,
        },
    ])[-1]
    portfolio_return = portfolio_change["value_change_percent"]
    if not _number(portfolio_return):
        return base
    benchmark_type = benchmark["benchmark_type"]
    if benchmark_type == "USER_PROVIDED_VALUE":
        if benchmark_start == 0:
            return base
        benchmark_return = (
            benchmark_end / benchmark_start - 1
        ) * 100
        benchmark_value_change = benchmark_end - benchmark_start
    else:
        return_denominator = 100 + benchmark_start
        if return_denominator == 0:
            return base
        benchmark_return = (
            (100 + benchmark_end) / return_denominator - 1
        ) * 100
        benchmark_value_change = None

    portfolio_value_change = portfolio_change["value_change"]
    benchmark_value_change = (
        benchmark_value_change
        if benchmark_value_change is None or _number(benchmark_value_change)
        else None
    )
    difference = portfolio_return - benchmark_return
    if not all(
        _number(value)
        for value in (
            portfolio_return,
            benchmark_return,
            portfolio_value_change,
            difference,
        )
    ):
        return base

    return {
        **base,
        "available": True,
        "period_start_date": start_date,
        "period_end_date": end_date,
        "portfolio_return_percent": portfolio_return,
        "benchmark_return_percent": benchmark_return,
        "difference_percentage_points": difference,
        "portfolio_value_change": portfolio_value_change,
        "benchmark_value_change": benchmark_value_change,
        "message": None,
    }


def generate_goals_intelligence(
    *,
    portfolio_data=None,
    history=None,
    goals=None,
    benchmarks=None,
    observations_by_benchmark=None,
    as_of_date=None,
):
    """Return factual goal progress and comparisons using supplied records."""
    if portfolio_data is None:
        portfolio_data = portfolio.calculate_portfolio_valuation()
    if history is None:
        history = portfolio.get_portfolio_performance_history()
    history = sorted(
        (dict(item) for item in history),
        key=lambda item: item.get("date", ""),
    )
    if goals is None:
        goals = get_active_portfolio_goals()
    else:
        goals = [dict(goal) for goal in goals if goal.get("is_active", 1)]
    if benchmarks is None:
        benchmarks = get_portfolio_benchmarks(active_only=True)
    else:
        benchmarks = [
            dict(item) for item in benchmarks if item.get("is_active", 1)
        ]
    as_of_date = as_of_date or date.today()
    if isinstance(as_of_date, datetime):
        as_of_date = as_of_date.date()
    if not isinstance(as_of_date, date):
        raise ValueError("as_of_date must be a date.")

    goal_reports = [
        _goal_progress(goal, portfolio_data, history, as_of_date)
        for goal in goals
    ]
    if observations_by_benchmark is None:
        observations_by_benchmark = {
            benchmark["id"]: get_benchmark_observations(benchmark["id"])
            for benchmark in benchmarks
        }
    benchmark_reports = []
    for benchmark in benchmarks:
        observations = []
        for observation in observations_by_benchmark.get(
            benchmark["id"], []
        ):
            observation_date = _validate_date(
                observation.get("date"),
                "Observation date",
            )
            if date.fromisoformat(observation_date) <= as_of_date:
                value = _validate_finite_value(
                    observation.get("value"),
                    "Observation value",
                    minimum=(
                        -100
                        if benchmark["benchmark_type"]
                        == "USER_PROVIDED_RETURN"
                        else 0
                    ),
                )
                if (
                    benchmark["benchmark_type"]
                    == "USER_PROVIDED_VALUE"
                    and value == 0
                ):
                    raise ValueError(
                        "Value/index observations must be greater than 0."
                    )
                observations.append({
                    "date": observation_date,
                    "value": value,
                })
        benchmark_reports.append({
            **benchmark,
            "observations": list(observations),
            "comparison": _benchmark_comparison(
                benchmark,
                observations,
                history,
            ),
        })

    return {
        "goals": goal_reports,
        "active_goal_count": len(goal_reports),
        "benchmarks": benchmark_reports,
        "active_benchmark_count": len(benchmark_reports),
        "latest_portfolio_value": (
            portfolio_data.get("total_current_value")
            if _number(portfolio_data.get("total_current_value"))
            else None
        ),
        "latest_portfolio_data_date": (
            as_of_date.isoformat()
            if _number(portfolio_data.get("total_current_value"))
            else history[-1].get("date") if history else None
        ),
        "historical_snapshot_count": len(history),
        "limitations": [
            item["comparison"]["message"]
            for item in benchmark_reports
            if not item["comparison"]["available"]
        ],
    }
