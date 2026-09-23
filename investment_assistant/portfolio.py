from datetime import datetime
import math
import re
from numbers import Real

from investment_assistant.database import get_connection


def calculate_positions(transactions, opening_positions=()):
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
                "is_zero_quantity": False,
            },
        )

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

        position = get_position(symbol.strip().upper())
        position["total_buy_quantity"] += quantity
        position["total_buy_cost"] += invested_amount

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
        position = get_position(symbol)

        if transaction_type == "BUY":
            position["total_buy_quantity"] += quantity
            position["total_buy_cost"] += quantity * price
        elif transaction_type == "SELL":
            position["total_sell_quantity"] += quantity
            position["total_sell_proceeds"] += quantity * price
        else:
            raise ValueError("Transaction type must be BUY or SELL.")

    for position in positions.values():
        position["current_quantity"] = (
            position["total_buy_quantity"] - position["total_sell_quantity"]
        )
        if position["total_buy_quantity"] > 0:
            position["average_buy_price"] = (
                position["total_buy_cost"] / position["total_buy_quantity"]
            )
        position["is_zero_quantity"] = position["current_quantity"] == 0

    return positions


def _validate_date(value, field_name):
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    ):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")
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
        rel_tol=1e-09,
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
        (symbol, company_name, quantity, average_cost, invested_amount, purchase_date)
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
    transaction_date
):
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol cannot be empty.")

    if not isinstance(company_name, str) or not company_name.strip():
        raise ValueError("Company name cannot be empty.")

    if not isinstance(transaction_type, str):
        raise ValueError("Transaction type must be BUY or SELL.")

    symbol = symbol.strip().upper()
    company_name = company_name.strip()
    transaction_type = transaction_type.upper()

    if transaction_type not in ("BUY", "SELL"):
        raise ValueError("Transaction type must be BUY or SELL.")

    if (
        not isinstance(quantity, Real)
        or isinstance(quantity, bool)
        or not math.isfinite(quantity)
        or quantity <= 0
    ):
        raise ValueError("Quantity must be greater than 0.")

    if (
        not isinstance(price, Real)
        or isinstance(price, bool)
        or not math.isfinite(price)
        or price < 0
    ):
        raise ValueError("Price cannot be negative.")

    _validate_date(transaction_date, "Transaction date")

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO transactions
        (symbol, company_name, transaction_type, quantity, price, transaction_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            symbol.upper(),
            company_name,
            transaction_type,
            quantity,
            price,
            transaction_date
        )
    )

    conn.commit()
    conn.close()

    print(
        f"Added {transaction_type}: "
        f"{quantity} × {symbol.upper()} @ ₹{price:.2f}"
    )


def get_transactions():
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
            transaction_date
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

from investment_assistant.market_data import get_yahoo_quote


def calculate_portfolio_valuation():
    """
    Calculate the current portfolio value and unrealized P&L
    using the latest available market prices.

    Returns:
        dict containing:
            positions
            total_invested
            total_current_value
            total_unrealized_pnl
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

    for symbol, position in positions.items():

        quantity = position["current_quantity"]

        # If no shares/units remain, there is no current holding
        # to value.
        if quantity <= 0:
            valuation[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "average_buy_price": position["average_buy_price"],
                "invested_amount": 0.0,
                "current_price": None,
                "current_value": 0.0,
                "unrealized_pnl": 0.0,
                "return_percent": None,
                "market_timestamp": None,
                "source": None,
            }
            continue

        quote = get_yahoo_quote(symbol)

        current_price = quote["price"]

        average_buy_price = position["average_buy_price"]

        invested_amount = quantity * average_buy_price
        current_value = quantity * current_price
        unrealized_pnl = current_value - invested_amount

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
            "current_price": current_price,
            "current_value": current_value,
            "unrealized_pnl": unrealized_pnl,
            "return_percent": return_percent,
            "market_timestamp": quote["market_timestamp"],
            "source": quote["source"],
        }

        total_invested += invested_amount
        total_current_value += current_value

    total_unrealized_pnl = (
        total_current_value - total_invested
    )

    if total_invested > 0:
        total_return_percent = (
            total_unrealized_pnl / total_invested
        ) * 100
    else:
        total_return_percent = None

    return {
        "positions": valuation,
        "total_invested": total_invested,
        "total_current_value": total_current_value,
        "total_unrealized_pnl": total_unrealized_pnl,
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
                f"Invested Amount   : "
                f"₹{data['invested_amount']:,.2f}"
            )

            print(
                f"Current Value     : "
                f"₹{data['current_value']:,.2f}"
            )

            print(
                f"Unrealized P&L    : "
                f"₹{data['unrealized_pnl']:,.2f}"
            )

            if data["return_percent"] is not None:
                print(
                    f"Return            : "
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

    print("\n" + "=" * 60)
    print("PORTFOLIO TOTAL")
    print("=" * 60)

    print(
        f"Total Invested    : "
        f"₹{portfolio['total_invested']:,.2f}"
    )

    print(
        f"Current Value     : "
        f"₹{portfolio['total_current_value']:,.2f}"
    )

    print(
        f"Unrealized P&L    : "
        f"₹{portfolio['total_unrealized_pnl']:,.2f}"
    )

    if portfolio["total_return_percent"] is not None:
        print(
            f"Total Return      : "
            f"{portfolio['total_return_percent']:.2f}%"
        )

    print("=" * 60)


if __name__ == "__main__":
    display_portfolio_valuation()