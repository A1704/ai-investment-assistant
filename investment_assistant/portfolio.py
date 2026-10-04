import json
from datetime import datetime
import math
import re
from numbers import Real

from investment_assistant.database import get_connection
from investment_assistant.market_data import get_yahoo_quote


def calculate_positions(transactions, opening_positions=()):
    """
    Calculate portfolio positions using weighted-average cost basis.

    Opening positions are treated as the starting portfolio state.

    BUY:
        - Increases quantity
        - Increases cost basis
        - Recalculates weighted-average cost

    SELL:
        - Requires sufficient quantity
        - Uses the current weighted-average cost for sold shares
        - Calculates realized P&L
        - Reduces remaining cost basis
        - Keeps the remaining average cost unchanged

    Returns:
        Dictionary containing one calculated position per symbol.
    """

    positions = {}

    def get_position(symbol):
        return positions.setdefault(
            symbol,
            {
                "total_buy_quantity": 0,
                "total_sell_quantity": 0,
                "current_quantity": 0,
                "total_buy_cost": 0,
                "total_sell_proceeds": 0,
                "average_buy_price": None,
                "remaining_cost_basis": 0,
                "realized_pnl": 0,
                "is_zero_quantity": True,
            },
        )

    # ---------------------------------------------------------
    # 1. Load opening positions
    # ---------------------------------------------------------
    for opening_position in opening_positions:
        (
            _opening_id,
            symbol,
            _company_name,
            quantity,
            average_cost,
            invested_amount,
            _purchase_date,
        ) = opening_position

        symbol = symbol.strip().upper()

        position = get_position(symbol)

        position["total_buy_quantity"] += quantity
        position["total_buy_cost"] += invested_amount
        position["current_quantity"] += quantity
        position["remaining_cost_basis"] += invested_amount

    # ---------------------------------------------------------
    # 2. Process transactions
    # ---------------------------------------------------------
    for transaction in transactions:
        (
            _transaction_id,
            symbol,
            _company_name,
            transaction_type,
            quantity,
            price,
            _transaction_date,
        ) = transaction

        symbol = symbol.strip().upper()
        transaction_type = transaction_type.upper()

        position = get_position(symbol)

        if transaction_type == "BUY":

            purchase_cost = quantity * price

            position["total_buy_quantity"] += quantity
            position["total_buy_cost"] += purchase_cost
            position["current_quantity"] += quantity
            position["remaining_cost_basis"] += purchase_cost

        elif transaction_type == "SELL":

            current_quantity = position["current_quantity"]

            # Prevent short selling / selling more than owned.
            if quantity > current_quantity:
                raise ValueError(
                    f"Cannot sell {quantity} shares of {symbol}. "
                    f"Only {current_quantity} shares are available."
                )

            # Calculate weighted-average cost before the sale.
            if current_quantity > 0:
                average_cost_before_sale = (
                    position["remaining_cost_basis"]
                    / current_quantity
                )
            else:
                average_cost_before_sale = 0

            # Cost basis assigned to the shares being sold.
            cost_of_sold_shares = (
                quantity * average_cost_before_sale
            )

            # Money received from the sale.
            sale_proceeds = quantity * price

            # Realized profit/loss.
            realized_pnl = (
                sale_proceeds - cost_of_sold_shares
            )

            position["total_sell_quantity"] += quantity
            position["total_sell_proceeds"] += sale_proceeds
            position["realized_pnl"] += realized_pnl

            # Reduce remaining holding and cost basis.
            position["current_quantity"] -= quantity
            position["remaining_cost_basis"] -= cost_of_sold_shares

            # Prevent tiny floating-point residue after full liquidation.
            if abs(position["remaining_cost_basis"]) < 1e-9:
                position["remaining_cost_basis"] = 0

        else:
            raise ValueError(
                "Transaction type must be BUY or SELL."
            )

    # ---------------------------------------------------------
    # 3. Finalize calculated fields
    # ---------------------------------------------------------
    for position in positions.values():

        current_quantity = position["current_quantity"]

        if current_quantity > 0:

            position["average_buy_price"] = (
                position["remaining_cost_basis"]
                / current_quantity
            )

            position["is_zero_quantity"] = False

        else:

            position["average_buy_price"] = None
            position["remaining_cost_basis"] = 0
            position["is_zero_quantity"] = True

    return positions


