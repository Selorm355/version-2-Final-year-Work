import pandas as pd


def summarize_sales(
    df,
    product_column=None,
    quantity_column=None,
    sales_column=None,
    unit_price_column=None,
    cost_column=None,
    unit_cost_column=None,
    discount_column=None,
    discount_type="Amount",
    product_filter="",
):
    """Build overall product sales, profit, quantity, and discount summaries."""
    quantity = pd.to_numeric(df[quantity_column], errors="coerce") if quantity_column else None
    sales = None
    if sales_column:
        sales = pd.to_numeric(df[sales_column], errors="coerce")
    elif unit_price_column and quantity is not None:
        sales = pd.to_numeric(df[unit_price_column], errors="coerce") * quantity

    cost = None
    if cost_column:
        cost = pd.to_numeric(df[cost_column], errors="coerce")
    elif unit_cost_column and quantity is not None:
        cost = pd.to_numeric(df[unit_cost_column], errors="coerce") * quantity

    working = pd.DataFrame(index=df.index)
    if product_column:
        working["Product"] = df[product_column].fillna("UNKNOWN").astype(str)
    if quantity is not None:
        working["Units Sold"] = quantity
    else:
        working["Units Sold"] = 1
    if sales is not None:
        working["Sales"] = sales
    if cost is not None:
        working["Cost"] = cost
    if sales is not None and cost is not None:
        working["Profit"] = sales - cost

    if discount_column:
        discount = pd.to_numeric(df[discount_column], errors="coerce")
        if discount_type == "Percentage":
            working["Discount %"] = discount
            if sales is not None:
                working["Discount Amount"] = sales * discount / 100
        else:
            working["Discount Amount"] = discount

    filter_text = product_filter.strip().casefold()
    if filter_text and "Product" in working:
        working = working[working["Product"].str.casefold() == filter_text]

    if working.empty:
        return working, {}

    summary = {}
    if sales is not None:
        summary["Sales"] = working["Sales"].sum()
    if cost is not None:
        summary["Cost"] = working["Cost"].sum()
    if "Profit" in working:
        summary["Profit"] = working["Profit"].sum()
    summary["Units Sold"] = working["Units Sold"].sum()
    if "Discount Amount" in working:
        summary["Discount Amount"] = working["Discount Amount"].sum()
    if "Discount %" in working:
        summary["Discount %"] = working["Discount %"].mean()

    if "Product" not in working:
        return working, summary

    aggregations = {column: "sum" for column in working.columns if column != "Product"}
    if "Discount %" in aggregations:
        aggregations["Discount %"] = "mean"
    product_summary = working.groupby("Product", dropna=False).agg(aggregations).reset_index()
    product_summary = product_summary.sort_values("Units Sold", ascending=False)
    return product_summary, summary