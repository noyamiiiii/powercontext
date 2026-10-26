"""Order listing service; status is reserved but not implemented in the baseline."""

def list_orders(orders, *, status=None, offset=0, limit=20):
    """Return orders sorted by id, with stable offset/limit pagination."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    selected = sorted(orders, key=lambda order: order["id"])
    return selected[offset:offset + limit]
