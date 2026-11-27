"""Pure USD landed-cost accounting for the existing first-unit purchase evidence.

No price, stock, address, physical qualification or release is inferred here.
Use full quoted package costs and explicit seller charges; missing is not zero.
The strict procurement release still owns receipt verification.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NamedTuple
from urllib.parse import urlsplit

MAX_ACCOUNTING_USD = Decimal("1000000000000")
PROTOTYPE_CAP_CENTS = 5000


def cents(value: object, label: str) -> int:
    """Accept dollar strings or exact Decimal, never imprecise binary floats."""
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError(f"{label}: use an exact USD dollar amount")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label}: invalid USD amount") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label}: USD amount must be nonnegative cents")
    # Keep all supplier and prior-order amounts bounded before Decimal
    # arithmetic. An absurd exponent can otherwise raise decimal.Overflow
    # instead of producing a failed receipt.
    if number > MAX_ACCOUNTING_USD:
        raise ValueError(f"{label}: USD amount exceeds receipt bound")
    # Convert the exact representation without ambient Decimal rounding.
    # Strip only zero subcent digits; the bound keeps integer arithmetic small.
    if not number:
        return 0
    _, digits, exponent = number.as_tuple()
    cent_exponent = exponent + 2
    if cent_exponent < 0:
        if -cent_exponent >= len(digits) or any(digits[cent_exponent:]):
            raise ValueError(f"{label}: subcent amount")
        digits = digits[:cent_exponent]
        cent_exponent = 0
    coefficient = int("".join(map(str, digits)))
    return coefficient * 10**cent_exponent


def sum_line_cost_cents(lines: Iterable[tuple[int, int]]) -> int:
    """Sum validated (quantity, unit or package price in cents) pairs exactly."""
    return sum(quantity * price for quantity, price in lines)


def landed_total_cents(
    subtotal: int, *, shipping: int, tax: int, duties: int, discount: int,
) -> int:
    """Combine validated integer cents; callers own missing-charge policy."""
    total = subtotal + shipping + tax + duties - discount
    if total < 0:
        raise ValueError("discount exceeds seller total")
    return total


# A supplier may not inject arbitrary-precision counts into cost arithmetic.
# This limit exceeds every selected first-robot and five-pet role by far.
MAX_ACCOUNTING_UNITS = 10_000


def positive_count(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label}: expected a positive integer")
    if value > MAX_ACCOUNTING_UNITS:
        raise ValueError(f"{label}: quantity exceeds {MAX_ACCOUNTING_UNITS} unit bound")
    return value


def evidence_https_url(value: object) -> bool:
    """Reject ambiguous HTTPS evidence URLs before the parser normalizes them."""
    if not isinstance(value, str) or any(
        ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port != 0)
    except ValueError:
        return False


_url = evidence_https_url


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: missing identifier")
    if not value.isprintable():
        raise ValueError(f"{label}: nonprintable identifier")
    return value.strip()


def _quote_date(value: object) -> date:
    """Only a real, canonical ISO calendar date can date a supplier quote."""
    if not isinstance(value, str):
        raise ValueError("quote date must be a YYYY-MM-DD calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("quote date must be a YYYY-MM-DD calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError("quote date must be a YYYY-MM-DD calendar date")
    # A future-dated seller quote cannot be a completed historical checkout
    # receipt, even if its format and monetary arithmetic are valid.
    if parsed > date.today():
        raise ValueError("supplier quote date cannot be in the future")
    return parsed


# Historical evaluation remains useful. Actual first-unit/fleet quotes must
# include dated price and stock confirmations; a product URL alone is not a
# live supplier availability statement.
CURRENT_QUOTE_MAX_AGE_DAYS = 7
MAX_VALIDITY_DAYS = 30


def _seller_date(value: object, label: str, *, allow_future: bool = False) -> date:
    if type(value) is not str:
        raise ValueError(f"{label} must be a canonical ISO calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a canonical ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be a canonical ISO calendar date")
    if not allow_future and parsed > date.today():
        raise ValueError(f"{label} cannot be in the future")
    return parsed


def _current_checkout_quote(line: dict, quoted: date) -> None:
    """Bound claimed checkout freshness; release still needs verified receipts.

    Dates and HTTPS links do not independently authenticate seller stock,
    physical fit or the immutable signed release gate.
    """
    today = date.today()
    checked = _seller_date(line.get("stock_checked_at"), "stock_checked_at")
    if checked < quoted or (today - checked).days > CURRENT_QUOTE_MAX_AGE_DAYS:
        raise ValueError("stock check predates supplier quote or is stale")

    expiry = None
    if "quote_valid_through" in line:
        expiry = _seller_date(line["quote_valid_through"],
                              "quote_valid_through", allow_future=True)
        if expiry < quoted or (expiry - quoted).days > MAX_VALIDITY_DAYS:
            raise ValueError("seller quote exceeds 30-day validity window")
        if expiry < today:
            raise ValueError("seller quote has expired")

    reconfirmed = None
    if "price_reconfirmed_at" in line or "price_reconfirmation_url" in line:
        reconfirmed = _seller_date(line.get("price_reconfirmed_at"),
                                   "price_reconfirmed_at")
        if (not _url(line.get("price_reconfirmation_url"))
                or reconfirmed < quoted or checked < reconfirmed
                or (today - reconfirmed).days > CURRENT_QUOTE_MAX_AGE_DAYS):
            raise ValueError("price reconfirmation is stale or lacks supplier evidence")
    if ((today - quoted).days > CURRENT_QUOTE_MAX_AGE_DAYS
            and expiry is None and reconfirmed is None):
        raise ValueError("supplier quote is stale without current price proof")


class _QuoteTotals(NamedTuple):
    buckets: dict[str, int]
    supplied: defaultdict[str, int]
    seller_subtotals: defaultdict[str, int]
    seller_category_goods: defaultdict[str, defaultdict[str, int]]
    seller_category_units: defaultdict[str, defaultdict[str, int]]
    quote_packs_by_role: defaultdict[str, list[tuple[int, int, object]]]


def _parse_quote(
    line: dict, required_roles: dict[str, int], role_categories: dict[str, str],
    buckets: dict[str, int], expected_scope: str,
) -> tuple[str, str, str, str, int, int, str, int]:
    role = _nonempty(line.get("role_key"), "role_key")
    if role not in required_roles or required_roles[role] == 0:
        raise ValueError("unknown or excluded role")
    seller = _nonempty(line.get("seller"), "seller")
    sku = _nonempty(line.get("sku"), "sku")
    quote_ref = _nonempty(line.get("quote_reference"), "quote_reference")
    quoted = _quote_date(line.get("quoted_at"))
    if not _url(line.get("stock_evidence_url")):
        raise ValueError("missing HTTPS stock evidence")
    if expected_scope in {"first_robot", "fleet"}:
        _current_checkout_quote(line, quoted)
    packages = positive_count(line.get("quantity_packages"), "packages")
    units = positive_count(line.get("units_per_package"), "units")
    category = role_categories[role]
    if category not in buckets:
        raise ValueError("unknown robot, dock or station cost category")
    price = cents(line.get("package_price_usd"), "package price")
    if price == 0 and not _url(line.get("free_package_evidence_url")):
        raise ValueError("zero package price requires explicit free-item evidence")
    return role, seller, sku, quote_ref, packages, units, category, price


def _collect_quotes(
    evidence: dict, required_roles: dict[str, int], role_categories: dict[str, str],
    expected_scope: str, errors: list[str],
) -> _QuoteTotals:
    buckets = {"robot": 0, "dock": 0, "station": 0}
    supplied = defaultdict(int)
    seller_subtotals = defaultdict(int)
    seller_category_goods = defaultdict(lambda: defaultdict(int))
    seller_category_units = defaultdict(lambda: defaultdict(int))
    quote_claims: set[tuple[str, str, str, str]] = set()
    # Keep physical packages distinct from role coverage. A sealed retail
    # multipack can leave explicitly reviewed spare units, never free stock.
    quote_packs_by_role: dict[str, list[tuple[int, int, object]]] = defaultdict(list)
    lines = evidence.get("lines", [])
    if not isinstance(lines, list):
        errors.append("Quote lines must be a list")
        lines = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            errors.append(f"quote {index}: invalid line")
            continue
        try:
            role, seller, sku, quote_ref, packages, units, category, price = _parse_quote(
                line, required_roles, role_categories, buckets, expected_scope
            )
            total = packages * price
            claim = (role, seller, sku, quote_ref)
            if claim in quote_claims:
                raise ValueError("duplicate quoted SKU under same role and quote reference")
            quote_claims.add(claim)
            quote_packs_by_role[role].append(
                (packages, units, line.get("minimum_pack_review"))
            )
            supplied[role] += packages * units
            seller_subtotals[seller] += total
            seller_category_goods[seller][category] += total
            seller_category_units[seller][category] += packages * units
            buckets[category] += total
        except (ValueError, KeyError) as exc:
            errors.append(f"quote {index}: {exc}")
    return _QuoteTotals(
        buckets, supplied, seller_subtotals, seller_category_goods,
        seller_category_units, quote_packs_by_role,
    )


def _collect_paid_orders(
    evidence: dict, errors: list[str],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    paid_orders = {}
    paid_order_allocations: dict[str, dict[str, int]] = {}
    if evidence.get("paid_orders_complete") is not True:
        errors.append("Prior paid spending not verified as complete")
    # A missing register is UNKNOWN, even if somebody marked it complete.
    # Only an explicitly supplied empty list can mean verified zero spend.
    if "paid_orders" not in evidence:
        errors.append("Prior paid orders register missing; spending is unknown")
    orders = evidence.get("paid_orders", [])
    if not isinstance(orders, list):
        errors.append("Prior paid orders must be a list")
        orders = []
    for index, order in enumerate(orders):
        if not isinstance(order, dict):
            errors.append(f"paid order {index}: invalid record")
            continue
        try:
            reference = _nonempty(order.get("order_reference"), "paid reference")
            amount = cents(order.get("total_paid_usd"), "paid total")
            raw_allocations = order.get("allocations", [])
            if not isinstance(raw_allocations, list):
                raise ValueError("paid allocations must be a list")
            allocations: dict[str, int] = {}
            for item in raw_allocations:
                if not isinstance(item, dict):
                    raise ValueError("invalid paid allocation")
                role = _nonempty(item.get("role_key"), "paid allocation role")
                quantity = positive_count(
                    item.get("quantity"), "paid allocation units"
                )
                if role in allocations:
                    raise ValueError("duplicate role in paid order allocations")
                allocations[role] = quantity
            if reference in paid_orders and (
                    paid_orders[reference] != amount
                    or paid_order_allocations[reference] != allocations):
                raise ValueError("conflicting duplicate paid reference")
            paid_orders[reference] = amount
            paid_order_allocations[reference] = allocations
        except ValueError as exc:
            errors.append(f"paid order {index}: {exc}")
    return paid_orders, paid_order_allocations


def _collect_inventory(
    evidence: dict, required_roles: dict[str, int], paid_orders: dict[str, int],
    paid_order_allocations: dict[str, dict[str, int]], errors: list[str],
) -> tuple[defaultdict[str, int], defaultdict[tuple[str, str], int]]:
    allocated = defaultdict(int)
    inventory_claims: set[tuple[str, str]] = set()
    inspected_from_paid_order: dict[tuple[str, str], int] = defaultdict(int)
    inventory = evidence.get("inventory", [])
    if not isinstance(inventory, list):
        errors.append("Inventory must be a list")
        inventory = []
    for index, stock in enumerate(inventory):
        try:
            role = _nonempty(stock.get("role_key"), "inventory role")
            if role not in required_roles:
                raise ValueError("unknown inventory role")
            quantity = positive_count(stock.get("usable_allocated"), "inventory units")
            receipt = stock.get("inspection_receipt_url")
            if not _url(receipt):
                raise ValueError("missing stock inspection receipt URL")
            claim = (role, receipt)
            if claim in inventory_claims:
                raise ValueError("duplicate inspection receipt for same role")
            origin = stock.get("acquisition_kind")
            if origin == "already_owned":
                if stock.get("order_reference") is not None:
                    raise ValueError("already owned stock cannot claim a paid order")
            elif origin == "paid_order":
                ref = _nonempty(stock.get("order_reference"), "inspected order")
                if ref not in paid_orders:
                    raise ValueError("inspected paid stock lacks an order record")
                paid_claim = (ref, role)
                combined = inspected_from_paid_order[paid_claim] + quantity
                if combined > paid_order_allocations.get(ref, {}).get(role, 0):
                    raise ValueError("inspected stock exceeds paid role allocation")
                inspected_from_paid_order[paid_claim] = combined
            else:
                raise ValueError("inventory acquisition_kind must be already_owned or paid_order")
            inventory_claims.add(claim)
            allocated[role] += quantity
        except (AttributeError, ValueError) as exc:
            errors.append(f"inventory {index}: {exc}")
    return allocated, inspected_from_paid_order


def _collect_incoming(
    evidence: dict, required_roles: dict[str, int], paid_orders: dict[str, int],
    paid_order_allocations: dict[str, dict[str, int]],
    inspected_from_paid_order: defaultdict[tuple[str, str], int], errors: list[str],
) -> defaultdict[str, int]:
    awaiting = defaultdict(int)
    incoming_claims: set[tuple[str, str]] = set()
    incoming_items = evidence.get("paid_in_flight", [])
    if not isinstance(incoming_items, list):
        errors.append("Paid in-flight orders must be a list")
        incoming_items = []
    for index, incoming in enumerate(incoming_items):
        try:
            role = _nonempty(incoming.get("role_key"), "in-flight role")
            if role not in required_roles or required_roles[role] == 0:
                raise ValueError("unknown or excluded in-flight role")
            quantity = positive_count(incoming.get("quantity"), "in-flight units")
            ref = _nonempty(incoming.get("order_reference"), "in-flight order")
            if ref not in paid_orders:
                raise ValueError("in-flight order lacks a paid record")
            if paid_order_allocations.get(ref, {}).get(role, 0) < quantity:
                raise ValueError(
                    "in-flight order does not allocate claimed role and quantity"
                )
            if (inspected_from_paid_order[(ref, role)] + quantity
                    > paid_order_allocations[ref][role]):
                raise ValueError(
                    "paid allocation already consumed by inspected inventory"
                )
            claim = (role, ref)
            if claim in incoming_claims:
                raise ValueError("duplicate in-flight order allocation for same role")
            incoming_claims.add(claim)
            awaiting[role] += quantity
        except (AttributeError, ValueError) as exc:
            errors.append(f"in-flight {index}: {exc}")
    return awaiting


def _check_role_coverage(
    required_roles: dict[str, int], quotes: _QuoteTotals,
    allocated: defaultdict[str, int], awaiting: defaultdict[str, int], errors: list[str],
) -> tuple[list[str], dict[str, int]]:
    supplied = quotes.supplied
    quote_packs_by_role = quotes.quote_packs_by_role
    pending_roles = []
    reviewed_pack_surplus_units: dict[str, int] = {}
    for role, needed in required_roles.items():
        if allocated[role] + awaiting[role] + supplied[role] < needed:
            pending_roles.append(role)
        if allocated[role] + awaiting[role] > needed:
            errors.append(f"{role}: allocated and incoming exceed needed stock")
        if supplied[role] and allocated[role] + awaiting[role] >= needed:
            errors.append(f"{role}: duplicated purchase despite covered inventory")
        remaining = needed - allocated[role] - awaiting[role]
        quoted_packs = quote_packs_by_role[role]
        if supplied[role] > remaining and remaining > 0:
            # The only permitted excess is the smallest number of sealed
            # packages of one reviewed SKU that can cover the missing role.
            # Multiple sellers or surplus packages are not a minimum pack.
            extra = supplied[role] - remaining
            acceptable = False
            if len(quoted_packs) == 1:
                packages, units, review = quoted_packs[0]
                minimum_packages = (remaining + units - 1) // units
                acceptable = (
                    packages == minimum_packages
                    and isinstance(review, dict)
                    and set(review) == {
                        "extra_units", "seller_minimum_pack_url", "reviewed"
                    }
                    and type(review.get("extra_units")) is int
                    and review["extra_units"] == extra
                    and review.get("reviewed") is True
                    and _url(review.get("seller_minimum_pack_url"))
                )
            if acceptable:
                reviewed_pack_surplus_units[role] = extra
            else:
                errors.append(
                    f"{role}: over-order or minimum pack surplus lacks exact review"
                )
        elif any(review is not None for _, _, review in quoted_packs):
            # A review cannot manufacture a surplus or justify a purchase
            # against inventory that already covers the role.
            errors.append(f"{role}: minimum pack review without genuine surplus")
    return pending_roles, reviewed_pack_surplus_units


def _collect_seller_totals(
    evidence: dict, seller_subtotals: dict[str, int], errors: list[str],
) -> dict[str, int]:
    charged_sellers = set()
    seller_totals = {}
    charges = evidence.get("seller_charges", [])
    if not isinstance(charges, list):
        errors.append("Seller charges must be a list")
        charges = []
    for index, group in enumerate(charges):
        try:
            seller = _nonempty(group.get("seller"), "charge seller")
            if seller not in seller_subtotals or seller in charged_sellers:
                raise ValueError("unknown or duplicate seller charges")
            charged_sellers.add(seller)
            seller_totals[seller] = landed_total_cents(
                seller_subtotals[seller],
                shipping=cents(group.get("shipping_usd"), "shipping"),
                tax=cents(group.get("tax_usd"), "tax"),
                duties=cents(group.get("duties_usd"), "duties"),
                discount=cents(group.get("discount_usd"), "discount"),
            )
        except (AttributeError, ValueError) as exc:
            errors.append(f"seller charges {index}: {exc}")
    if set(seller_subtotals) != charged_sellers:
        errors.append("Shipping, taxes, duties or discounts unknown for one or more sellers")
    return seller_totals


def _allocate_landed_subtotals(
    quotes: _QuoteTotals, seller_totals: dict[str, int],
) -> dict[str, int]:
    # Shipping, tax, duties and discounts belong to sellers, not specific
    # robot/dock/station roles. For reporting only, apportion each seller's
    # exact payable cents by material value, with stable largest remainders.
    # If all material is free, use item counts instead. These allocations
    # are not direct supplier quotes.
    allocated_landed_subtotals = dict.fromkeys(quotes.buckets, 0)
    for seller, gross in seller_totals.items():
        weights = quotes.seller_category_goods[seller]
        if sum(weights.values()) == 0:
            weights = quotes.seller_category_units[seller]
        denominator = sum(weights.values())
        shares = {
            category: gross * weight // denominator
            for category, weight in weights.items()
        }
        remainder = gross - sum(shares.values())
        ranking = sorted(
            weights,
            key=lambda category: (
                -(gross * weights[category] % denominator), category
            ),
        )
        for category in ranking[:remainder]:
            shares[category] += 1
        for category, amount in shares.items():
            allocated_landed_subtotals[category] += amount
    return allocated_landed_subtotals


def _prior_paid_total(
    evidence: dict, paid_orders: dict[str, int], errors: list[str],
) -> int | None:
    # An absent or malformed historical spending register is UNKNOWN, not
    # evidence that the owner has spent zero dollars already.
    prior_spend_known = (
        evidence.get("paid_orders_complete") is True
        and "paid_orders" in evidence
        and isinstance(evidence["paid_orders"], list)
        and not any(error.startswith("paid order ") for error in errors)
    )
    return sum(paid_orders.values()) if prior_spend_known else None


def _accounting_result(
    *, expected_scope: str, cap_cents: int, required_roles: dict[str, int],
    errors: list[str], quotes: _QuoteTotals, allocated: defaultdict[str, int],
    awaiting: defaultdict[str, int], pending_roles: list[str],
    reviewed_pack_surplus_units: dict[str, int], seller_totals: dict[str, int],
    already_paid: int | None,
) -> dict:
    complete = (not errors and bool(required_roles)
                and any(q > 0 for q in required_roles.values()))
    payable = sum(seller_totals.values()) if complete else None
    allocated_landed_subtotals = (
        _allocate_landed_subtotals(quotes, seller_totals) if complete else None
    )
    cumulative = (payable + already_paid
                  if payable is not None and already_paid is not None
                  else None)
    # The $50 delivered cap is for the FIRST robot, not for five complete
    # units. Keep evaluation samples under the same prototype discipline.
    cap_applies = expected_scope != "fleet"
    return {
        "scope": expected_scope,
        "currency": "USD",
        "calculation_complete_not_physical_approval": complete,
        "errors": errors,
        "unaccounted_roles": sorted(pending_roles),
        "reviewed_pack_surplus_units": dict(sorted(reviewed_pack_surplus_units.items())),
        # These quantities, not retail pack quantities, count toward roles.
        # Spare units remain physical leftovers, never a second free order.
        "quoted_units_applied_to_roles": {
            role: min(quotes.supplied[role], max(
                0, need - allocated[role] - awaiting[role]
            )) for role, need in sorted(required_roles.items())
        },
        "awaiting_arrival_roles": sorted(role for role in awaiting if awaiting[role]),
        "material_subtotals_cents": quotes.buckets,
        "allocated_landed_subtotals_cents": allocated_landed_subtotals,
        "seller_payable_cents": dict(sorted(seller_totals.items())),
        "payable_now_cents": payable,
        "prior_paid_orders_cents": already_paid,
        "prototype_cumulative_cents": cumulative,
        "prototype_cap_cents": cap_cents if cap_applies else None,
        "remaining_under_cap_cents": (cap_cents - cumulative
                                      if cumulative is not None else None)
        if cap_applies else None,
        "within_prototype_cap": (cumulative <= cap_cents
                                 if cumulative is not None else False)
        if cap_applies else None,
        "landed_price_is_a_verified_supplier_checkout": False,
    }


def _validate_accounting_request(
    evidence: dict, required_roles: dict[str, int], role_categories: dict[str, str],
    expected_scope: str, cap_cents: int,
) -> list[str]:
    if expected_scope not in {"first_robot", "fleet", "evaluation"}:
        raise ValueError("Unknown cost scope")
    if type(cap_cents) is not int or cap_cents <= 0:
        raise ValueError("Invalid prototype budget")
    if any(type(qty) is not int or not 0 <= qty <= MAX_ACCOUNTING_UNITS
           for qty in required_roles.values()):
        raise ValueError("Invalid canonical requirement count")
    if set(required_roles) != set(role_categories):
        raise ValueError("Cost category map differs from canonical requirements")
    errors: list[str] = []
    if evidence.get("scope") != expected_scope:
        errors.append("Missing or mismatched quote scope")
    if evidence.get("currency") != "USD":
        errors.append("Quote currency must be USD")
    return errors


def account_landed_cost(
    evidence: dict,
    required_roles: dict[str, int],
    role_categories: dict[str, str],
    *,
    expected_scope: str = "first_robot",
    cap_cents: int = PROTOTYPE_CAP_CENTS,
) -> dict:
    """Compute payable and lifetime prototype spend without authorizing a cart.

    Evidence keys: scope, lines, seller_charges, inventory, paid_in_flight,
    paid_orders. Every quote has role_key, seller, sku, quantity_packages,
    units_per_package, package_price_usd, quote_reference, quoted_at,
    stock_evidence_url. A zero package price additionally requires a separate
    free_package_evidence_url proving the seller actually quotes a free item.
    A seller charge has explicit shipping_usd, tax_usd,
    duties_usd, discount_usd. Inspected inventory must identify acquisition_kind
    as already_owned or paid_order and include an inspection_receipt_url.
    Paid-order inventory also needs its order_reference. The same paid order's
    role allocation must cover inspected AND still-in-flight units together;
    a paid total alone proves no item.
    """
    if not isinstance(evidence, dict):
        evidence = {}
    errors = _validate_accounting_request(
        evidence, required_roles, role_categories, expected_scope, cap_cents
    )
    quotes = _collect_quotes(evidence, required_roles, role_categories, expected_scope, errors)
    paid_orders, paid_order_allocations = _collect_paid_orders(evidence, errors)
    allocated, inspected_from_paid_order = _collect_inventory(
        evidence, required_roles, paid_orders, paid_order_allocations, errors
    )
    awaiting = _collect_incoming(
        evidence, required_roles, paid_orders, paid_order_allocations,
        inspected_from_paid_order, errors,
    )
    pending_roles, reviewed_pack_surplus_units = _check_role_coverage(
        required_roles, quotes, allocated, awaiting, errors
    )
    seller_totals = _collect_seller_totals(evidence, quotes.seller_subtotals, errors)
    if pending_roles:
        errors.append("Not all canonical roles are priced or accounted for")
    return _accounting_result(
        expected_scope=expected_scope, cap_cents=cap_cents, required_roles=required_roles,
        errors=errors, quotes=quotes, allocated=allocated, awaiting=awaiting,
        pending_roles=pending_roles, reviewed_pack_surplus_units=reviewed_pack_surplus_units,
        seller_totals=seller_totals, already_paid=_prior_paid_total(evidence, paid_orders, errors),
    )
