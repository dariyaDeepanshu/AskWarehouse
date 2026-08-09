"""
Generates the AskWarehouse synthetic e-commerce warehouse into
data/warehouse/warehouse.duckdb, schema `raw`.

Vectorized with numpy for the multi-million-row fact tables; Faker is only
used to build small lookup pools (names, cities, products) that get sampled
from, since calling Faker per-row for millions of rows is too slow.

Deliberately messy in a few realistic ways so schema linking / staging
normalization has real work to do:
  - customers.signup_date_raw is text in two different formats
  - customers.phone is null ~15% of the time
  - products.category has inconsistent casing before staging normalizes it
  - customers.state is stored as USPS abbreviations (e.g. 'CA'), while
    business questions will say "California" -> this is what the value
    index is for.
"""
import duckdb
import numpy as np
import pandas as pd
from faker import Faker
import time
import argparse

SEED = 7
US_STATES = [
    ("AL","South"),("AK","West"),("AZ","West"),("AR","South"),("CA","West"),
    ("CO","West"),("CT","Northeast"),("DE","South"),("FL","South"),("GA","South"),
    ("HI","West"),("ID","West"),("IL","Midwest"),("IN","Midwest"),("IA","Midwest"),
    ("KS","Midwest"),("KY","South"),("LA","South"),("ME","Northeast"),("MD","South"),
    ("MA","Northeast"),("MI","Midwest"),("MN","Midwest"),("MS","South"),("MO","Midwest"),
    ("MT","West"),("NE","Midwest"),("NV","West"),("NH","Northeast"),("NJ","Northeast"),
    ("NM","West"),("NY","Northeast"),("NC","South"),("ND","Midwest"),("OH","Midwest"),
    ("OK","South"),("OR","West"),("PA","Northeast"),("RI","Northeast"),("SC","South"),
    ("SD","Midwest"),("TN","South"),("TX","South"),("UT","West"),("VT","Northeast"),
    ("VA","South"),("WA","West"),("WV","South"),("WI","Midwest"),("WY","West"),
]
STATE_CODES = np.array([s for s, _ in US_STATES])
STATE_REGION = {s: r for s, r in US_STATES}

CATEGORIES = {
    "Electronics": ["Laptops", "Headphones", "Smart Home", "Cameras", "Accessories"],
    "Apparel": ["Men's", "Women's", "Kids", "Footwear", "Outerwear"],
    "Home & Kitchen": ["Cookware", "Furniture", "Bedding", "Decor", "Appliances"],
    "Beauty": ["Skincare", "Makeup", "Haircare", "Fragrance"],
    "Sports & Outdoors": ["Fitness", "Camping", "Cycling", "Team Sports"],
    "Toys & Games": ["Building Sets", "Puzzles", "Action Figures", "Board Games"],
    "Grocery": ["Snacks", "Beverages", "Pantry", "Fresh"],
}
BRANDS = ["Northline", "Kesto", "Verdant", "Amber&Co", "Pulsewear", "Grovemark",
          "Solace", "Ridgeforge", "Bluepeak", "Coastal Union", "Ironvale", "Lumio"]
CHANNELS = ["online", "retail", "marketplace"]
ACQ_CHANNELS = ["organic", "paid_search", "paid_social", "email", "referral", "affiliate"]
ORDER_STATUS_P = {"completed": 0.80, "cancelled": 0.07, "returned": 0.08, "pending": 0.05}
PAYMENT_METHODS = ["credit_card", "paypal", "gift_card", "bank_transfer", "buy_now_pay_later"]
CAMPAIGN_CHANNELS = ["email", "paid_social", "search", "display", "influencer"]
TOUCH_TYPES_P = {"impression": 0.70, "click": 0.24, "conversion": 0.06}


def weighted_choice(rng, options_p, n):
    keys = list(options_p.keys())
    p = np.array(list(options_p.values()))
    p = p / p.sum()
    return rng.choice(keys, size=n, p=p)


