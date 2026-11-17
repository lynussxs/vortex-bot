from __future__ import annotations

import unittest

from core.ai_context import OWNER_ADDENDUM, build_messages


class OwnerModeTests(unittest.TestCase):
    def test_owner_mode_adds_addendum_and_full_report_label(self) -> None:
        owner = build_messages("sys", "FULL", [], [], "check server", owner_mode=True)
        normal = build_messages("sys", "PUBLIC", [], [], "check server")
        self.assertIn(OWNER_ADDENDUM.strip()[:30], owner[0]["content"])
        self.assertIn("Full server report", owner[-1]["content"])
        self.assertNotIn("Verified owner session", normal[0]["content"])
        self.assertIn("Server metadata (public)", normal[-1]["content"])


if __name__ == "__main__":
    unittest.main()
