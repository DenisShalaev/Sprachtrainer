import unittest
from unittest.mock import call, patch

import main


class GeminiFallbackTests(unittest.TestCase):
    @patch("main.gemini_interaction")
    def test_invalid_primary_text_uses_fallback_model(self, interaction):
        interaction.side_effect = [
            {"output_text": "  "},
            {"output_text": " Übersetzung "},
        ]

        result = main.gemini_interaction_mit_fallback("prompt")

        self.assertEqual(main.gemini_output_text(result), "Übersetzung")
        self.assertEqual(interaction.call_args_list, [
            call("prompt", main.GEMINI_TEXT_MODEL, 60),
            call("prompt", main.GEMINI_TEXT_FALLBACK_MODEL, 60),
        ])

    @patch("main.gemini_interaction")
    def test_missing_primary_text_uses_fallback_model(self, interaction):
        interaction.side_effect = [
            {"output": None},
            {"output_text": "Fallback"},
        ]

        result = main.gemini_interaction_mit_fallback("prompt")

        self.assertEqual(main.gemini_output_text(result), "Fallback")
        self.assertEqual(interaction.call_count, 2)


if __name__ == "__main__":
    unittest.main()
