import hashlib
import hmac
import http.server
import json
import math
import os
import re
import secrets
import copy
import shutil
import socket
import tempfile
import threading
import time
import unicodedata
import zipfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


DISCOVERY_PORT = 43981
HTTP_PORT = 43982
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_BOOK_BYTES = 2 * 1024 * 1024 * 1024
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BOOK_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
PROFILE_ID_PATTERN = re.compile(r"^(?:default|[a-f0-9]{32})$")


def profile_id_for_name(name):
    normalized = unicodedata.normalize("NFKC", name).strip().casefold()
    if not normalized or len(normalized) > 80:
        raise ValueError("Profile name must contain 1 to 80 characters.")
    if normalized == "default":
        return "default"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


class SyncStateStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.revision = 0
        self._state = {
            "version": 1,
            "words": {},
            "progress": {},
            "devices": {},
            "deleted_books": {},
            "profiles": {},
        }
        if self.path.exists():
            self._state = self._read()

    def _read(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read sync state at {self.path}: {error}") from error
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or not isinstance(state.get("words"), dict)
            or not isinstance(state.get("progress"), dict)
            or not isinstance(state.get("devices"), dict)
        ):
            raise ValueError(f"Invalid sync state in {self.path}")
        profiles = state.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError(f"Invalid profiles in {self.path}")
        if any(
            not isinstance(word, str)
            or not word
            or len(word) > 128
            or not isinstance(record, dict)
            or not isinstance(record.get("known"), bool)
            or type(record.get("updated_at")) is not int
            or record["updated_at"] < 0
            for word, record in state["words"].items()
        ):
            raise ValueError(f"Invalid dictionary state in {self.path}")
        if any(
            not BOOK_ID_PATTERN.fullmatch(book_id)
            or not isinstance(record, dict)
            or type(record.get("position_ms")) is not int
            or record["position_ms"] < 0
            or type(record.get("updated_at")) is not int
            or record["updated_at"] < 0
            for book_id, record in state["progress"].items()
        ):
            raise ValueError(f"Invalid playback state in {self.path}")
        deleted = state.setdefault("deleted_books", {})
        if not isinstance(deleted, dict) or any(
            not isinstance(book_id, str)
            or not BOOK_ID_PATTERN.fullmatch(book_id)
            or type(stamp) is not int
            for book_id, stamp in deleted.items()
        ):
            raise ValueError(f"Invalid deleted-book state in {self.path}")
        if any(
            not isinstance(device_id, str)
            or not DEVICE_ID_PATTERN.fullmatch(device_id)
            or not isinstance(record, dict)
            or not isinstance(record.get("name"), str)
            or not isinstance(record.get("token"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", record["token"])
            or type(record.get("paired_at")) is not int
            for device_id, record in state["devices"].items()
        ):
            raise ValueError(f"Invalid paired-device state in {self.path}")
        for profile_id, profile in profiles.items():
            if (
                not isinstance(profile_id, str)
                or not PROFILE_ID_PATTERN.fullmatch(profile_id)
                or profile_id == "default"
                or not isinstance(profile, dict)
                or not isinstance(profile.get("name"), str)
                or not isinstance(profile.get("words"), dict)
                or not isinstance(profile.get("progress"), dict)
                or not isinstance(profile.get("deleted_books"), dict)
            ):
                raise ValueError(f"Invalid profile state in {self.path}")
            for word, record in profile["words"].items():
                if (
                    not isinstance(word, str) or not word or len(word) > 128
                    or not isinstance(record, dict)
                    or not isinstance(record.get("known"), bool)
                    or type(record.get("updated_at")) is not int
                    or record["updated_at"] < 0
                ):
                    raise ValueError(f"Invalid profile dictionary in {self.path}")
            for book_id, record in profile["progress"].items():
                if (
                    not isinstance(book_id, str)
                    or not BOOK_ID_PATTERN.fullmatch(book_id)
                    or not isinstance(record, dict)
                    or type(record.get("position_ms")) is not int
                    or record["position_ms"] < 0
                    or type(record.get("updated_at")) is not int
                    or record["updated_at"] < 0
                ):
                    raise ValueError(f"Invalid profile progress in {self.path}")
            if any(
                not isinstance(book_id, str)
                or not BOOK_ID_PATTERN.fullmatch(book_id)
                or type(stamp) is not int
                for book_id, stamp in profile["deleted_books"].items()
            ):
                raise ValueError(f"Invalid profile deletions in {self.path}")
        for device in state["devices"].values():
            if device.get("profile_id", "default") not in (
                {"default"} | set(profiles)
            ):
                raise ValueError(f"Unknown device profile in {self.path}")
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self._state, file, ensure_ascii=False, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            self.revision += 1
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def pair_device(self, device_id, name, token, profile_name="Default"):
        profile_id = profile_id_for_name(profile_name)
        with self._lock:
            previous = self._state["devices"].get(device_id)
            profile_previous = self._state["profiles"].get(profile_id)
            if profile_id != "default" and profile_previous is None:
                self._state["profiles"][profile_id] = {
                    "name": profile_name.strip()[:80],
                    "words": {},
                    "progress": {},
                    "deleted_books": {},
                }
            self._state["devices"][device_id] = {
                "name": name[:80],
                "token": token,
                "paired_at": int(time.time() * 1000),
                "profile_id": profile_id,
            }
            try:
                self._save()
            except OSError:
                if profile_id != "default" and profile_previous is None:
                    self._state["profiles"].pop(profile_id, None)
                if previous is None:
                    self._state["devices"].pop(device_id, None)
                else:
                    self._state["devices"][device_id] = previous
                raise
            return profile_id

    def device_token(self, device_id):
        with self._lock:
            device = self._state["devices"].get(device_id)
            return device.get("token") if isinstance(device, dict) else None

    def device_profile(self, device_id):
        with self._lock:
            device = self._state["devices"].get(device_id)
            return device.get("profile_id", "default") if device else None

    def profile_ids(self):
        with self._lock:
            return ["default", *self._state["profiles"].keys()]

    def _profile(self, profile_id):
        if profile_id == "default":
            return self._state
        profile = self._state["profiles"].get(profile_id)
        if profile is None:
            raise ValueError("Unknown synchronization profile.")
        return profile

    def public_state(self, profile_id="default"):
        with self._lock:
            profile = self._profile(profile_id)
            return {
                "version": 1,
                "profile_id": profile_id,
                "words": copy.deepcopy(profile["words"]),
                "progress": copy.deepcopy(profile["progress"]),
                "deleted_books": copy.deepcopy(profile["deleted_books"]),
            }

    def mark_book_deleted(self, book_id, profile_id="default"):
        with self._lock:
            self._profile(profile_id)["deleted_books"][book_id] = int(
                time.time() * 1000
            )
            self._save()

    def mark_book_deleted_all(self, book_id):
        with self._lock:
            stamp = int(time.time() * 1000)
            self._state["deleted_books"][book_id] = stamp
            for profile in self._state["profiles"].values():
                profile["deleted_books"][book_id] = stamp
            self._save()

    def unmark_book_deleted(self, book_id):
        with self._lock:
            changed = self._state["deleted_books"].pop(book_id, None) is not None
            for profile in self._state["profiles"].values():
                changed |= profile["deleted_books"].pop(book_id, None) is not None
            if changed:
                self._save()

    def merge(self, incoming, profile_id="default"):
        if (
            not isinstance(incoming, dict)
            or type(incoming.get("version")) is not int
            or incoming["version"] != 1
            or not isinstance(incoming.get("words"), dict)
            or not isinstance(incoming.get("progress"), dict)
            or len(incoming["words"]) > 100_000
            or len(incoming["progress"]) > 50_000
        ):
            raise ValueError("State must contain words and progress objects.")
        latest_allowed = int(time.time() * 1000) + 5 * 60 * 1000
        with self._lock:
            for word, record in incoming["words"].items():
                if (
                    not isinstance(word, str)
                    or not word
                    or len(word) > 128
                    or not isinstance(record, dict)
                ):
                    raise ValueError("Invalid dictionary entry.")
                timestamp = record.get("updated_at")
                if (
                    type(timestamp) is not int
                    or timestamp < 0
                    or timestamp > latest_allowed
                    or not isinstance(record.get("known"), bool)
                ):
                    raise ValueError("Invalid dictionary timestamp.")
            for book_id, record in incoming["progress"].items():
                if (
                    not isinstance(book_id, str)
                    or not BOOK_ID_PATTERN.fullmatch(book_id)
                    or not isinstance(record, dict)
                ):
                    raise ValueError("Invalid playback progress entry.")
                timestamp = record.get("updated_at")
                position = record.get("position_ms")
                if (
                    type(timestamp) is not int
                    or timestamp < 0
                    or timestamp > latest_allowed
                    or type(position) is not int
                    or position < 0
                ):
                    raise ValueError("Invalid playback progress values.")

            previous = copy.deepcopy(self._state)
            try:
                profile = self._profile(profile_id)
                for word, record in incoming["words"].items():
                    timestamp = record["updated_at"]
                    old = profile["words"].get(word)
                    if (
                        not isinstance(old, dict)
                        or timestamp > old.get("updated_at", -1)
                        or (
                            timestamp == old.get("updated_at")
                            and record["known"] is True
                            and old.get("known") is False
                        )
                    ):
                        profile["words"][word] = {
                            "known": record["known"],
                            "updated_at": timestamp,
                        }

                for book_id, record in incoming["progress"].items():
                    timestamp = record["updated_at"]
                    old = profile["progress"].get(book_id)
                    if (
                        not isinstance(old, dict)
                        or timestamp > old.get("updated_at", -1)
                        or (
                            timestamp == old.get("updated_at")
                            and record["position_ms"] > old.get("position_ms", -1)
                        )
                    ):
                        profile["progress"][book_id] = {
                            "position_ms": record["position_ms"],
                            "updated_at": timestamp,
                        }
                self._save()
            except OSError:
                self._state = previous
                raise
            return self.public_state(profile_id)


def validate_stbook(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or "metadata.json" not in names:
                raise ValueError("Invalid or duplicate .stbook entries.")
            for name in names:
                entry_path = name[:-1] if name.endswith("/") else name
                if (
                    not entry_path
                    or name.startswith("/")
                    or "\\" in name
                    or any(
                        part in ("", ".", "..")
                        for part in entry_path.split("/")
                    )
                ):
                    raise ValueError("The archive contains an unsafe file path.")
            if entries[names.index("metadata.json")].file_size > 64 * 1024 * 1024:
                raise ValueError(".stbook metadata exceeds the supported size.")
            if sum(entry.file_size for entry in entries) > MAX_BOOK_BYTES:
                raise ValueError(".stbook exceeds the supported size.")
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            if (
                not isinstance(metadata, dict)
                or metadata.get("format") != "Sprachtrainer Book"
                or metadata.get("version") != 1
            ):
                raise ValueError("Unsupported .stbook format.")
            audio = metadata.get("audio")
            segments = metadata.get("segments")
            assets = metadata.get("assets")
            if (
                not isinstance(audio, str)
                or not audio.startswith("audio/")
                or len(audio.split("/")) != 2
                or Path(audio).suffix.lower()
                not in {".mp3", ".wav", ".m4a", ".ogg", ".aif", ".aiff"}
                or audio not in names
                or not isinstance(segments, list)
                or not segments
                or not isinstance(assets, list)
                or not isinstance(metadata.get("translations", []), list)
            ):
                raise ValueError("Invalid .stbook contents.")
            if any(
                not isinstance(translation, dict)
                or not all(
                    isinstance(translation.get(field), str)
                    for field in ("original", "language", "text")
                )
                for translation in metadata.get("translations", [])
            ):
                raise ValueError("Invalid .stbook translation.")
            for asset in assets:
                if (
                    not isinstance(asset, str)
                    or not asset.startswith("bilder/")
                    or len(asset.split("/")) != 2
                    or asset not in names
                ):
                    raise ValueError("Invalid .stbook image path.")
            for segment in segments:
                if (
                    not isinstance(segment, dict)
                    or not isinstance(segment.get("start"), (int, float))
                    or not isinstance(segment.get("ende"), (int, float))
                    or not math.isfinite(segment["start"])
                    or not math.isfinite(segment["ende"])
                    or segment["start"] < 0
                    or segment["ende"] < segment["start"]
                    or not isinstance(segment.get("tokens"), list)
                    or not segment["tokens"]
                    or any(
                        not isinstance(token, dict)
                        or not isinstance(token.get("roh"), str)
                        or not isinstance(token.get("rein"), str)
                        for token in segment["tokens"]
                    )
                ):
                    raise ValueError("Invalid .stbook sentence data.")
            return metadata
    except (
        zipfile.BadZipFile,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RuntimeError,
        RecursionError,
    ) as error:
        raise ValueError(f"Invalid .stbook archive: {error}") from error


class SyncServerThread(QThread):
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)
    state_received = pyqtSignal(str, dict)
    book_received = pyqtSignal(str)
    pairing_code_changed = pyqtSignal(str)

    def __init__(self, state_path, books_directory):
        super().__init__()
        self.store = SyncStateStore(state_path)
        self.books_directory = Path(books_directory)
        self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
        self._pair_code_created = time.monotonic()
        self._stop_event = threading.Event()
        self._nonces = {}
        self._auth_lock = threading.Lock()
        self._pair_attempts = {}
        self._pair_attempts_lock = threading.Lock()
        self._pair_lock = threading.Lock()

    def pair_device(self, supplied, device_id, name, token, profile_name="Default"):
        with self._pair_lock:
            if (
                time.monotonic() - self._pair_code_created > 600
                or not hmac.compare_digest(supplied, self.pair_code)
            ):
                if time.monotonic() - self._pair_code_created > 600:
                    self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
                    self._pair_code_created = time.monotonic()
                    self.pairing_code_changed.emit(self.pair_code)
                return False
            profile_id = self.store.pair_device(
                device_id, name, token, profile_name
            )
            self.prepare_profile_books(profile_id)
            self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
            self._pair_code_created = time.monotonic()
        self.pairing_code_changed.emit(self.pair_code)
        return profile_id

    def change_fingerprint(self, profile_id):
        directory = self.books_directory_for(profile_id)
        names = []
        try:
            for path in directory.glob("*.stbook"):
                names.append(f"{path.stem}:{path.stat().st_size}")
        except OSError:
            pass
        books = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:16]
        return f"{self.store.revision}x{books}"

    def books_directory_for(self, profile_id):
        if profile_id == "default":
            return self.books_directory
        return self.books_directory / "profiles" / profile_id

    def prepare_profile_books(self, profile_id):
        target = self.books_directory_for(profile_id)
        target.mkdir(parents=True, exist_ok=True)
        if target == self.books_directory:
            return
        for source in self.books_directory.glob("*.stbook"):
            destination = target / source.name
            if not destination.exists():
                shutil.copy2(source, destination)

    def stop(self):
        self._stop_event.set()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as wake:
                wake.sendto(b"STBOOK_WAKE", ("127.0.0.1", DISCOVERY_PORT))
        except OSError:
            pass

    def run(self):
        httpd = None
        udp = None
        try:
            httpd = _SyncHTTPServer(self)
            http_thread = threading.Thread(
                target=httpd.serve_forever, kwargs={"poll_interval": 0.25},
                name="SprachtrainerSyncHTTP", daemon=True,
            )
            http_thread.start()
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.bind(("", DISCOVERY_PORT))
            udp.settimeout(0.5)
            self.ready.emit(f"HTTP {HTTP_PORT}; pairing code {self.pair_code}")
            while not self._stop_event.is_set():
                try:
                    payload, address = udp.recvfrom(4096)
                except socket.timeout:
                    continue
                if payload != b"STBOOK_DISCOVER_V1":
                    continue
                response = json.dumps({
                    "service": "Sprachtrainer",
                    "version": 1,
                    "http_port": HTTP_PORT,
                    "name": socket.gethostname(),
                }).encode("utf-8")
                udp.sendto(response, address)
        except OSError as error:
            self.failed.emit(f"Sync server could not start: {error}")
        finally:
            if udp:
                udp.close()
            if httpd:
                httpd.shutdown()
                httpd.server_close()


class _SyncHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, owner):
        self.owner = owner
        super().__init__(("0.0.0.0", HTTP_PORT), _make_handler())


