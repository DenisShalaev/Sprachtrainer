# Sprachtrainer Android client

The client opens `.stbook` files locally, plays their audio, displays sentence
translations and bundled images, and lets the learner mark words as known.
Tap a word to preview its bundled image; use the check button by the image to
mark it as known, or double-tap the word. The tapped word is highlighted in
its sentence translation when a translation is available. Tap a sentence card
outside a word to seek playback to that sentence.
Translations not present in the saved book are identified explicitly.
After analyzing a source on desktop, the app translates every unique sentence
into the selected translation language before publishing the book for sync.
If the translation service fails or rate-limits requests, the book is still
published with the translations that were obtained.
To update an already analyzed source, use the desktop refresh button (↻).
It reuses the transcript cache when available and only requests translations
that are not already cached, then rebuilds the book for sync.
Use its dropdown to retry only missing translations, explicitly re-run Whisper
without the saved transcript, or retry image loading for the current sentence.
The library shows a bundled-image cover when available and each book's audio
length in minutes; the header sync button starts an immediate sync. The player
shows elapsed and total playback time. New desktop analyses include Whisper word timestamps
for precise highlighting. Re-analyze the original audio on desktop and sync
again to upgrade older books that only contain sentence timestamps.
Books may have word timestamps for most sentences while a small number could
not be aligned automatically. These partial timings are still used; untimed
sentences fall back to sentence-level highlighting instead of disabling
word-level highlighting for the whole book.
During playback, the active sentence is scrolled to the top of the visible
sentence list.
Books, dictionary changes (including removals), and playback positions can be
synchronized with the desktop app over the same Wi-Fi network. After pairing,
the app syncs on launch and about once per minute while it remains open. Pull
down in the library to start an immediate sync.
Updates use millisecond timestamps; on an exact tie, known-word entries win
over removals and the later playback position wins.
Each device is assigned to a profile during pairing. Devices paired with the
same profile name share that profile's library, known words, and playback
positions; different names create isolated user profiles on the computer.
Names are normalized for matching, so capitalization and surrounding spaces do
not create different profiles. The current profile is shown in the library.
The mobile app limits both compressed and extracted book data to 512 MiB to
avoid excessive memory use while validating ZIP archives.

## Pairing and sync

Start the desktop app and choose **Sync with Android**. In the Android app,
choose **Pair / discover**, select the computer, and enter the six-digit
one-time code displayed by the desktop app. The code rotates after successful
pairing. Pull down in the library to transfer books and merge
dictionary/progress changes; the entry with the newer millisecond timestamp
wins.
To add another device for the same learner, pair it with the same profile name.
Use a different name for another learner; their book list, dictionary, and
playback positions stay separate. **Change profile** starts pairing again
intentionally; normal synchronization does not require repeated pairing.

UDP port `43981` is used only for local discovery; HTTP port `43982` carries
the paired sync protocol. The Android client verifies HMAC-SHA256 signatures
and book SHA-256 digests. Keep pairing to trusted private Wi-Fi networks:
the local HTTP transport is not encrypted.

## Development

The project requires Flutter 3.38 or newer. From this directory, run
`flutter pub get`, `flutter analyze`, and
`flutter test`. The app uses Android's `INTERNET` permission for local-network
discovery and sync. Android must also allow cleartext HTTP for this
trusted-LAN-only protocol; the pairing warning explains that sync traffic is
not encrypted.

After installing the Android SDK and accepting its licenses, build a debug APK
with `flutter build apk --debug`. The APK is written to
`build/app/outputs/flutter-apk/app-debug.apk`.
