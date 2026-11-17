from __future__ import annotations

import unittest
from types import SimpleNamespace

from cogs.welcome import WelcomeCog


class WelcomeTemplateTests(unittest.TestCase):
    def test_placeholders_render_and_variants_rotate(self) -> None:
        member = SimpleNamespace(
            mention="<@123>",
            display_name="New Member",
            guild=SimpleNamespace(name="My Server", member_count=42),
            id=123,
        )
        output = WelcomeCog._render(
            "{user} joined {server} as #{membercount} ({userid})||Welcome {username}",
            member,
        )
        self.assertIn(output, {"<@123> joined My Server as #42 (123)", "Welcome New Member"})
