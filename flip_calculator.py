from config import PLATFORM_FEE_PERCENT, TRANSPORT_COST_EUR, TIME_COST_EUR, MIN_FLIP_MARGIN_EUR


def calculate_flip_margin(buy_price: float, resale_min: float, resale_max: float) -> dict:
    """Calculate net margin for a flip opportunity.

    Uses expected margin (mid) for the alert decision.
    Reports conservative, mid, and optimistic scenarios.
    """
    resale_mid = (resale_min + resale_max) / 2

    # Costs that apply to every flip
    platform_fee = resale_mid * PLATFORM_FEE_PERCENT
    total_cost = buy_price + platform_fee + TRANSPORT_COST_EUR + TIME_COST_EUR

    margin_conservative = resale_min - total_cost  # worst case
    margin_mid = resale_mid - total_cost           # expected
    margin_optimistic = resale_max - total_cost    # best case

    return {
        "buy_price": buy_price,
        "resale_min": resale_min,
        "resale_max": resale_max,
        "platform_fee": round(platform_fee, 2),
        "transport_cost": TRANSPORT_COST_EUR,
        "time_cost": TIME_COST_EUR,
        "total_cost": round(total_cost, 2),
        "margin_conservative": round(margin_conservative, 2),
        "margin_mid": round(margin_mid, 2),
        "margin_optimistic": round(margin_optimistic, 2),
        "is_worth_it": margin_mid >= MIN_FLIP_MARGIN_EUR,
        "roi_percent": round((margin_mid / buy_price) * 100, 1) if buy_price > 0 else 0,
    }