def _validate_date(value, field_name):
    """Validate a date in YYYY-MM-DD format."""

    if value is None:
        return

    if (
        not isinstance(value, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    ):
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        )

    try:
        datetime.strptime(value, "%Y-%m-%d")

    except ValueError as error:

        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from error


def add_opening_position(
    symbol,
    company_name,
    quantity,
    average_cost,
    invested_amount,
    purchase_date=None,
):
    """
    Add an opening portfolio position.

    Opening positions represent holdings that existed before
    the transaction tracking system was introduced.
    """

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol cannot be empty.")

    if not isinstance(company_name, str) or not company_name.strip():
        raise ValueError("Company name cannot be empty.")

    if (
        not isinstance(quantity, Real)
        or isinstance(quantity, bool)
        or not math.isfinite(quantity)
        or quantity <= 0
    ):
        raise ValueError("Quantity must be greater than 0.")

    if (
        not isinstance(average_cost, Real)
        or isinstance(average_cost, bool)
        or not math.isfinite(average_cost)
        or average_cost < 0
    ):
        raise ValueError("Average cost cannot be negative.")

    if (
        not isinstance(invested_amount, Real)
        or isinstance(invested_amount, bool)
        or not math.isfinite(invested_amount)
        or invested_amount < 0
    ):
        raise ValueError("Invested amount cannot be negative.")

    if not math.isclose(
        quantity * average_cost,
        invested_amount,
        rel_tol=1e-9,
        abs_tol=0.01,
    ):
        raise ValueError(
            "Invested amount must match quantity multiplied by average cost."
        )

    _validate_date(purchase_date, "Purchase date")

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO opening_positions
        (
            symbol,
            company_name,
            quantity,
            average_cost,
            invested_amount,
            purchase_date
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            symbol.strip().upper(),
            company_name.strip(),
            quantity,
            average_cost,
            invested_amount,
            purchase_date,
        ),
    )

    conn.commit()
    conn.close()


def get_opening_positions():
    """Return all opening portfolio positions."""

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            id,
            symbol,
            company_name,
            quantity,
            average_cost,
            invested_amount,
            purchase_date
        FROM opening_positions
        ORDER BY symbol, id
        """
    ).fetchall()

    conn.close()

    return rows


def add_transaction(
    symbol,
    company_name,
    transaction_type,
    quantity,
    price,
    transaction_date,
):
    """
    Add a BUY or SELL transaction to the database.

    Validation happens before the transaction is inserted.

    BUY:
        - Quantity must be positive.
        - Price cannot be negative.
        - Date must be valid.

    SELL:
        - Quantity must be positive.
        - Price cannot be negative.
        - Date must be valid.
        - Symbol must have sufficient available quantity.
        - Invalid SELL transactions are rejected before database insertion.
    """

    # ---------------------------------------------------------
    # 1. Basic validation
    # ---------------------------------------------------------

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol cannot be empty.")

    if not isinstance(company_name, str) or not company_name.strip():
        raise ValueError("Company name cannot be empty.")

    if not isinstance(transaction_type, str):
        raise ValueError(
            "Transaction type must be BUY or SELL."
        )

    symbol = symbol.strip().upper()
    company_name = company_name.strip()
    transaction_type = transaction_type.strip().upper()

    if transaction_type not in ("BUY", "SELL"):
        raise ValueError(
            "Transaction type must be BUY or SELL."
        )

    if (
        not isinstance(quantity, Real)
        or isinstance(quantity, bool)
        or not math.isfinite(quantity)
        or quantity <= 0
    ):
        raise ValueError(
            "Quantity must be greater than 0."
        )

    if (
        not isinstance(price, Real)
        or isinstance(price, bool)
        or not math.isfinite(price)
        or price < 0
    ):
        raise ValueError(
            "Price cannot be negative."
        )

    _validate_date(
        transaction_date,
        "Transaction date",
    )

    # ---------------------------------------------------------
    # 2. SELL validation BEFORE database insertion
    # ---------------------------------------------------------

    if transaction_type == "SELL":

        existing_transactions = get_transactions()
        opening_positions = get_opening_positions()

        # Calculate the portfolio state before this new SELL.
        positions = calculate_positions(
            existing_transactions,
            opening_positions,
        )

        available_quantity = positions.get(
            symbol,
            {}
        ).get(
            "current_quantity",
            0,
        )

        if available_quantity <= 0:
            raise ValueError(
                f"Cannot sell {quantity} shares of {symbol}. "
                f"No shares are currently available."
            )

        if quantity > available_quantity:
            raise ValueError(
                f"Cannot sell {quantity} shares of {symbol}. "
                f"Only {available_quantity} shares are available."
            )

    # ---------------------------------------------------------
    # 3. Insert only after ALL validation passes
    # ---------------------------------------------------------

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT INTO transactions
            (
                symbol,
                company_name,
                transaction_type,
                quantity,
                price,
                transaction_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                company_name,
                transaction_type,
                quantity,
                price,
                transaction_date,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    print(
        f"Added {transaction_type}: "
        f"{quantity} × {symbol} @ ₹{price:.2f}"
    )

def get_transactions():
    """Return all transactions ordered chronologically."""

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            id,
            symbol,
            company_name,
            transaction_type,
            quantity,
            price,
            transaction_date
        FROM transactions
        ORDER BY transaction_date, id
        """
    ).fetchall()

    conn.close()

    return rows


