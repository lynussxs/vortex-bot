from __future__ import annotations

import unittest
from types import SimpleNamespace

from cogs.welcome import WelcomeCog


class WelcomeRenderTests(unittest.TestCase):
    def _member(self):
        guild = SimpleNamespace(name="Test *Server*", member_count=42)
        return SimpleNamespace(mention="<@7>", display_name="Bob", guild=guild, id=7)

    def test_known_placeholders_are_replaced(self) -> None:
        text = WelcomeCog._render("Hi {user} to {server} #{membercount}", self._member())
        self.assertEqual(text, "Hi <@7> to Test \\*Server\\* #42")

    def test_unknown_or_unbalanced_braces_do_not_crash(self) -> None:
        member = self._member()
        self.assertEqual(WelcomeCog._render("Hello {name}!", member), "Hello {name}!")
        self.assertEqual(WelcomeCog._render("Oops { open", member), "Oops { open")
        self.assertEqual(WelcomeCog._render("{user.__class__}", member), "{user.__class__}")


if __name__ == "__main__":
    unittest.main()
