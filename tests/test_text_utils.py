"""Portable tests for text helpers (no Windows APIs or OCR packages needed)."""

import ast
import itertools
from pathlib import Path
import re
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "typer_bot.py"
FUNCTIONS = {"clean", "spellings", "is_ambiguous", "forget_stale"}
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
namespace = {"itertools": itertools, "re": re, "MAX_SPELLINGS": 8, "FORGET_AFTER": 5.0}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)


class TextUtilsTests(unittest.TestCase):
    def test_clean_full_width_punctuation(self):
        self.assertEqual(namespace["clean"]("Hello，  world！"), "Hello, world!")

    def test_clean_removes_non_ascii(self):
        self.assertEqual(namespace["clean"](" café  ok  "), "caf ok")

    def test_clean_collapses_whitespace(self):
        self.assertEqual(namespace["clean"]("a\t\n b"), "a b")

    def test_spellings_nonambiguous(self):
        self.assertEqual(namespace["spellings"]("Desk"), ["desk"])

    def test_spellings_ambiguous(self):
        self.assertEqual(namespace["spellings"]("Il"), ["il", "ll", "ii", "li"])

    def test_spellings_are_limited(self):
        self.assertLessEqual(len(namespace["spellings"]("IIIIIIII")), 8)

    def test_ambiguity_detection(self):
        is_ambiguous = namespace["is_ambiguous"]
        self.assertTrue(is_ambiguous("I"))
        self.assertTrue(is_ambiguous("|"))
        self.assertTrue(is_ambiguous("like"))
        self.assertFalse(is_ambiguous("hello"))

    def test_forget_stale_keeps_visible_words(self):
        last_seen, tries, recent = {}, {"desk": 1}, {"desk": 0.0}
        namespace["forget_stale"](["Desk"], last_seen, tries, recent, 0.0)
        namespace["forget_stale"](["Desk"], last_seen, tries, recent, 100.0)
        self.assertEqual(tries, {"desk": 1})

    def test_forget_stale_drops_words_gone_too_long(self):
        last_seen, tries, recent = {}, {"desk": 1}, {"desk": 0.0}
        namespace["forget_stale"](["Desk"], last_seen, tries, recent, 0.0)
        namespace["forget_stale"]([], last_seen, tries, recent, 3.0)
        self.assertEqual(tries, {"desk": 1})
        namespace["forget_stale"]([], last_seen, tries, recent, 6.0)
        self.assertEqual((last_seen, tries, recent), ({}, {}, {}))


if __name__ == "__main__":
    unittest.main()