def display_transactions():
    """Display transaction history."""

    transactions = get_transactions()

    if not transactions:
        print("No transactions found.")
        return

    print("\n===== TRANSACTION HISTORY =====")

    for transaction in transactions:

        (
            transaction_id,
            symbol,
            company_name,
            transaction_type,
            quantity,
            price,
            transaction_date,
        ) = transaction

        value = quantity * price

        print(
            f"\nID: {transaction_id}"
            f"\nSymbol: {symbol}"
            f"\nCompany: {company_name}"
            f"\nType: {transaction_type}"
            f"\nQuantity: {quantity}"
            f"\nPrice: ₹{price:.2f}"
            f"\nTransaction Value: ₹{value:.2f}"
            f"\nDate: {transaction_date}"
        )


def calculate_portfolio_valuation(price_overrides=None):
    """
    Calculate current portfolio value using the latest
    available market prices.

    Returns:
        dict containing:

        positions
        total_invested
        total_current_value
        total_realized_pnl
        total_unrealized_pnl
        total_pnl
        total_return_percent
    """

    transactions = get_transactions()
    opening_positions = get_opening_positions()

    positions = calculate_positions(
        transactions,
        opening_positions,
    )

    valuation = {}

    total_invested = 0.0
    total_current_value = 0.0
    total_realized_pnl = 0.0

    for symbol, position in positions.items():

        quantity = position["current_quantity"]

        realized_pnl = position["realized_pnl"]

        total_realized_pnl += realized_pnl

        # No current holding remains.
        if quantity <= 0:

            valuation[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "average_buy_price": None,
                "invested_amount": 0.0,
                "remaining_cost_basis": 0.0,
                "current_price": None,
                "current_value": 0.0,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": 0.0,
                "total_pnl": realized_pnl,
                "return_percent": None,
                "market_timestamp": None,
                "source": None,
                "retrieved_at": None,
                "currency": None,
                "exchange": None,
            }

            continue

        if price_overrides and symbol in price_overrides:
            current_price = float(price_overrides[symbol])

            quote = {
                "price": current_price,
                "market_timestamp": None,
                "source": "test override",
                "retrieved_at": None,
                "currency": None,
                "exchange": None,
            }
        else:
            quote = get_yahoo_quote(symbol)

        current_price = quote["price"]

        average_buy_price = position["average_buy_price"]

        # This is the actual remaining cost basis after
        # accounting for previous SELL transactions.
        invested_amount = position["remaining_cost_basis"]

        current_value = quantity * current_price

        unrealized_pnl = (
            current_value - invested_amount
        )

        total_pnl = (
            realized_pnl + unrealized_pnl
        )

        if invested_amount > 0:
            return_percent = (
                unrealized_pnl / invested_amount
            ) * 100
        else:
            return_percent = None

        valuation[symbol] = {
            "symbol": symbol,
            "quantity": quantity,
            "average_buy_price": average_buy_price,
            "invested_amount": invested_amount,
            "remaining_cost_basis": invested_amount,
            "current_price": current_price,
            "current_value": current_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,
            "return_percent": return_percent,
            "market_timestamp": quote["market_timestamp"],
            "source": quote["source"],
            "retrieved_at": quote.get("retrieved_at"),
            "currency": quote.get("currency"),
            "exchange": quote.get("exchange"),
        }

        total_invested += invested_amount
        total_current_value += current_value

    total_unrealized_pnl = (
        total_current_value - total_invested
    )

    total_pnl = (
        total_realized_pnl + total_unrealized_pnl
    )

    if total_invested > 0:

        total_return_percent = (
            total_unrealized_pnl
            / total_invested
        ) * 100

    else:
        total_return_percent = None

    return {
        "positions": valuation,
        "total_invested": total_invested,
        "total_current_value": total_current_value,
        "total_realized_pnl": total_realized_pnl,
        "total_unrealized_pnl": total_unrealized_pnl,
        "total_pnl": total_pnl,
        "total_return_percent": total_return_percent,
    }


