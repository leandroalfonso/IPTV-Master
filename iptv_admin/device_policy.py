def can_claim_device(active_device_ids, device_id, limit):
    """Return whether device_id may use one of the user's active slots."""
    normalized = {str(value) for value in active_device_ids if value}
    current = str(device_id or '')
    try:
        maximum = max(1, int(limit or 1))
    except (TypeError, ValueError):
        maximum = 1
    return current in normalized or len(normalized) < maximum
