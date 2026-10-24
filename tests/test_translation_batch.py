import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import main


class TranslationBatchTests(unittest.TestCase):
    def test_batch_translates_unique_sentences_missing_from_cache(self):
        cached_text = "Das ist schon übersetzt."
        pending_text = "Das muss noch übersetzt werden."
        cache_key = main.SprachLernPlayer.uebersetzung_cache_schluessel(
            cached_text, "ru"
        )
        window = SimpleNamespace(
            combo_uebersetzung=Mock(),
            segmente=[
                {"tokens": [{"roh": cached_text}]},
                {"tokens": [{"roh": pending_text}]},
                {"tokens": [{"roh": pending_text}]},
            ],
            uebersetzungen={},
            einstellungen=Mock(),
            uebersetzung_cache_schluessel=(
                main.SprachLernPlayer.uebersetzung_cache_schluessel
            ),
            _translation_batch_next=Mock(),
            btn_export=Mock(),
            btn_reanalyse=Mock(),
            progress_bar=Mock(),
        )
        window.combo_uebersetzung.currentData.return_value = "ru"
        window.einstellungen.value.side_effect = lambda key, *_args, **_kwargs: (
            "Это уже переведено." if key.endswith(cache_key) else ""
        )

        main.SprachLernPlayer._start_translation_batch(window)

        self.assertEqual(window.translation_batch["items"], [pending_text])
        self.assertEqual(window.translation_batch["total"], 2)
        self.assertEqual(window.translation_batch["done"], 1)
        self.assertEqual(
            window.uebersetzungen[(cached_text, "ru")],
            "Это уже переведено.",
        )
        window._translation_batch_next.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
