import hashlib
import unittest
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class WordTimestampTests(unittest.TestCase):
    def test_promotes_books_with_partial_but_real_word_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "partial.stbook"
            metadata = {
                "format": "Sprachtrainer Book",
                "version": 1,
                "audio": "audio/book.mp3",
                "word_timestamps": False,
                "segments": [{
                    "start": 0,
                    "ende": 1,
                    "tokens": [
                        {"roh": "Hallo", "rein": "Hallo", "start": 0.1, "ende": 0.5},
                        {"roh": "Welt", "rein": "Welt"},
                    ],
                }],
                "assets": [],
            }
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("metadata.json", json.dumps(metadata))
                archive.writestr("audio/book.mp3", b"audio")

            migrated, new_id = main.aktualisiere_stbook_timing_flag(str(source))
            try:
                with zipfile.ZipFile(migrated) as archive:
                    updated = json.loads(archive.read("metadata.json"))
                    self.assertEqual(archive.read("audio/book.mp3"), b"audio")
                self.assertTrue(updated["word_timestamps"])
                self.assertTrue(main.stbook_hat_wortzeiten(updated))
                self.assertEqual(
                    new_id,
                    hashlib.sha256(Path(migrated).read_bytes()).hexdigest(),
                )
            finally:
                Path(migrated).unlink()

    def test_maps_whisper_words_to_whitespace_preserving_tokens(self):
        tokens = [
            {"roh": "Wir", "rein": "Wir"},
            {"roh": " ", "rein": ""},
            {"roh": "gehen.", "rein": "gehen"},
        ]
        whisper_words = [
            {"word": " Wir", "start": 0.1, "end": 0.35},
            {"word": " gehen.", "start": 0.4, "end": 0.8},
        ]

        result = main.wortzeitstempel_fuer_tokens(
            tokens, whisper_words, 0.0, 1.0
        )

        self.assertEqual(result, [(0, 0.1, 0.35), (2, 0.4, 0.8)])

    def test_rejects_partial_alignment_instead_of_mixing_guessed_times(self):
        tokens = [
            {"roh": "Wir", "rein": "Wir"},
            {"roh": "gehen.", "rein": "gehen"},
        ]
        whisper_words = [
            {"word": " Wir", "start": 0.1, "end": 0.35},
            {"word": " laufen.", "start": 0.4, "end": 0.8},
        ]

        self.assertIsNone(
            main.wortzeitstempel_fuer_tokens(
                tokens, whisper_words, 0.0, 1.0
            )
        )

    @patch("main.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("main.whisper.load_model")
    def test_transcription_requests_and_persists_word_timestamps(
        self, load_model, _which
    ):
        model = SimpleNamespace(device=SimpleNamespace(type="cpu"))
        model.transcribe = Mock(
            return_value={
                "segments": [
                    {
                        "text": " Hallo Welt!",
                        "start": 1.0,
                        "end": 2.0,
                        "words": [
                            {"word": " Hallo", "start": 1.1, "end": 1.4},
                            {"word": " Welt!", "start": 1.5, "end": 1.9},
                        ],
                    }
                ]
            }
        )
        load_model.return_value = model

        result = main.AnalyseThread("audio.mp3", "base").transkribiere()

        model.transcribe.assert_called_once()
        self.assertTrue(model.transcribe.call_args.kwargs["word_timestamps"])
        self.assertEqual(result["segmente"][0]["tokens"][0]["start"], 1.1)
        self.assertEqual(result["segmente"][0]["tokens"][2]["ende"], 1.9)


if __name__ == "__main__":
    unittest.main()