def display_portfolio_valuation():
    """Display the current portfolio valuation."""

    portfolio = calculate_portfolio_valuation()

    print("\n" + "=" * 60)
    print("              CURRENT PORTFOLIO")
    print("=" * 60)

    for symbol, data in portfolio["positions"].items():

        print(f"\n{symbol}")
        print("-" * 40)

        print(
            f"Quantity           : "
            f"{data['quantity']:,.2f}"
        )

        if data["current_price"] is not None:

            print(
                f"Average Buy Price : "
                f"₹{data['average_buy_price']:,.2f}"
            )

            print(
                f"Current Price     : "
                f"₹{data['current_price']:,.2f}"
            )

            print(
                f"Remaining Cost    : "
                f"₹{data['remaining_cost_basis']:,.2f}"
            )

            print(
                f"Current Value     : "
                f"₹{data['current_value']:,.2f}"
            )

            print(
                f"Realized P&L      : "
                f"₹{data['realized_pnl']:,.2f}"
            )

            print(
                f"Unrealized P&L    : "
                f"₹{data['unrealized_pnl']:,.2f}"
            )

            print(
                f"Total P&L         : "
                f"₹{data['total_pnl']:,.2f}"
            )

            if data["return_percent"] is not None:

                print(
                    f"Unrealized Return : "
                    f"{data['return_percent']:.2f}%"
                )

            print(
                f"Market Timestamp  : "
                f"{data['market_timestamp']}"
            )

            print(
                f"Price Source      : "
                f"{data['source']}"
            )

        else:

            print(
                f"Realized P&L      : "
                f"₹{data['realized_pnl']:,.2f}"
            )

    print("\n" + "=" * 60)
    print("PORTFOLIO TOTAL")
    print("=" * 60)

    print(
        f"Current Cost Basis: "
        f"₹{portfolio['total_invested']:,.2f}"
    )

    print(
        f"Current Value     : "
        f"₹{portfolio['total_current_value']:,.2f}"
    )

    print(
        f"Realized P&L      : "
        f"₹{portfolio['total_realized_pnl']:,.2f}"
    )

    print(
        f"Unrealized P&L    : "
        f"₹{portfolio['total_unrealized_pnl']:,.2f}"
    )

    print(
        f"Total P&L         : "
        f"₹{portfolio['total_pnl']:,.2f}"
    )

    if portfolio["total_return_percent"] is not None:

        print(
            f"Unrealized Return : "
            f"{portfolio['total_return_percent']:.2f}%"
        )

    print("=" * 60)

