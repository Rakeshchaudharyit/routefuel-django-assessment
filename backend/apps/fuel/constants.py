"""Reference values used to validate fuel-price data."""

from decimal import Decimal

# 50 states + DC. The routing API only accepts US trips.
US_STATE_CODES: frozenset[str] = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
        "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
        "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
        "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    }
)  # fmt: skip

# Canadian provinces/territories appear in the supplied CSV. They are recognised so they
# can be reported as out-of-scope rather than as invalid data.
CANADIAN_PROVINCE_CODES: frozenset[str] = frozenset(
    {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
)

# Sanity bounds for a US retail diesel price in USD per gallon. Values outside this range
# are treated as data errors, not prices.
MIN_RETAIL_PRICE = Decimal("0.50")
MAX_RETAIL_PRICE = Decimal("20.00")

# The CSV carries up to 8 decimal places (averaged prices such as 3.00733333).
# Prices are stored exactly; anything more precise is rejected rather than rounded.
PRICE_MAX_DIGITS = 10
PRICE_DECIMAL_PLACES = 8
