"""Language selection and translation tests; runnable without Windows/OCR."""

import string
import unittest

from i18n import MESSAGES, resolve_language, tr


class TranslationTests(unittest.TestCase):
    def test_explicit_language_overrides_locale(self):
        self.assertEqual(resolve_language("en", "zh_CN"), "en")
        self.assertEqual(resolve_language("zh", "en_GB"), "zh")

    def test_automatic_locale_selection(self):
        for code in ("zh_CN", "zh-TW", "Chinese (Simplified)_China"):
            self.assertEqual(resolve_language("auto", code), "zh")
        for code in ("en_GB", "ja_JP", ""):
            self.assertEqual(resolve_language("auto", code), "en")

    def test_invalid_language(self):
        with self.assertRaises(ValueError):
            resolve_language("fr", "fr_FR")

    def test_every_message_has_matching_format_fields(self):
        formatter = string.Formatter()
        for key, translations in MESSAGES.items():
            self.assertEqual(set(translations), {"en", "zh"}, key)
            en_fields = {field for _, field, _, _ in formatter.parse(translations["en"]) if field}
            zh_fields = {field for _, field, _, _ in formatter.parse(translations["zh"]) if field}
            self.assertEqual(en_fields, zh_fields, key)

    def test_formatted_messages(self):
        self.assertIn("3", tr("sign_seen", "en", delay=3))
        self.assertIn("3", tr("sign_seen", "zh", delay=3))


if __name__ == "__main__":
    unittest.main()