def save_portfolio_snapshot(
    snapshot_date,
    total_invested,
    total_current_value,
    total_realized_pnl,
    total_unrealized_pnl,
    total_pnl,
    total_return_percent,
    holding_positions,
):
    """
    Save a portfolio snapshot for a specific date.

    Only one snapshot is allowed per date.
    """

    company_names = {
        row[1].strip().upper(): row[2]
        for row in get_opening_positions()
    }
    for row in get_transactions():
        company_names[row[1].strip().upper()] = row[2]
    holding_snapshot = json.dumps(
        _build_holding_snapshot(
            holding_positions,
            total_current_value,
            company_names,
        ),
        sort_keys=True,
        allow_nan=False,
    )

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_date,
                total_invested,
                total_current_value,
                total_realized_pnl,
                total_unrealized_pnl,
                total_pnl,
                total_return_percent,
                holding_snapshot_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date)
            DO UPDATE SET
                total_invested = excluded.total_invested,
                total_current_value = excluded.total_current_value,
                total_realized_pnl = excluded.total_realized_pnl,
                total_unrealized_pnl = excluded.total_unrealized_pnl,
                total_pnl = excluded.total_pnl,
                total_return_percent = excluded.total_return_percent,
                holding_snapshot_json = COALESCE(
                    excluded.holding_snapshot_json,
                    portfolio_snapshots.holding_snapshot_json
                )
            """,
            (
                snapshot_date,
                total_invested,
                total_current_value,
                total_realized_pnl,
                total_unrealized_pnl,
                total_pnl,
                total_return_percent,
                holding_snapshot,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def _build_holding_snapshot(positions, total_current_value, company_names):
    snapshot = {}
    for symbol, position in positions.items():
        normalized_symbol = symbol.strip().upper()
        current_value = float(position["current_value"])
        company_name = (
            position.get("company_name")
            or company_names.get(normalized_symbol)
        )
        if not company_name:
            raise ValueError(
                f"Company name is unavailable for holding {normalized_symbol}."
            )
        snapshot[normalized_symbol] = {
            "symbol": normalized_symbol,
            "company_name": company_name,
            "quantity": float(position["quantity"]),
            "current_price": (
                float(position["current_price"])
                if position.get("current_price") is not None
                else None
            ),
            "market_value": current_value,
            "remaining_cost_basis": float(position["remaining_cost_basis"]),
            "unrealized_pnl": float(position["unrealized_pnl"]),
            "total_pnl": float(position["total_pnl"]),
            "allocation_percent": (
                current_value / total_current_value * 100
                if total_current_value > 0
                else 0.0
            ),
        }
    return snapshot


def get_portfolio_snapshots():
    """
    Return all portfolio snapshots ordered by date.
    """

    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            SELECT
                id,
                snapshot_date,
                total_invested,
                total_current_value,
                total_realized_pnl,
                total_unrealized_pnl,
                total_pnl,
                total_return_percent,
                created_at,
                holding_snapshot_json
            FROM portfolio_snapshots
            ORDER BY snapshot_date ASC
            """
        )

        return cursor.fetchall()

    finally:
        conn.close()

def record_current_portfolio_snapshot(
    snapshot_date,
    price_overrides=None,
):
    """
    Calculate the current portfolio valuation and save it
    as a portfolio snapshot.
    """

    portfolio = calculate_portfolio_valuation(
        price_overrides=price_overrides
    )

    save_portfolio_snapshot(
        snapshot_date=snapshot_date,
        total_invested=portfolio["total_invested"],
        total_current_value=portfolio["total_current_value"],
        total_realized_pnl=portfolio["total_realized_pnl"],
        total_unrealized_pnl=portfolio["total_unrealized_pnl"],
        total_pnl=portfolio["total_pnl"],
        total_return_percent=portfolio["total_return_percent"],
        holding_positions=portfolio["positions"],
    )

    return portfolio

