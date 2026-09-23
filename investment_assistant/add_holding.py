from investment_assistant.portfolio import add_transaction


def main():
    symbol = input("Stock/ETF symbol: ").strip()
    company_name = input("Company/ETF name: ").strip()
    quantity = float(input("Quantity: "))
    buy_price = float(input("Buy price per unit: ₹"))
    buy_date = input("Buy date (YYYY-MM-DD): ").strip()

    add_transaction(
        symbol=symbol,
        company_name=company_name,
        transaction_type="BUY",
        quantity=quantity,
        price=buy_price,
        transaction_date=buy_date,
    )


if __name__ == "__main__":
    main()