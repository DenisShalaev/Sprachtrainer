import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import main


class AnalysisCacheTests(unittest.TestCase):
    def test_force_reanalysis_bypasses_cache_and_replaces_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "source.mp3")
            with open(audio_path, "wb") as audio:
                audio.write(b"audio")
            fresh_result = {"segmente": [{"start": 2, "ende": 3}]}

            with patch.object(main, "CACHE_ORDNER", directory):
                thread = main.AnalyseThread(
                    audio_path, "base", force_reanalyse=True
                )
                cache_path = thread.cache_pfad()
                with open(cache_path, "w", encoding="utf-8") as cache:
                    json.dump({"segmente": [{"start": 0, "ende": 1}]}, cache)
                thread.transkribiere = Mock(return_value=fresh_result)

                thread.run()

                thread.transkribiere.assert_called_once_with()
                with open(cache_path, encoding="utf-8") as cache:
                    self.assertEqual(json.load(cache), fresh_result)

    def test_refresh_reuses_existing_transcript_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = os.path.join(directory, "source.mp3")
            with open(audio_path, "wb") as audio:
                audio.write(b"audio")
            cached_result = {"segmente": [{"start": 0, "ende": 1}]}

            with patch.object(main, "CACHE_ORDNER", directory):
                thread = main.AnalyseThread(audio_path, "base")
                with open(thread.cache_pfad(), "w", encoding="utf-8") as cache:
                    json.dump(cached_result, cache)
                thread.transkribiere = Mock()

                thread.run()

                thread.transkribiere.assert_not_called()


if __name__ == "__main__":
    unittest.main()