def get_portfolio_performance_history():
    """
    Return historical portfolio performance from saved snapshots.

    Each entry contains:
        - date
        - invested amount
        - current value
        - realized P&L
        - unrealized P&L
        - total P&L
        - return percentage
    """

    snapshots = get_portfolio_snapshots()

    history = []

    for snapshot in snapshots:
        history.append(
            {
                "date": snapshot[1],
                "total_invested": snapshot[2],
                "total_current_value": snapshot[3],
                "total_realized_pnl": snapshot[4],
                "total_unrealized_pnl": snapshot[5],
                "total_pnl": snapshot[6],
                "total_return_percent": snapshot[7],
            }
        )

    return history

def calculate_snapshot_changes(history=None):
    """
    Calculate portfolio value changes between consecutive snapshots.

    The first snapshot has no previous value, so its changes are None.
    """

    if history is None:
        history = get_portfolio_performance_history()
    results = []

    previous_value = None

    for snapshot in history:
        current_value = snapshot["total_current_value"]

        if previous_value is None:
            value_change = None
            value_change_percent = None
        else:
            value_change = current_value - previous_value

            if previous_value == 0:
                value_change_percent = None
            else:
                value_change_percent = (
                    value_change / previous_value
                ) * 100

        results.append(
            {
                **snapshot,
                "previous_value": previous_value,
                "value_change": value_change,
                "value_change_percent": value_change_percent,
            }
        )

        previous_value = current_value

    return results

def calculate_max_drawdown(history=None):
    """
    Calculate the maximum peak-to-trough drawdown
    from recorded portfolio snapshots.

    Returns:
        {
            "max_drawdown_amount": float,
            "max_drawdown_percent": float,
            "peak_date": str | None,
            "trough_date": str | None,
        }
    """

    if history is None:
        history = get_portfolio_performance_history()

    if not history:
        return {
            "max_drawdown_amount": 0,
            "max_drawdown_percent": 0,
            "peak_date": None,
            "trough_date": None,
        }

    peak_value = history[0]["total_current_value"]
    peak_date = history[0]["date"]

    max_drawdown_amount = 0
    max_drawdown_percent = 0
    max_peak_date = None
    max_trough_date = None

    for snapshot in history:
        current_value = snapshot["total_current_value"]

        if current_value > peak_value:
            peak_value = current_value
            peak_date = snapshot["date"]

        drawdown_amount = peak_value - current_value

        if peak_value == 0:
            drawdown_percent = 0
        else:
            drawdown_percent = (
                drawdown_amount / peak_value
            ) * 100

        if drawdown_percent > max_drawdown_percent:
            max_drawdown_percent = drawdown_percent
            max_drawdown_amount = drawdown_amount
            max_peak_date = peak_date
            max_trough_date = snapshot["date"]

    return {
        "max_drawdown_amount": max_drawdown_amount,
        "max_drawdown_percent": max_drawdown_percent,
        "peak_date": max_peak_date,
        "trough_date": max_trough_date,
    }

def calculate_portfolio_allocation(price_overrides=None):
    """
    Calculate each holding's percentage of the current portfolio value.

    Returns:
        {
            "SYMBOL": {
                "current_value": float,
                "allocation_percent": float,
            }
        }
    """

    portfolio = calculate_portfolio_valuation(
        price_overrides=price_overrides
    )

    total_value = portfolio["total_current_value"]

    allocation = {}

    for symbol, position in portfolio["positions"].items():
        current_value = position["current_value"]

        if total_value == 0:
            allocation_percent = 0
        else:
            allocation_percent = (
                current_value / total_value
            ) * 100

        allocation[symbol] = {
            "current_value": current_value,
            "allocation_percent": allocation_percent,
        }

    return allocation

def calculate_portfolio_concentration(price_overrides=None):
    """
    Calculate basic portfolio concentration metrics.

    Returns:
        {
            "holding_count": int,
            "largest_holding_symbol": str or None,
            "largest_holding_percent": float,
            "largest_holding_value": float,
        }
    """

    allocation = calculate_portfolio_allocation(
        price_overrides=price_overrides
    )

    if not allocation:
        return {
            "holding_count": 0,
            "largest_holding_symbol": None,
            "largest_holding_percent": 0,
            "largest_holding_value": 0,
        }

    largest_symbol = max(
        allocation,
        key=lambda symbol: allocation[symbol]["allocation_percent"],
    )

    largest_holding = allocation[largest_symbol]

    return {
        "holding_count": len(allocation),
        "largest_holding_symbol": largest_symbol,
        "largest_holding_percent": largest_holding[
            "allocation_percent"
        ],
        "largest_holding_value": largest_holding[
            "current_value"
        ],
    }