def _make_handler():
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "SprachtrainerSync/1"

        def log_message(self, format_string, *args):
            return

        def _send(self, status, body, token=None, body_hash=None, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if token and body_hash:
                signature = hmac.new(
                    token.encode("utf-8"),
                    f"{status}\n{body_hash}".encode("ascii"),
                    hashlib.sha256,
                ).hexdigest()
                self.send_header("X-ST-Response-Signature", signature)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, value, token=None):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(status, body, token, hashlib.sha256(body).hexdigest())

        def _read_body(self, maximum):
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > maximum:
                raise ValueError("Invalid request size.")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body.")
            return body

        def _authenticate(self, body, body_digest=None):
            owner = self.server.owner
            device_id = self.headers.get("X-ST-Device", "")
            token = owner.store.device_token(device_id)
            timestamp = self.headers.get("X-ST-Timestamp", "")
            nonce = self.headers.get("X-ST-Nonce", "")
            supplied = self.headers.get("X-ST-Signature", "")
            try:
                timestamp_number = int(timestamp)
            except ValueError:
                timestamp_number = 0
            if (
                not token
                or abs(int(time.time()) - timestamp_number) > 300
                or not re.fullmatch(r"[a-f0-9]{32}", nonce)
            ):
                return None
            if body_digest is None:
                body_digest = hashlib.sha256(body).hexdigest()
            signed = "\n".join((
                timestamp, nonce, self.command, self.path, body_digest
            )).encode("utf-8")
            expected = hmac.new(token.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, supplied):
                return None
            with owner._auth_lock:
                now = time.monotonic()
                owner._nonces = {
                    key: value
                    for key, value in owner._nonces.items()
                    if now - value < 600
                }
                nonce_key = f"{device_id}:{nonce}"
                if nonce_key in owner._nonces:
                    return None
                owner._nonces[nonce_key] = now
            return token

        def do_POST(self):
            if self.path != "/api/v1/pair":
                self._json(404, {"error": "Not found."})
                return
            try:
                data = json.loads(self._read_body(4096).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Invalid pairing request.")
                code = data.get("code")
                device_id = data.get("device_id")
                name = data.get("name", "Android device")
                profile_name = data.get("profile_name", "Default")
                if (
                    not isinstance(data, dict)
                    or not isinstance(code, str)
                    or not isinstance(device_id, str)
                    or not DEVICE_ID_PATTERN.fullmatch(device_id)
                    or not isinstance(name, str)
                    or not isinstance(profile_name, str)
                ):
                    raise ValueError("Invalid pairing request.")
                profile_id_for_name(profile_name)
                owner = self.server.owner
                now = time.monotonic()
                with owner._pair_attempts_lock:
                    attempts = owner._pair_attempts.get(
                        self.client_address[0], []
                    )
                    attempts = [
                        attempt for attempt in attempts if now - attempt < 60
                    ]
                    if len(attempts) >= 8:
                        owner._pair_attempts[self.client_address[0]] = attempts
                        self._json(429, {"error": "Too many pairing attempts."})
                        return
                    attempts.append(now)
                    owner._pair_attempts[self.client_address[0]] = attempts
                token = secrets.token_hex(32)
                profile_id = owner.pair_device(
                    code, device_id, name, token, profile_name
                )
                if not profile_id:
                    self._json(403, {"error": "Pairing code is incorrect."})
                    return
                self._json(200, {
                    "protocol_version": 2,
                    "device_id": device_id,
                    "token": token,
                    "profile_id": profile_id,
                    "profile_name": profile_name.strip()[:80],
                })
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self._json(400, {"error": str(error)})
            except OSError as error:
                self._json(500, {"error": f"Could not save paired device: {error}"})

        def _wait_for_changes(self, token):
            match = re.fullmatch(
                r"/api/v1/changes\?since=([0-9]{1,12}x[a-f0-9]{16})", self.path
            )
            owner = self.server.owner
            profile_id = owner.store.device_profile(
                self.headers.get("X-ST-Device", "")
            )
            since = match.group(1)
            deadline = time.monotonic() + 25
            while True:
                fingerprint = owner.change_fingerprint(profile_id)
                if (
                    fingerprint != since
                    or time.monotonic() >= deadline
                    or owner._stop_event.is_set()
                ):
                    break
                time.sleep(0.5)
            self._json(
                200,
                {"fingerprint": fingerprint, "changed": fingerprint != since},
                token,
            )

        def do_GET(self):
            if re.fullmatch(r"/api/v1/changes\?since=[0-9]{1,12}x[a-f0-9]{16}", self.path):
                token = self._authenticate(b"")
                if token is None:
                    self._json(401, {"error": "Authentication failed."})
                    return
                self._wait_for_changes(token)
                return
            if self.path == "/api/v1/books":
                body = b""
            elif self.path == "/api/v1/state":
                body = b""
            elif re.fullmatch(r"/api/v1/books/[a-f0-9]{64}", self.path):
                body = b""
            else:
                self._json(404, {"error": "Not found."})
                return
            token = self._authenticate(body)
            if token is None:
                self._json(401, {"error": "Authentication failed."})
                return
            if self.path == "/api/v1/state":
                profile_id = self.server.owner.store.device_profile(
                    self.headers.get("X-ST-Device", "")
                )
                self._json(
                    200, self.server.owner.store.public_state(profile_id), token
                )
                return
            if self.path == "/api/v1/books":
                profile_id = self.server.owner.store.device_profile(
                    self.headers.get("X-ST-Device", "")
                )
                books_directory = self.server.owner.books_directory_for(profile_id)
                books = []
                books_directory.mkdir(parents=True, exist_ok=True)
                for path in books_directory.glob("*.stbook"):
                    if not BOOK_ID_PATTERN.fullmatch(path.stem):
                        continue
                    books.append({"id": path.stem, "size": path.stat().st_size})
                self._json(
                    200, {"books": books, "profile_id": profile_id}, token
                )
                return
            book_id = self.path.rsplit("/", 1)[-1]
            profile_id = self.server.owner.store.device_profile(
                self.headers.get("X-ST-Device", "")
            )
            path = (
                self.server.owner.books_directory_for(profile_id)
                / f"{book_id}.stbook"
            )
            if not path.is_file():
                self._json(404, {"error": "Book not found."}, token)
                return
            body_hash = book_id
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.sprachtrainer.book")
            self.send_header("Content-Length", str(path.stat().st_size))
            signature = hmac.new(
                token.encode("utf-8"), f"200\n{body_hash}".encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            self.send_header("X-ST-Response-Signature", signature)
            self.end_headers()
            with path.open("rb") as file:
                while chunk := file.read(128 * 1024):
                    self.wfile.write(chunk)

        def do_PUT(self):
            is_book = re.fullmatch(r"/api/v1/books/[a-f0-9]{64}", self.path)
            if not is_book and self.path != "/api/v1/state":
                self._json(404, {"error": "Not found."})
                return
            maximum = MAX_BOOK_BYTES if is_book else MAX_JSON_BYTES
            temporary = None
            try:
                content_length = int(self.headers.get("Content-Length", "-1"))
                if content_length < 0 or content_length > maximum:
                    raise ValueError("Invalid request size.")
                claimed_digest = self.headers.get("X-ST-Content-SHA256", "")
                if not re.fullmatch(r"[a-f0-9]{64}", claimed_digest):
                    raise ValueError("Missing or invalid content digest.")
                token = self._authenticate(b"", claimed_digest)
                if token is None:
                    self._json(401, {"error": "Authentication failed."})
                    return
                if is_book:
                    digest = hashlib.sha256()
                    self.server.owner.books_directory.parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    fd, temporary = tempfile.mkstemp(
                        prefix="sprachtrainer-sync-", suffix=".stbook",
                        dir=self.server.owner.books_directory.parent,
                    )
                    with os.fdopen(fd, "wb") as file:
                        remaining = content_length
                        while remaining:
                            chunk = self.rfile.read(min(128 * 1024, remaining))
                            if not chunk:
                                raise ValueError("Incomplete request body.")
                            file.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                    body_hash = digest.hexdigest()
                    book_id = self.path.rsplit("/", 1)[-1]
                    if (
                        not hmac.compare_digest(book_id, body_hash)
                        or not hmac.compare_digest(claimed_digest, body_hash)
                    ):
                        raise ValueError(".stbook id does not match its SHA-256.")
                    body = b""
                else:
                    body = self.rfile.read(content_length)
                    if len(body) != content_length:
                        raise ValueError("Incomplete request body.")
                    body_hash = hashlib.sha256(body).hexdigest()
                    if not hmac.compare_digest(claimed_digest, body_hash):
                        raise ValueError("Request body does not match its SHA-256.")
                if is_book:
                    validate_stbook(temporary)
                    profile_id = self.server.owner.store.device_profile(
                        self.headers.get("X-ST-Device", "")
                    )
                    if book_id in self.server.owner.store.public_state(
                        profile_id
                    )["deleted_books"]:
                        self._json(200, {"id": book_id, "deleted": True}, token)
                        return
                    directory = self.server.owner.books_directory_for(profile_id)
                    directory.mkdir(parents=True, exist_ok=True)
                    os.replace(temporary, directory / f"{book_id}.stbook")
                    temporary = None
                    self.server.owner.book_received.emit(book_id)
                    self._json(200, {"id": book_id}, token)
                    return
                try:
                    state = json.loads(body.decode("utf-8"))
                    profile_id = self.server.owner.store.device_profile(
                        self.headers.get("X-ST-Device", "")
                    )
                    merged = self.server.owner.store.merge(state, profile_id)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    raise ValueError(f"Invalid sync state: {error}") from error
                self.server.owner.state_received.emit(profile_id, merged)
                self._json(200, merged, token)
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                self._json(400, {"error": str(error)})
            finally:
                if temporary:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Allow", "GET, POST, PUT, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler
