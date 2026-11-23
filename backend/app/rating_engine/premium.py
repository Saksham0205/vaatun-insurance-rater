from decimal import Decimal


def normalize_premium(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Premium must be a finite decimal amount.") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Premium must be a finite non-negative decimal amount.")
    return result


def hdfc_band_from_premium(value: Decimal | None) -> tuple[str | None, str | None]:
    """Only non-boundary values are assigned; the PDF leaves exact endpoints unclear."""
    if value is None:
        return None, "OD premium is required to determine HDFC premium slab."
    boundaries = {Decimal("10000"), Decimal("50000"), Decimal("100000"), Decimal("200000")}
    if value in boundaries:
        return None, f"HDFC grid does not define inclusivity at exact OD premium boundary {value}."
    if value < 10000:
        return "<10k", None
    if value < 50000:
        return ">10-50k", None
    if value < 100000:
        return ">50k-1L", None
    if value < 200000:
        return ">1L-2L", None
    return ">2L", None