def get_portfolio_analytics_summary(price_overrides=None):
    """
    Return a consolidated portfolio analytics summary.

    Combines allocation, concentration, and drawdown metrics.
    """

    allocation = calculate_portfolio_allocation(
        price_overrides=price_overrides
    )

    concentration = calculate_portfolio_concentration(
        price_overrides=price_overrides
    )

    drawdown = calculate_max_drawdown()

    return {
        "allocation": allocation,
        "concentration": concentration,
        "max_drawdown": drawdown,
    }

def get_historical_performance_summary(history=None):
    """
    Return a summary of historical portfolio performance
    based on saved portfolio snapshots.
    """

    if history is None:
        history = get_portfolio_performance_history()

    if not history:
        return {
            "starting_value": 0,
            "latest_value": 0,
            "value_change": 0,
            "value_change_percent": 0,
            "highest_value": 0,
            "lowest_value": 0,
            "starting_date": None,
            "latest_date": None,
            "highest_value_date": None,
            "lowest_value_date": None,
        }

    starting = history[0]
    latest = history[-1]

    values = [
        snapshot["total_current_value"]
        for snapshot in history
    ]

    highest = max(
        history,
        key=lambda snapshot: snapshot["total_current_value"],
    )

    lowest = min(
        history,
        key=lambda snapshot: snapshot["total_current_value"],
    )

    starting_value = starting["total_current_value"]
    latest_value = latest["total_current_value"]

    value_change = latest_value - starting_value

    if starting_value == 0:
        value_change_percent = 0
    else:
        value_change_percent = (
            value_change / starting_value
        ) * 100

    return {
        "starting_value": starting_value,
        "latest_value": latest_value,
        "value_change": value_change,
        "value_change_percent": value_change_percent,
        "highest_value": highest["total_current_value"],
        "lowest_value": lowest["total_current_value"],
        "starting_date": starting["date"],
        "latest_date": latest["date"],
        "highest_value_date": highest["date"],
        "lowest_value_date": lowest["date"],
    }

def get_dashboard_data(price_overrides=None):
    """
    Return all portfolio data required by the dashboard.

    Combines portfolio valuation, analytics, allocation,
    concentration, and historical performance.
    """

    portfolio = calculate_portfolio_valuation(
        price_overrides=price_overrides
    )

    analytics = get_portfolio_analytics_summary(
        price_overrides=price_overrides
    )

    historical = get_historical_performance_summary()

    history = get_portfolio_performance_history()

    return {
        "portfolio": portfolio,
        "analytics": analytics,
        "historical": {
            **historical,
            "history": history,
        },
    }

def get_portfolio_alerts(price_overrides=None):
    portfolio = calculate_portfolio_valuation(
        price_overrides=price_overrides
    )

    alerts = []

    for symbol, position in portfolio["positions"].items():

        if position["unrealized_pnl"] < 0:
            alerts.append(
                {
                    "type": "negative_pnl",
                    "symbol": symbol,
                    "message": (
                        f"{symbol} currently has a negative "
                        f"unrealized P&L of "
                        f"₹{position['unrealized_pnl']:.2f}."
                    ),
                }
            )

    concentration = calculate_portfolio_concentration(
        price_overrides=price_overrides
    )

    if concentration["largest_holding_percent"] >= 50:
        alerts.append(
            {
                "type": "concentration",
                "symbol": concentration["largest_holding_symbol"],
                "message": (
                    f"{concentration['largest_holding_symbol']} "
                    f"represents "
                    f"{concentration['largest_holding_percent']:.2f}% "
                    f"of the portfolio value."
                ),
            }
        )

    return alerts

if __name__ == "__main__":
    display_portfolio_valuation()