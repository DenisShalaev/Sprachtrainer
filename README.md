# Sprachtrainer Ecosystem

A cross-platform language learning application designed to help users master German through context-driven audiovisual associations. The project consists of a powerful Desktop Hub (Python/PyQt6) for media preparation and an autonomous Mobile Client (Flutter/Android) for on-the-go learning.
<img width="1520" height="905" alt="Знімок екрана 2026-10-10 о 22 03 27" src="https://github.com/user-attachments/assets/a435fd69-627f-4b4c-875d-6f898527438b" />

## 🚀 Key Features

* **Contextual Visual Learning:** Replaces traditional translation with visual association. Uses Gemini 1.5 Flash to analyze sentence context and Google Imagen 3 to generate highly relevant, text-free images for unknown words.
* **Asynchronous Prefetching:** Employs a lazy-loading architecture to generate and cache images in the background, ensuring a smooth, uninterrupted reading and listening experience.
* **Cross-Platform Synchronization:** Features zero-configuration local networking (UDP Broadcast & REST API). Instantly syncs reading progress, known vocabulary (union merging logic), and library data between desktop and mobile devices.
* **Custom `.stbook` Format:** Packages text, timestamps, translations, audio, and generated images into a unified, offline-ready ZIP archive for mobile consumption.
* **Smart Audio Processing:** Integrates local OpenAI Whisper models to transcribe audio files into interactive, sentence-level segments.
* **Native TTS Support:** Converts plain text files into audio on the fly using the native macOS `say` utility on the desktop and Android TTS on mobile.
* **Multilingual UI & On-the-fly Translation:** The interface supports multiple languages and translates complex sentences directly via API.

## ⚙️ Core Modules & Functions

### Desktop Hub (Python / PyQt6)
* **`AnalyseThread`**: Handles background audio transcription using Whisper without blocking the main UI thread.
* **`TextAudioThread`**: Converts text documents into AIFF audio using local system voices.
* **`DiscoveryServerThread` & `SyncServerThread`**: Broadcasts the desktop hub's presence via UDP and provides a local REST API to merge dictionaries and update reading timestamps from mobile clients.
* **`BildLadeThread`**: Manages the intelligent fallback search and caching of images based on context strings.

### Mobile Client (Dart / Flutter)
<img width="615" height="1280" alt="Sprachtrainer 2026-10-24 09 35 47" src="https://github.com/user-attachments/assets/40a08200-f541-476b-8fd9-88711312a993" />

* **`ApiService`**: Connects to the Gemini API and Imagen 3 to generate contextual prompts and fetch base64 image data.
* **`PrefetchManager`**: Scans upcoming sentences and asynchronously generates and caches images locally before the user reaches them.
* **`AutoDiscoveryManager`**: Listens for UDP broadcasts to automatically detect the Desktop Hub's IP address on the local Wi-Fi network.
* **`BuchImportManager`**: Extracts and parses `.stbook` archives, instantly configuring the offline learning environment.
