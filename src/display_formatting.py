import pandas as pd


MONEY_COLUMN_HINTS = (
    "money", "amount", "price", "revenue", "sales", "cost", "profit",
    "discount", "tax", "fee", "balance", "income", "payment", "expense",
    "cash", "salary", "wage", "commission", "refund", "subtotal", "capital",
    "budget", "value", "currency", "ghs", "cedi",
)
NON_AMOUNT_HINTS = (
    "percent", "percentage", "ratio", "qty", "quantity", "count", "units sold",
    "items sold", "orders", "records", "age", "year", "day", "night", "hour",
    "month", "week", "margin", "rate", " id", "code", "sku",
)


def is_monetary_column(column_name):
    column = str(column_name).lower().replace("_", " ").replace("-", " ")
    return any(hint in column for hint in MONEY_COLUMN_HINTS) and not any(
        hint in column for hint in NON_AMOUNT_HINTS
    )


def format_numeric_value(value, column_name, currency_symbol="₵"):
    """Format one displayed numeric result without changing its stored value."""
    if pd.isna(value):
        return ""

    if is_monetary_column(column_name):
        return f"{currency_symbol}{value:,.2f}"
    return f"{value:,.0f}"


def format_numeric_dataframe(df):
    """Return a presentation copy with readable numeric strings for left alignment."""
    display_df = df.copy()
    for column in display_df.columns:
        if pd.api.types.is_numeric_dtype(display_df[column]):
            display_df[column] = display_df[column].map(
                lambda value, name=column: format_numeric_value(value, name)
            ).astype("string")
    return display_df
