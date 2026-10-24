import hashlib
import hmac
import http.client
import http.server
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from sync_server import (
    SyncServerThread,
    SyncStateStore,
    _make_handler,
    profile_id_for_name,
    validate_stbook,
)


class SyncStateStoreTests(unittest.TestCase):
    def test_http_books_and_state_are_scoped_to_paired_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "books"
            store = SyncStateStore(Path(directory) / "state.json")
            alice = store.pair_device("alice-phone", "Phone", "a" * 64, "Alice")
            bob = store.pair_device("bob-phone", "Phone", "b" * 64, "Bob")
            alice_dir = root / "profiles" / alice
            bob_dir = root / "profiles" / bob
            alice_dir.mkdir(parents=True)
            bob_dir.mkdir(parents=True)
            (alice_dir / f"{'c' * 64}.stbook").write_bytes(b"Alice")
            (bob_dir / f"{'d' * 64}.stbook").write_bytes(b"Bob")
            store.merge({
                "version": 1,
                "words": {"haus": {"known": True, "updated_at": 10}},
                "progress": {},
            }, alice)
            owner = SimpleNamespace(
                store=store,
                books_directory=root,
                books_directory_for=lambda profile_id: (
                    root if profile_id == "default"
                    else root / "profiles" / profile_id
                ),
                _auth_lock=threading.Lock(),
                _nonces={},
            )
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), _make_handler()
            )
            server.owner = owner
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def get(device_id, token, path):
                timestamp = str(int(time.time()))
                nonce = hashlib.sha256(
                    f"{device_id}:{time.monotonic_ns()}".encode()
                ).hexdigest()[:32]
                empty_digest = hashlib.sha256(b"").hexdigest()
                signed = "\n".join((
                    timestamp, nonce, "GET", path, empty_digest
                )).encode()
                signature = hmac.new(
                    token.encode(), signed, hashlib.sha256
                ).hexdigest()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1]
                )
                connection.request("GET", path, headers={
                    "X-ST-Device": device_id,
                    "X-ST-Timestamp": timestamp,
                    "X-ST-Nonce": nonce,
                    "X-ST-Signature": signature,
                })
                response = connection.getresponse()
                body = response.read()
                connection.close()
                self.assertEqual(response.status, 200)
                return json.loads(body)

            try:
                alice_books = get("alice-phone", "a" * 64, "/api/v1/books")
                bob_books = get("bob-phone", "b" * 64, "/api/v1/books")
                alice_state = get("alice-phone", "a" * 64, "/api/v1/state")
                bob_state = get("bob-phone", "b" * 64, "/api/v1/state")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            self.assertEqual([item["id"] for item in alice_books["books"]], ["c" * 64])
            self.assertEqual([item["id"] for item in bob_books["books"]], ["d" * 64])
            self.assertIn("haus", alice_state["words"])
            self.assertEqual(bob_state["words"], {})

    def test_changes_endpoint_waits_and_reports_state_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "books"
            root.mkdir()
            owner = SyncServerThread(Path(directory) / "state.json", root)
            owner.store.pair_device("phone", "Phone", "a" * 64, "Alice")
            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), _make_handler()
            )
            server.owner = owner
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def get(path):
                timestamp = str(int(time.time()))
                nonce = hashlib.sha256(
                    str(time.monotonic_ns()).encode()
                ).hexdigest()[:32]
                signed = "\n".join((
                    timestamp, nonce, "GET", path,
                    hashlib.sha256(b"").hexdigest(),
                )).encode()
                signature = hmac.new(
                    ("a" * 64).encode(), signed, hashlib.sha256
                ).hexdigest()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_address[1], timeout=40
                )
                connection.request("GET", path, headers={
                    "X-ST-Device": "phone",
                    "X-ST-Timestamp": timestamp,
                    "X-ST-Nonce": nonce,
                    "X-ST-Signature": signature,
                })
                response = connection.getresponse()
                body = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                return body

            try:
                first = get("/api/v1/changes?since=0x0000000000000000")
                self.assertTrue(first["changed"])
                path = f"/api/v1/changes?since={first['fingerprint']}"
                threading.Timer(1, lambda: owner.store.merge({
                    "version": 1, "words": {}, "progress": {
                        "b" * 64: {"position_ms": 5, "updated_at": 1}
                    },
                }, owner.store.device_profile("phone"))).start()
                started = time.monotonic()
                second = get(path)
                self.assertTrue(second["changed"])
                self.assertLess(time.monotonic() - started, 5)
                profile_directory = owner.books_directory_for(
                    owner.store.device_profile("phone")
                )
                profile_directory.mkdir(parents=True, exist_ok=True)
                (profile_directory / f"{'c' * 64}.stbook").write_bytes(b"x")
                third = get(f"/api/v1/changes?since={second['fingerprint']}")
                self.assertNotEqual(
                    third["fingerprint"].split("x")[1],
                    second["fingerprint"].split("x")[1],
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_profiles_have_separate_book_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "books"
            root.mkdir()
            (root / f"{'a' * 64}.stbook").write_bytes(b"default")
            server = SyncServerThread(Path(directory) / "state.json", root)
            first = server.store.pair_device(
                "phone-one", "Phone", "a" * 64, "Alice"
            )
            second = server.store.pair_device(
                "phone-two", "Phone", "b" * 64, "Bob"
            )
            server.prepare_profile_books(first)
            server.prepare_profile_books(second)
            first_books = server.books_directory_for(first)
            second_books = server.books_directory_for(second)
            self.assertEqual(
                (first_books / f"{'a' * 64}.stbook").read_bytes(),
                b"default",
            )
            self.assertNotEqual(first_books, second_books)
            (first_books / f"{'b' * 64}.stbook").write_bytes(b"Alice only")
            self.assertFalse((second_books / f"{'b' * 64}.stbook").exists())

    def test_profiles_share_state_by_name_but_isolate_other_users(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncStateStore(Path(directory) / "state.json")
            first = store.pair_device("phone-one", "Phone", "a" * 64, "Family")
            same = store.pair_device("tablet", "Tablet", "b" * 64, " family ")
            other = store.pair_device("guest", "Phone", "c" * 64, "Guest")
            self.assertEqual(first, same)
            self.assertNotEqual(first, other)
            self.assertEqual(first, profile_id_for_name("FAMILY"))

            store.merge({
                "version": 1,
                "words": {"haus": {"known": True, "updated_at": 10}},
                "progress": {},
            }, first)
            self.assertTrue(store.public_state(same)["words"]["haus"]["known"])
            self.assertEqual(store.public_state(other)["words"], {})

            restored = SyncStateStore(Path(directory) / "state.json")
            self.assertEqual(restored.device_profile("tablet"), first)
            self.assertEqual(restored.public_state(other)["words"], {})

    def test_latest_timestamp_wins_for_words_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncStateStore(Path(directory) / "state.json")
            book_id = "a" * 64
            store.merge({
                "version": 1,
                "words": {"haus": {"known": True, "updated_at": 10}},
                "progress": {
                    book_id: {"position_ms": 1200, "updated_at": 10}
                },
            })
            merged = store.merge({
                "version": 1,
                "words": {"haus": {"known": False, "updated_at": 20}},
                "progress": {
                    book_id: {"position_ms": 2500, "updated_at": 20}
                },
            })
            self.assertEqual(merged["words"]["haus"], {
                "known": False,
                "updated_at": 20,
            })
            self.assertEqual(merged["progress"][book_id], {
                "position_ms": 2500,
                "updated_at": 20,
            })
            tied = store.merge({
                "version": 1,
                "words": {"haus": {"known": True, "updated_at": 20}},
                "progress": {
                    book_id: {"position_ms": 3000, "updated_at": 20}
                },
            })
            self.assertTrue(tied["words"]["haus"]["known"])
            self.assertEqual(tied["progress"][book_id]["position_ms"], 3000)

    def test_invalid_merge_does_not_partially_modify_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SyncStateStore(Path(directory) / "state.json")
            with self.assertRaises(ValueError):
                store.merge({
                    "version": 1,
                    "words": {
                        "haus": {"known": True, "updated_at": 1},
                        "baum": {"known": "yes", "updated_at": 2},
                    },
                    "progress": {},
                })
            self.assertEqual(store.public_state()["words"], {})

    def test_store_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            SyncStateStore(path).merge({
                "version": 1,
                "words": {"haus": {"known": True, "updated_at": 10}},
                "progress": {},
            })
            self.assertEqual(
                SyncStateStore(path).public_state()["words"]["haus"]["known"],
                True,
            )


class StbookValidationTests(unittest.TestCase):
    def test_accepts_valid_manifest_and_rejects_traversal_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.stbook"
            metadata = {
                "format": "Sprachtrainer Book",
                "version": 1,
                "audio": "audio/book.mp3",
                "segments": [{
                    "start": 0,
                    "ende": 1,
                    "tokens": [{"roh": "Hallo", "rein": "Hallo"}],
                }],
                "assets": [],
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("metadata.json", json.dumps(metadata))
                archive.writestr("audio/book.mp3", b"audio")
            self.assertEqual(validate_stbook(path)["format"], "Sprachtrainer Book")

            metadata["assets"] = ["bilder/../secret.png"]
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("metadata.json", json.dumps(metadata))
                archive.writestr("audio/book.mp3", b"audio")
            with self.assertRaises(ValueError):
                validate_stbook(path)


if __name__ == "__main__":
    unittest.main()
