"""Splitting money without losing any.

The problem in one line: ``100.00`` split three ways is ``33.333...`` each,
and no rounding of that number three times adds back up to ``100.00``.

Rounding each share independently is the obvious approach and it is wrong in
both directions. Round half-up and three shares of ``33.33`` total ``99.99``,
a paisa short. Round up and you charge ``100.02``, inventing money. Neither
error is visible on one bill and both accumulate.

The fix here is the **largest remainder method**, the same rule used to
allocate parliamentary seats. Give everyone their exact share floored to the
paisa, count what is left over, and hand the leftover paisas one at a time to
whoever was rounded down hardest. Ties go to the earlier position, so the
result is deterministic and a test can assert it.

Everything is computed in integer paisa. Decimal would be correct too, but
integers make it impossible to reintroduce a fractional part by accident.
"""

from decimal import Decimal

CENT = Decimal("0.01")


def allocate(total: Decimal, weights: list[int]) -> list[Decimal]:
    """Split ``total`` proportionally to ``weights``.

    Returns one Decimal per weight, each quantised to the paisa. The return
    value always satisfies ``sum(result) == total`` exactly -- that property
    is the entire reason this function exists, and it is what the tests pin.

    Raises ValueError on a non-positive weight, which the DB also rejects via
    ``share_weight_positive``. The check is duplicated deliberately: this
    function is called before anything is saved.
    """
    if not weights:
        return []
    if any(weight <= 0 for weight in weights):
        raise ValueError("every share weight must be positive")

    paisa = int(total.quantize(CENT) * 100)
    total_weight = sum(weights)

    # Integer division floors, so every share is now at or below its exact
    # value and the shortfall is whatever is left of the total.
    shares = [paisa * weight // total_weight for weight in weights]
    remainders = [(paisa * weight) % total_weight for weight in weights]
    leftover = paisa - sum(shares)

    # Hand the leftover paisas to the largest remainders first. Sorting by
    # (-remainder, index) keeps ties resolving to the earlier position, which
    # is what makes this reproducible rather than dependent on sort stability.
    ranked = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for index in ranked[:leftover]:
        shares[index] += 1

    return [Decimal(share) / 100 for share in shares]