def main(scale: str):
    if scale == "small":
        n_customers, n_products, n_stores, n_campaigns, n_orders = 20_000, 1_500, 40, 60, 120_000
    elif scale == "medium":
        n_customers, n_products, n_stores, n_campaigns, n_orders = 100_000, 4_000, 120, 150, 900_000
    else:  # full
        n_customers, n_products, n_stores, n_campaigns, n_orders = 250_000, 6_000, 180, 250, 3_000_000

    t0 = time.time()
    rng = np.random.default_rng(SEED)
    fake = Faker()
    Faker.seed(SEED)

    print(f"[1/8] customers: {n_customers:,}")
    # small pools sampled with replacement -> realistic name collisions, fast
    pool_n = min(20_000, n_customers)
    first_names = [fake.first_name() for _ in range(pool_n)]
    last_names = [fake.last_name() for _ in range(pool_n)]
    cities = [fake.city() for _ in range(pool_n)]
    fn = rng.choice(first_names, n_customers)
    ln = rng.choice(last_names, n_customers)
    city = rng.choice(cities, n_customers)
    state = rng.choice(STATE_CODES, n_customers, p=None)
    country = rng.choice(["US"] * 95 + ["CA"] * 4 + ["MX"] * 1, n_customers)
    signup_days_ago = rng.integers(1, 365 * 4, n_customers)
    signup_dt = pd.Timestamp.today().normalize() - pd.to_timedelta(signup_days_ago, unit="D")
    # ~15% of signup dates rendered in a different text format (dirty source system)
    fmt_a = signup_dt.strftime("%Y-%m-%d")
    fmt_b = signup_dt.strftime("%m/%d/%Y")
    messy_mask = rng.random(n_customers) < 0.15
    signup_date_raw = np.where(messy_mask, fmt_b, fmt_a)
    phone = np.array([fake.phone_number() for _ in range(pool_n)])[rng.integers(0, pool_n, n_customers)]
    phone_null_mask = rng.random(n_customers) < 0.15
    phone = np.where(phone_null_mask, None, phone)
    birth_dt = pd.Timestamp.today().normalize() - pd.to_timedelta(rng.integers(18*365, 75*365, n_customers), unit="D")
    birth_null = rng.random(n_customers) < 0.08
    birth_date = pd.Series(birth_dt).where(~birth_null, pd.NaT)

    customers = pd.DataFrame({
        "customer_id": np.arange(1, n_customers + 1),
        "first_name": fn,
        "last_name": ln,
        "email": [f"{a}.{b}{i}@{d}".lower() for a, b, i, d in zip(
            fn, ln, range(n_customers),
            rng.choice(["gmail.com", "yahoo.com", "outlook.com", "mail.com"], n_customers))],
        "phone": phone,
        "city": city,
        "state": state,
        "country": country,
        "signup_date_raw": signup_date_raw,
        "birth_date": birth_date.values,
        "is_marketing_opt_in": rng.random(n_customers) < 0.55,
        "acquisition_channel": rng.choice(ACQ_CHANNELS, n_customers,
                                           p=[0.30, 0.22, 0.18, 0.12, 0.10, 0.08]),
    })

    print(f"[2/8] products: {n_products:,}")
    cats = list(CATEGORIES.keys())
    cat_choice = rng.choice(cats, n_products)
    subcat_choice = np.array([rng.choice(CATEGORIES[c]) for c in cat_choice])
    # inconsistent casing pre-staging-normalization on ~10% of rows
    cat_dirty_mask = rng.random(n_products) < 0.10
    cat_rendered = np.where(cat_dirty_mask, np.char.lower(cat_choice.astype(str)), cat_choice)
    brand = rng.choice(BRANDS, n_products)
    unit_cost = np.round(rng.gamma(shape=3.0, scale=8.0, size=n_products) + 2, 2)
    margin_mult = rng.uniform(1.4, 3.2, n_products)
    list_price = np.round(unit_cost * margin_mult, 2)
    launch_days_ago = rng.integers(1, 365 * 6, n_products)
    products = pd.DataFrame({
        "product_id": np.arange(1, n_products + 1),
        "sku": [f"SKU-{i:06d}" for i in range(1, n_products + 1)],
        "product_name": [f"{b} {sc} {suf}" for b, sc, suf in zip(
            brand, subcat_choice, rng.integers(100, 999, n_products))],
        "category": cat_rendered,
        "subcategory": subcat_choice,
        "brand": brand,
        "unit_cost": unit_cost,
        "list_price": list_price,
        "is_active": rng.random(n_products) < 0.92,
        "launch_date": (pd.Timestamp.today().normalize() - pd.to_timedelta(launch_days_ago, unit="D")).values,
    })

    print(f"[3/8] stores: {n_stores:,}")
    store_states = rng.choice(STATE_CODES, n_stores)
    stores = pd.DataFrame({
        "store_id": np.arange(1, n_stores + 1),
        "store_name": [f"{fake.city()} {ch.title()}" for ch in rng.choice(CHANNELS, n_stores)],
        "channel": rng.choice(CHANNELS, n_stores, p=[0.55, 0.35, 0.10]),
        "state": store_states,
        "region": [STATE_REGION[s] for s in store_states],
    })

    print(f"[4/8] campaigns: {n_campaigns:,}")
    camp_start_days_ago = rng.integers(30, 365 * 3, n_campaigns)
    camp_start = pd.Timestamp.today().normalize() - pd.to_timedelta(camp_start_days_ago, unit="D")
    camp_len = rng.integers(7, 60, n_campaigns)
    campaigns = pd.DataFrame({
        "campaign_id": np.arange(1, n_campaigns + 1),
        "campaign_name": [f"{ch.title()} Push {q}" for ch, q in zip(
            rng.choice(CAMPAIGN_CHANNELS, n_campaigns), rng.integers(1, 999, n_campaigns))],
        "channel": rng.choice(CAMPAIGN_CHANNELS, n_campaigns),
        "start_date": camp_start.values,
        "end_date": (camp_start + pd.to_timedelta(camp_len, unit="D")).values,
        "budget": np.round(rng.gamma(3, 4000, n_campaigns), 2),
    })

    print(f"[5/8] orders: {n_orders:,}")
    # mild recency skew + weekly seasonality so date-range questions have real signal
    order_days_ago = rng.exponential(scale=280, size=n_orders).astype(int)
    order_days_ago = np.clip(order_days_ago, 0, 365 * 4)
    order_ts = pd.Timestamp.today().normalize() - pd.to_timedelta(order_days_ago, unit="D")
    order_ts = order_ts + pd.to_timedelta(rng.integers(0, 86400, n_orders), unit="s")
    order_customer = rng.integers(1, n_customers + 1, n_orders)
    order_store = rng.integers(1, n_stores + 1, n_orders)
    orders = pd.DataFrame({
        "order_id": np.arange(1, n_orders + 1),
        "customer_id": order_customer,
        "store_id": order_store,
        "order_ts": order_ts.values,
        "order_status": weighted_choice(rng, ORDER_STATUS_P, n_orders),
        "channel": stores["channel"].values[order_store - 1],
        "currency": "USD",
    })

    print("[6/8] order_items (vectorized fan-out)")
    items_per_order = rng.poisson(2.1, n_orders) + 1
    total_items = int(items_per_order.sum())
    order_id_rep = np.repeat(orders["order_id"].values, items_per_order)
    item_product = rng.integers(1, n_products + 1, total_items)
    quantity = rng.integers(1, 5, total_items)
    base_price = products["list_price"].values[item_product - 1]
    discount_pct = np.round(rng.choice([0, 0, 0, 5, 10, 15, 20, 25], total_items) / 100, 2)
    discount_null_mask = discount_pct == 0
    unit_price = np.round(base_price * (1 - discount_pct), 2)
    order_items = pd.DataFrame({
        "order_item_id": np.arange(1, total_items + 1),
        "order_id": order_id_rep,
        "product_id": item_product,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": np.where(discount_null_mask, None, discount_pct),
    })
    print(f"       -> {total_items:,} order_items rows")

    print("[7/8] payments")
    order_item_totals = order_items.assign(line_total=order_items.quantity * order_items.unit_price) \
        .groupby("order_id")["line_total"].sum()
    pay_order_id = order_item_totals.index.values
    n_pay = len(pay_order_id)
    payments = pd.DataFrame({
        "payment_id": np.arange(1, n_pay + 1),
        "order_id": pay_order_id,
        "payment_method": rng.choice(PAYMENT_METHODS, n_pay, p=[0.55, 0.20, 0.08, 0.09, 0.08]),
        "amount": np.round(order_item_totals.values, 2),
        "payment_ts": orders.set_index("order_id").loc[pay_order_id, "order_ts"].values,
        "payment_status": rng.choice(["succeeded", "failed", "refunded"], n_pay, p=[0.93, 0.03, 0.04]),
    })

    print("[8/8] customer_campaign_touch")
    n_touch = min(int(n_customers * 3.2), 1_500_000)
    touch_customer = rng.integers(1, n_customers + 1, n_touch)
    touch_campaign = rng.integers(1, n_campaigns + 1, n_touch)
    camp_start_by_id = campaigns.set_index("campaign_id")["start_date"]
    touch_offset = rng.integers(0, 45, n_touch)
    touch_ts = pd.to_datetime(camp_start_by_id.loc[touch_campaign].values) + pd.to_timedelta(touch_offset, unit="D")
    touches = pd.DataFrame({
        "touch_id": np.arange(1, n_touch + 1),
        "customer_id": touch_customer,
        "campaign_id": touch_campaign,
        "touch_ts": touch_ts,
        "touch_type": weighted_choice(rng, TOUCH_TYPES_P, n_touch),
    })

    print("writing to DuckDB ...")
    import os
    os.makedirs("data/warehouse", exist_ok=True)
    con = duckdb.connect("data/warehouse/warehouse.duckdb")
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    for name, df in [
        ("raw.customers", customers), ("raw.products", products), ("raw.stores", stores),
        ("raw.campaigns", campaigns), ("raw.orders", orders), ("raw.order_items", order_items),
        ("raw.payments", payments), ("raw.customer_campaign_touch", touches),
    ]:
        con.register("df_tmp", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_tmp")
        con.unregister("df_tmp")
        print(f"  {name}: {len(df):,} rows")
    con.close()
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scale", choices=["small", "medium", "full"], default="full")
    args = p.parse_args()
    main(args.scale)
