import unittest

from device_policy import can_claim_device


class DevicePolicyTests(unittest.TestCase):
    def test_allows_same_device_without_consuming_another_slot(self):
        self.assertTrue(can_claim_device(['phone-a'], 'phone-a', 1))

    def test_allows_different_device_even_when_limit_would_be_reached(self):
        # Device limit is disabled: any device may claim a slot.
        self.assertTrue(can_claim_device(['phone-a'], 'phone-b', 1))

    def test_allows_new_device_when_slot_is_available(self):
        self.assertTrue(can_claim_device(['phone-a'], 'phone-b', 2))


if __name__ == '__main__':
    unittest.main()
