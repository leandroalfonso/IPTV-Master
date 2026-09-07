def can_claim_device(active_device_ids, device_id, limit):
    """Device limit is disabled: any device may claim a slot.

    Kept as a no-op shim so callers don't need to change, but the policy of
    "one device only" was removed because it was trapping sessions and blocking
    legitimate logins. Devices are still recorded (for visibility) but never
    rejected.
    """
    return True
