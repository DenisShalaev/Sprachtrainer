import sys
import os
import re
import json
import base64
import hashlib
import math
import shutil
import subprocess
import string
import bisect
import time
import threading
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections import Counter
from html import escape, unescape

import whisper
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget,
                             QPushButton, QFileDialog, QHBoxLayout, QProgressBar,
                             QSlider, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
                             QFrame, QScrollArea, QTextBrowser)
from PyQt6.QtCore import (QTimer, Qt, QUrl, QThread, pyqtSignal, QRectF, QSettings,
                          QSignalBlocker)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtGui import (QPixmap, QImage, QPainter, QPainterPath, QColor, QFont,
                         QShortcut, QKeySequence, QIcon, QLinearGradient, QPen)

BASIS_ORDNER = os.path.dirname(os.path.abspath(__file__))
WOERTERBUCH_DATEI = os.path.join(BASIS_ORDNER, "bekannte_woerter.txt")
BILDER_ORDNER = os.path.join(BASIS_ORDNER, "bilder")
CACHE_ORDNER = os.path.join(BASIS_ORDNER, "cache")
SEEK_VORLAUF_MS = 40  # Sprung ein wenig in den Satz hinein (Rundung / Seek-Ungenauigkeit)
SATZZEICHEN = string.punctuation + " „“”‚‘’«»…–—"
ARTIKEL_WOERTER = {
    "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einen", "einem", "einer", "eines",
    "kein", "keine", "keinen", "keinem", "keiner", "keines",
    "mein", "meine", "meinen", "meinem", "meiner", "meines",
    "dein", "deine", "deinen", "deinem", "deiner", "deines",
    "sein", "seine", "seinen", "seinem", "seiner", "seines",
    "ihr", "ihre", "ihren", "ihrem", "ihrer", "ihres",
    "unser", "unsere", "unseren", "unserem", "unserer", "unseres",
    "euer", "eure", "euren", "eurem", "eurer", "eures",
    "dieser", "diese", "dieses", "diesen", "diesem",
    "jeder", "jede", "jedes", "jeden", "jedem",
    "welcher", "welche", "welches", "welchen", "welchem",
}
ZEIT_MENGEN_WOERTER = {
    "heute", "gestern", "morgen", "übermorgen", "vorgestern",
    "jetzt", "bald", "später", "früher", "sofort", "immer", "nie",
    "täglich", "wöchentlich", "monatlich", "jährlich",
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag",
    "samstag", "sonntag", "morgen", "vormittag", "mittag", "abend",
    "tag", "tage", "tagen", "tages", "nacht", "nächte", "woche", "wochen",
    "monat", "monate", "monaten", "jahr", "jahre", "jahren",
    "stunde", "stunden", "minute", "minuten", "sekunde", "sekunden",
    "vormittags", "mittags", "abends", "nachts",
    "viel", "viele", "vielen", "vieler", "vieles", "wenig", "wenige",
    "wenigen", "weniger", "mehr", "mehrere", "mehreren", "einige",
    "einigen", "einiger", "einmal", "zweimal", "doppelt", "halb",
    "paar", "zahlreich", "zahlreiche", "kilogramm", "kilo", "gramm",
    "liter", "milliliter", "kilometer", "meter", "zentimeter",
    "euro", "cent", "stück", "stücke", "prozent",
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben",
    "acht", "neun", "zehn", "elf", "zwölf", "dreizehn", "vierzehn",
    "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn",
    "zwanzig", "dreißig", "vierzig", "fünfzig", "hundert", "tausend",
}
SUCH_STOP_WOERTER = {
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "sich",
    "uns", "euch", "und", "oder", "aber", "weil", "dass", "wenn", "als",
    "wie", "in", "im", "am", "an", "auf", "aus", "bei", "mit", "nach",
    "von", "zu", "zum", "zur", "für", "über", "unter", "vor", "hinter",
    "durch", "gegen", "ohne", "um", "ist", "sind", "war", "waren", "bin",
    "bist", "hat", "haben", "wird", "werden", "wurde", "wurden", "kann",
    "können", "muss", "müssen", "soll", "sollen", "will", "wollen",
    "gehen", "gehe", "gehst", "geht", "ging", "gingen", "hin", "her",
    "man", "dann", "dort", "hier", "auch", "noch", "schon", "sehr",
    "nicht", "kein", "keine", "keinen",
}
BILD_SUCH_ALTERNATIVEN = {
    "vermehren": ("plant propagation",),
    "schwärmen": ("bee swarm",),
    "untersuchen": ("examination research",),
}

UI_TEXTE = {
    "title": {
        "ru": "Sprachtrainer v3", "uk": "Sprachtrainer v3",
        "en": "Sprachtrainer v3", "fr": "Sprachtrainer v3", "es": "Sprachtrainer v3",
    },
    "initial_status": {
        "ru": "Загрузите аудио- или текстовый файл.",
        "uk": "Завантажте аудіо- або текстовий файл.",
        "en": "Load an audio or text file.",
        "fr": "Chargez un fichier audio ou texte.",
        "es": "Carga un archivo de audio o texto.",
    },
    "preparing_text": {
        "ru": "Подготовка текста к воспроизведению…",
        "uk": "Підготовка тексту до відтворення…",
        "en": "Preparing text for playback…", "fr": "Préparation du texte pour la lecture…",
        "es": "Preparando el texto para reproducirlo…",
    },
    "changing_voice": {
        "ru": "Смена голоса и повторная синхронизация текста…",
        "uk": "Зміна голосу та повторна синхронізація тексту…",
        "en": "Changing voice and synchronizing text…",
        "fr": "Changement de voix et synchronisation du texte…",
        "es": "Cambiando la voz y sincronizando el texto…",
    },
    "analyzing": {
        "ru": "Идёт анализ…", "uk": "Триває аналіз…", "en": "Analyzing…",
        "fr": "Analyse en cours…", "es": "Analizando…",
    },
    "no_sentences": {
        "ru": "Предложения не распознаны.", "uk": "Речення не розпізнано.",
        "en": "No sentences were detected.", "fr": "Aucune phrase détectée.",
        "es": "No se detectaron frases.",
    },
    "press_play": {
        "ru": "Нажмите «Воспроизвести».", "uk": "Натисніть «Відтворити».",
        "en": "Press Play.", "fr": "Appuyez sur Lecture.", "es": "Pulsa Reproducir.",
    },
    "file_not_found": {
        "ru": "Файл не найден: {path}", "uk": "Файл не знайдено: {path}",
        "en": "File not found: {path}", "fr": "Fichier introuvable : {path}",
        "es": "No se encontró el archivo: {path}",
    },
    "recent_file_not_found": {
        "ru": "Последний файл не найден: {path}",
        "uk": "Останній файл не знайдено: {path}",
        "en": "The most recent file was not found: {path}",
        "fr": "Le dernier fichier est introuvable : {path}",
        "es": "No se encontró el último archivo: {path}",
    },
    "restoring": {
        "ru": "Восстановление последнего файла…",
        "uk": "Відновлення останнього файлу…",
        "en": "Restoring the last file…", "fr": "Restauration du dernier fichier…",
        "es": "Restaurando el último archivo…",
    },
    "system_voice_error": {
        "ru": "Не удалось загрузить системные голоса: {error}",
        "uk": "Не вдалося завантажити системні голоси: {error}",
        "en": "Could not load system voices: {error}",
        "fr": "Impossible de charger les voix système : {error}",
        "es": "No se pudieron cargar las voces del sistema: {error}",
    },
    "cached_transcript": {
        "ru": "Транскрипт загружен из кэша.", "uk": "Транскрипт завантажено з кешу.",
        "en": "Transcript loaded from cache.", "fr": "Transcription chargée du cache.",
        "es": "Transcripción cargada desde la caché.",
    },
    "analysis_ready": {
        "ru": "Анализ завершён. Можно воспроизводить.",
        "uk": "Аналіз завершено. Можна відтворювати.",
        "en": "Analysis complete. Ready to play.",
        "fr": "Analyse terminée. Prêt à lire.",
        "es": "Análisis completado. Listo para reproducir.",
    },
    "loading_model": {
        "ru": "Загрузка модели Whisper ({model})…",
        "uk": "Завантаження моделі Whisper ({model})…",
        "en": "Loading Whisper model ({model})…",
        "fr": "Chargement du modèle Whisper ({model})…",
        "es": "Cargando el modelo Whisper ({model})…",
    },
    "analyzing_audio": {
        "ru": "Анализ аудио по предложениям (подождите)…",
        "uk": "Аналіз аудіо за реченнями (зачекайте)…",
        "en": "Analyzing audio by sentence (please wait)…",
        "fr": "Analyse de l'audio phrase par phrase (patientez)…",
        "es": "Analizando el audio por frases (espera)…",
    },
    "analysis_error": {
        "ru": "Ошибка анализа: {error}", "uk": "Помилка аналізу: {error}",
        "en": "Analysis error: {error}", "fr": "Erreur d'analyse : {error}",
        "es": "Error de análisis: {error}",
    },
    "text_read_error": {
        "ru": "Не удалось озвучить текст: {error}",
        "uk": "Не вдалося озвучити текст: {error}",
        "en": "Could not read the text aloud: {error}",
        "fr": "Impossible de lire le texte à voix haute : {error}",
        "es": "No se pudo leer el texto en voz alta: {error}",
    },
    "image_not_found_error": {
        "ru": "Подходящее изображение не найдено для слова «{word}».",
        "uk": "Не знайдено відповідного зображення для слова «{word}».",
        "en": "No suitable image found for “{word}”.",
        "fr": "Aucune image adaptée trouvée pour « {word} ».",
        "es": "No se encontró una imagen adecuada para «{word}».",
    },
    "image_load_error": {
        "ru": "Не удалось загрузить изображение для слова «{word}»: {error}",
        "uk": "Не вдалося завантажити зображення для слова «{word}»: {error}",
        "en": "Could not load an image for “{word}”: {error}",
        "fr": "Impossible de charger une image pour « {word} » : {error}",
        "es": "No se pudo cargar una imagen para «{word}»: {error}",
    },
    "load_file": {
        "ru": "📂  Открыть файл", "uk": "📂  Відкрити файл",
        "en": "📂  Open file", "fr": "📂  Ouvrir un fichier", "es": "📂  Abrir archivo",
    },
    "previous_sentence": {
        "ru": "Предыдущее предложение (←)", "uk": "Попереднє речення (←)",
        "en": "Previous sentence (←)", "fr": "Phrase précédente (←)", "es": "Frase anterior (←)",
    },
    "repeat_tooltip": {
        "ru": "Прослушать предложение ещё раз (R)", "uk": "Прослухати речення ще раз (R)",
        "en": "Listen to the sentence again (R)", "fr": "Réécouter la phrase (R)",
        "es": "Escuchar la frase de nuevo (R)",
    },
    "remember_tooltip": {
        "ru": "Запомнить выделенное слово и перейти дальше (пробел)",
        "uk": "Запам'ятати виділене слово й перейти далі (пробіл)",
        "en": "Remember the selected word and move on (Space)",
        "fr": "Mémoriser le mot sélectionné et continuer (Espace)",
        "es": "Memorizar la palabra seleccionada y continuar (Espacio)",
    },
    "skip_tooltip": {
        "ru": "Перейти к следующему новому слову (Enter)",
        "uk": "Перейти до наступного нового слова (Enter)",
        "en": "Move to the next new word (Enter)",
        "fr": "Passer au prochain nouveau mot (Entrée)",
        "es": "Ir a la siguiente palabra nueva (Enter)",
    },
    "remembered_tooltip": {
        "ru": "Щелчок — отметить слово как известное",
        "uk": "Клацніть, щоб позначити слово як відоме",
        "en": "Click to mark this word as known",
        "fr": "Cliquez pour marquer ce mot comme connu",
        "es": "Haz clic para marcar esta palabra como conocida",
    },
    "no_image": {
        "ru": "Изображение не найдено", "uk": "Зображення не знайдено",
        "en": "No image found", "fr": "Aucune image trouvée", "es": "No se encontró ninguna imagen",
    },
    "no_new_words": {
        "ru": "В этом предложении нет новых слов ✔",
        "uk": "У цьому реченні немає нових слів ✔",
        "en": "No new words in this sentence ✔",
        "fr": "Aucun nouveau mot dans cette phrase ✔",
        "es": "No hay palabras nuevas en esta frase ✔",
    },
    "image_info": {
        "ru": "Картинка из Openverse\nПоисковый запрос: {query}\nУточнённый запрос: {translated_query}\nЗаголовок: {title}\nОписание: {description}\nТеги: {tags}\nСовпавшие слова контекста: {context}\nСовпадение целевого слова: {target}\nИсточник: {source}{refinement_error}",
        "uk": "Зображення з Openverse\nПошуковий запит: {query}\nУточнений запит: {translated_query}\nЗаголовок: {title}\nОпис: {description}\nТеги: {tags}\nЗбіглі слова контексту: {context}\nЗбіг цільового слова: {target}\nДжерело: {source}{refinement_error}",
        "en": "Image from Openverse\nSearch query: {query}\nRefined query: {translated_query}\nTitle: {title}\nDescription: {description}\nTags: {tags}\nMatching context words: {context}\nTarget word matched in: {target}\nSource: {source}{refinement_error}",
        "fr": "Image de Openverse\nRecherche : {query}\nRecherche affinée : {translated_query}\nTitre : {title}\nDescription : {description}\nTags : {tags}\nMots du contexte correspondants : {context}\nMot cible trouvé dans : {target}\nSource : {source}{refinement_error}",
        "es": "Imagen de Openverse\nBúsqueda: {query}\nBúsqueda refinada: {translated_query}\nTítulo: {title}\nDescripción: {description}\nEtiquetas: {tags}\nPalabras del contexto coincidentes: {context}\nPalabra objetivo encontrada en: {target}\nFuente: {source}{refinement_error}",
    },
    "image_openverse": {
        "ru": "Openverse · метаданные", "uk": "Openverse · метадані",
        "en": "Openverse · metadata", "fr": "Openverse · métadonnées",
        "es": "Openverse · metadatos",
    },
    "image_gemini": {
        "ru": "Gemini · сгенерировано", "uk": "Gemini · згенеровано",
        "en": "Gemini · generated", "fr": "Gemini · générée",
        "es": "Gemini · generada",
    },
    "image_gemini_loading": {
        "ru": "Создаю иллюстрацию…", "uk": "Створюю ілюстрацію…",
        "en": "Generating illustration…", "fr": "Génération de l’illustration…",
        "es": "Generando ilustración…",
    },
    "image_gemini_no_key": {
        "ru": "Для генерации задайте GEMINI_API_KEY и перезапустите приложение.",
        "uk": "Для генерації задайте GEMINI_API_KEY і перезапустіть програму.",
        "en": "Set GEMINI_API_KEY and restart the app to generate images.",
        "fr": "Définissez GEMINI_API_KEY et redémarrez l’application pour générer des images.",
        "es": "Configura GEMINI_API_KEY y reinicia la aplicación para generar imágenes.",
    },
    "image_gemini_error": {
        "ru": "Gemini не смог создать иллюстрацию: {error}",
        "uk": "Gemini не зміг створити ілюстрацію: {error}",
        "en": "Gemini could not generate the illustration: {error}",
        "fr": "Gemini n’a pas pu générer l’illustration : {error}",
        "es": "Gemini no pudo generar la ilustración: {error}",
    },
    "image_rate_up": {
        "ru": "Подходит", "uk": "Підходить", "en": "Relevant",
        "fr": "Pertinente", "es": "Adecuada",
    },
    "image_rate_down": {
        "ru": "Не подходит", "uk": "Не підходить", "en": "Not relevant",
        "fr": "Non pertinente", "es": "No adecuada",
    },
    "image_retry": {
        "ru": "Создать", "uk": "Створити", "en": "Generate",
        "fr": "Générer", "es": "Generar",
    },
    "image_target_description": {
        "ru": "описание", "uk": "опис", "en": "description",
        "fr": "description", "es": "descripción",
    },
    "image_target_gemini_terms": {
        "ru": "переведённые Gemini понятия", "uk": "перекладені Gemini поняття",
        "en": "Gemini-translated concepts", "fr": "concepts traduits par Gemini",
        "es": "conceptos traducidos por Gemini",
    },
    "image_query_refinement_error": {
        "ru": "\nНе удалось уточнить запрос через Gemini: {error}",
        "uk": "\nНе вдалося уточнити запит через Gemini: {error}",
        "en": "\nGemini query refinement failed: {error}",
        "fr": "\nL’affinage de la recherche avec Gemini a échoué : {error}",
        "es": "\nNo se pudo refinar la búsqueda con Gemini: {error}",
    },
    "image_match_warning": {
        "ru": "Подбор сделан по текстовым метаданным; смысл изображения автоматически не проверяется.",
        "uk": "Зображення підібрано за текстовими метаданими; його зміст автоматично не перевіряється.",
        "en": "Selection uses text metadata; the image's actual meaning is not checked automatically.",
        "fr": "La sélection repose sur les métadonnées textuelles ; le sens réel de l'image n'est pas vérifié automatiquement.",
        "es": "La selección usa metadatos textuales; el significado real de la imagen no se verifica automáticamente.",
    },
    "image_gemini_warning": {
        "ru": "Иллюстрация создана ИИ по слову и контексту; её смысл тоже нужно проверить.",
        "uk": "Ілюстрацію створено ШІ за словом і контекстом; її зміст також варто перевірити.",
        "en": "AI-generated from the word and context; verify that the image conveys the intended meaning.",
        "fr": "Générée par IA à partir du mot et du contexte ; vérifiez qu’elle exprime bien le sens voulu.",
        "es": "Generada por IA a partir de la palabra y el contexto; comprueba que refleje el significado deseado.",
    },
    "image_info_legacy": {
        "ru": "Для этой сохранённой картинки метаданные поиска отсутствуют. Она была найдена по слову и контексту предложения.",
        "uk": "Для цього збереженого зображення немає метаданих пошуку. Його знайдено за словом і контекстом речення.",
        "en": "Search details are unavailable for this cached image. It was found using the word and sentence context.",
        "fr": "Les détails de recherche ne sont pas disponibles pour cette image en cache. Elle a été trouvée à partir du mot et du contexte de la phrase.",
        "es": "No hay detalles de búsqueda para esta imagen guardada. Se encontró usando la palabra y el contexto de la frase.",
    },
    "image_info_unavailable": {
        "ru": "Не удалось прочитать данные о подборе изображения: {error}",
        "uk": "Не вдалося прочитати дані про пошук зображення: {error}",
        "en": "Could not read image matching details: {error}",
        "fr": "Impossible de lire les détails de correspondance de l'image : {error}",
        "es": "No se pudieron leer los detalles de coincidencia de la imagen: {error}",
    },
    "image_info_save_error": {
        "ru": "Изображение загружено, но пояснение сохранить не удалось: {error}",
        "uk": "Зображення завантажено, але пояснення не вдалося зберегти: {error}",
        "en": "Image downloaded, but its matching details could not be saved: {error}",
        "fr": "Image téléchargée, mais ses détails de correspondance n'ont pas pu être enregistrés : {error}",
        "es": "La imagen se descargó, pero no se pudieron guardar los detalles: {error}",
    },
    "image_unknown_title": {
        "ru": "без заголовка", "uk": "без заголовка", "en": "untitled",
        "fr": "sans titre", "es": "sin título",
    },
    "image_no_tags": {
        "ru": "нет тегов", "uk": "немає тегів", "en": "no tags",
        "fr": "aucun tag", "es": "sin etiquetas",
    },
    "image_no_description": {
        "ru": "описание отсутствует", "uk": "опис відсутній",
        "en": "no description", "fr": "aucune description",
        "es": "sin descripción",
    },
    "image_source_missing": {
        "ru": "не указан", "uk": "не вказано", "en": "not provided",
        "fr": "non indiqué", "es": "no indicada",
    },
    "image_target_title": {
        "ru": "заголовок изображения", "uk": "заголовок зображення",
        "en": "image title", "fr": "titre de l'image", "es": "título de la imagen",
    },
    "image_target_tags": {
        "ru": "теги изображения", "uk": "теги зображення",
        "en": "image tags", "fr": "tags de l'image", "es": "etiquetas de la imagen",
    },
    "image_target_title_tags": {
        "ru": "заголовок и теги изображения", "uk": "заголовок і теги зображення",
        "en": "image title and tags", "fr": "titre et tags de l'image",
        "es": "título y etiquetas de la imagen",
    },
    "image_target_alternative": {
        "ru": "синонимичный запрос", "uk": "синонімічний запит",
        "en": "alternative search query", "fr": "recherche alternative",
        "es": "búsqueda alternativa",
    },
    "image_no_context_match": {
        "ru": "контекстные слова в метаданных не совпали",
        "uk": "контекстні слова в метаданих не збіглися",
        "en": "no context words matched the metadata",
        "fr": "aucun mot du contexte ne correspond aux métadonnées",
        "es": "ninguna palabra del contexto coincidió con los metadatos",
    },
    "play": {
        "ru": "▶  Воспроизвести", "uk": "▶  Відтворити",
        "en": "▶  Play", "fr": "▶  Lire", "es": "▶  Reproducir",
    },
    "pause": {
        "ru": "⏸  Пауза", "uk": "⏸  Пауза",
        "en": "⏸  Pause", "fr": "⏸  Pause", "es": "⏸  Pausa",
    },
    "next_sentence": {
        "ru": "Следующее предложение (→)", "uk": "Наступне речення (→)",
        "en": "Next sentence (→)", "fr": "Phrase suivante (→)", "es": "Frase siguiente (→)",
    },
    "repeat_sentence": {
        "ru": "🔁  Повторить", "uk": "🔁  Повторити",
        "en": "🔁  Repeat", "fr": "🔁  Répéter", "es": "🔁  Repetir",
    },
    "remember": {
        "ru": "✔  Запомнил", "uk": "✔  Запам'ятав",
        "en": "✔  Known", "fr": "✔  Mémorisé", "es": "✔  Aprendida",
    },
    "skip": {
        "ru": "→  Далее", "uk": "→  Далі",
        "en": "→  Skip", "fr": "→  Passer", "es": "→  Siguiente",
    },
    "translation": {
        "ru": "Перевод:", "uk": "Переклад:",
        "en": "Translation:", "fr": "Traduction :", "es": "Traducción:",
    },
    "translation_tooltip": {
        "ru": "Перевод сначала запрашивается у MyMemory; при ошибке используется Gemini, если задан GEMINI_API_KEY.",
        "uk": "Переклад спочатку запитується в MyMemory; у разі помилки використовується Gemini, якщо задано GEMINI_API_KEY.",
        "en": "Translation uses MyMemory first, then Gemini if it fails and GEMINI_API_KEY is set.",
        "fr": "La traduction utilise d’abord MyMemory, puis Gemini en cas d’échec si GEMINI_API_KEY est défini.",
        "es": "La traducción usa primero MyMemory y luego Gemini si falla y GEMINI_API_KEY está configurada.",
    },
    "translation_word_match_tooltip": {
        "ru": "В переводе выделяется только слово с точно таким же написанием, как у выбранного немецкого слова. Переводные эквиваленты не угадываются.",
        "uk": "У перекладі виділяється лише слово з точно таким самим написанням, як у вибраного німецького слова. Перекладні відповідники не вгадуються.",
        "en": "Only an exact spelling match for the selected German word is highlighted. Translated equivalents are not guessed.",
        "fr": "Seul un mot écrit exactement comme le mot allemand sélectionné est surligné. Les équivalents traduits ne sont pas devinés.",
        "es": "Solo se resalta una palabra escrita exactamente igual que la palabra alemana seleccionada. No se adivinan equivalentes traducidos.",
    },
    "model": {
        "ru": "Модель:", "uk": "Модель:", "en": "Model:",
        "fr": "Modèle :", "es": "Modelo:",
    },
    "model_tooltip": {
        "ru": "Модель Whisper (больше — точнее, но медленнее).",
        "uk": "Модель Whisper (більша — точніша, але повільніша).",
        "en": "Whisper model (larger is more accurate but slower).",
        "fr": "Modèle Whisper (plus grand : plus précis, mais plus lent).",
        "es": "Modelo Whisper (más grande: más preciso, pero más lento).",
    },
    "speed": {
        "ru": "Скорость:", "uk": "Швидкість:", "en": "Speed:",
        "fr": "Vitesse :", "es": "Velocidad:",
    },
    "text_voice": {
        "ru": "Голос для текста:", "uk": "Голос для тексту:",
        "en": "Text voice:", "fr": "Voix du texte :", "es": "Voz del texto:",
    },
    "no_voices": {
        "ru": "Нет доступных немецких голосов", "uk": "Немає доступних німецьких голосів",
        "en": "No German system voices available", "fr": "Aucune voix allemande disponible",
        "es": "No hay voces alemanas disponibles",
    },
    "autopause": {
        "ru": "Пауза в конце предложения с новыми словами",
        "uk": "Пауза наприкінці речення з новими словами",
        "en": "Pause after sentences with new words",
        "fr": "Pause après les phrases avec de nouveaux mots",
        "es": "Pausar tras frases con palabras nuevas",
    },
    "autopause_tooltip": {
        "ru": "Пауза в конце предложения с новыми словами. Пробел или Enter — продолжить.",
        "uk": "Пауза наприкінці речення з новими словами. Пробіл або Enter — продовжити.",
        "en": "Pause at the end of sentences with new words. Space or Enter continues.",
        "fr": "Pause à la fin des phrases contenant de nouveaux mots. Espace ou Entrée pour continuer.",
        "es": "Pausa al final de frases con palabras nuevas. Espacio o Enter para continuar.",
    },
    "hint": {
        "ru": "Пробел: запомнить слово · Enter: пропустить · ↑/↓: выбрать слово · Щелчок по слову: выбрать · Щелчок по изображению: запомнить · P: пауза · R: повтор · ←/→: перейти к предложению · Ctrl+Z: отменить",
        "uk": "Пробіл: запам'ятати слово · Enter: пропустити · ↑/↓: вибрати слово · Клацання по слову: вибрати · Клацання по зображенню: запам'ятати · P: пауза · R: повтор · ←/→: перейти до речення · Ctrl+Z: скасувати",
        "en": "Space: remember word · Enter: skip · ↑/↓: select word · Click a word: select · Click image: remember · P: pause · R: repeat · ←/→: change sentence · Ctrl+Z: undo",
        "fr": "Espace : mémoriser · Entrée : passer · ↑/↓ : choisir un mot · Clic sur un mot : choisir · Clic sur l'image : mémoriser · P : pause · R : répéter · ←/→ : changer de phrase · Ctrl+Z : annuler",
        "es": "Espacio: memorizar palabra · Enter: omitir · ↑/↓: elegir palabra · Clic en una palabra: elegir · Clic en la imagen: memorizar · P: pausa · R: repetir · ←/→: cambiar frase · Ctrl+Z: deshacer",
    },
    "analyzed_files": {
        "ru": "Проанализированные файлы", "uk": "Проаналізовані файли",
        "en": "Analyzed files", "fr": "Fichiers analysés", "es": "Archivos analizados",
    },
    "new_words": {
        "ru": "Новые слова в этом файле", "uk": "Нові слова в цьому файлі",
        "en": "New words in this file", "fr": "Nouveaux mots dans ce fichier",
        "es": "Palabras nuevas en este archivo",
    },
    "undo": {
        "ru": "↩  Отменить", "uk": "↩  Скасувати",
        "en": "↩  Undo", "fr": "↩  Annuler", "es": "↩  Deshacer",
    },
    "stats": {
        "ru": "Новых слов в этом файле: {new}\nВсего известных слов: {known}",
        "uk": "Нових слів у цьому файлі: {new}\nУсього відомих слів: {known}",
        "en": "New in this file: {new}\nKnown words total: {known}",
        "fr": "Nouveaux dans ce fichier : {new}\nMots connus au total : {known}",
        "es": "Nuevas en este archivo: {new}\nPalabras conocidas en total: {known}",
    },
    "placeholder": {
        "ru": "Загрузите файл, чтобы начать", "uk": "Завантажте файл, щоб почати",
        "en": "Load a file to get started", "fr": "Chargez un fichier pour commencer",
        "es": "Carga un archivo para empezar",
    },
    "choose_file_title": {
        "ru": "Выберите аудио- или текстовый файл", "uk": "Виберіть аудіо- або текстовий файл",
        "en": "Choose an audio or text file", "fr": "Choisir un fichier audio ou texte",
        "es": "Elige un archivo de audio o texto",
    },
    "supported_files": {
        "ru": "Поддерживаемые файлы (*.mp3 *.wav *.m4a *.ogg *.txt)",
        "uk": "Підтримувані файли (*.mp3 *.wav *.m4a *.ogg *.txt)",
        "en": "Supported files (*.mp3 *.wav *.m4a *.ogg *.txt)",
        "fr": "Fichiers pris en charge (*.mp3 *.wav *.m4a *.ogg *.txt)",
        "es": "Archivos compatibles (*.mp3 *.wav *.m4a *.ogg *.txt)",
    },
    "translation_loading": {
        "ru": "Перевод загружается…", "uk": "Переклад завантажується…",
        "en": "Loading translation…", "fr": "Traduction en cours…",
        "es": "Cargando traducción…",
    },
    "translation_rate_limited": {
        "ru": "Сервис переводов временно ограничил запросы. Повторите через {time}.",
        "uk": "Сервіс перекладу тимчасово обмежив запити. Спробуйте через {time}.",
        "en": "The translation service is temporarily rate-limiting requests. Try again in {time}.",
        "fr": "Le service de traduction limite temporairement les requêtes. Réessayez dans {time}.",
        "es": "El servicio de traducción limita temporalmente las solicitudes. Inténtalo en {time}.",
    },
    "translation_retry_tooltip": {
        "ru": "Повторить перевод текущего предложения",
        "uk": "Повторити переклад поточного речення",
        "en": "Retry translation for the current sentence",
        "fr": "Réessayer la traduction de la phrase actuelle",
        "es": "Reintentar la traducción de la frase actual",
    },
    "translation_error": {
        "ru": "Перевод недоступен: {error}", "uk": "Переклад недоступний: {error}",
        "en": "Translation unavailable: {error}", "fr": "Traduction indisponible : {error}",
        "es": "Traducción no disponible: {error}",
    },
    "marked": {
        "ru": "Запомнено: {words}", "uk": "Запам'ятовано: {words}",
        "en": "Remembered: {words}", "fr": "Mémorisé : {words}",
        "es": "Memorizadas: {words}",
    },
    "undone": {
        "ru": "Отменено: {words}", "uk": "Скасовано: {words}",
        "en": "Undo: {words}", "fr": "Annulé : {words}", "es": "Deshecho: {words}",
    },
}


def deutsche_systemstimmen():
    ausgabe = subprocess.run(
        ["/usr/bin/say", "-v", "?"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    stimmen = []
    for zeile in ausgabe.splitlines():
        treffer = re.match(r"^(.+?)\s+(de_[A-Z]{2})(?:\s|$)", zeile)
        if treffer:
            stimmen.append((treffer.group(1).strip(), treffer.group(2)))
    return stimmen


def erstelle_app_icon():
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    hintergrund = QPainterPath()
    hintergrund.addRoundedRect(4, 4, 120, 120, 28, 28)
    farbverlauf = QLinearGradient(4, 4, 124, 124)
    farbverlauf.setColorAt(0, QColor("#9a7bff"))
    farbverlauf.setColorAt(1, QColor("#6242df"))
    p.fillPath(hintergrund, farbverlauf)

    p.setPen(QPen(QColor("#ffffff"), 7, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    buch = QPainterPath()
    buch.moveTo(64, 48)
    buch.cubicTo(49, 36, 34, 36, 22, 42)
    buch.lineTo(22, 83)
    buch.cubicTo(38, 77, 52, 80, 64, 91)
    buch.cubicTo(76, 80, 90, 77, 106, 83)
    buch.lineTo(106, 42)
    buch.cubicTo(94, 36, 79, 36, 64, 48)
    p.drawPath(buch)
    p.drawLine(64, 49, 64, 90)
    p.end()

    return QIcon(pixmap)


def bild_pfad(wort_lower):
    """Dateiname für das Bild eines Wortes (Sonderzeichen werden ersetzt)."""
    sauber = re.sub(r"[^\w\-]", "_", wort_lower)
    return os.path.join(BILDER_ORDNER, sauber + "_context5.jpg")


def openverse_bild_pfade(wort_lower):
    hauptpfad = bild_pfad(wort_lower)
    stamm, endung = os.path.splitext(hauptpfad)
    return [hauptpfad, f"{stamm}_2{endung}", f"{stamm}_3{endung}"]


def gemini_bild_pfad(wort_lower):
    sauber = re.sub(r"[^\w\-]", "_", wort_lower)
    return os.path.join(BILDER_ORDNER, sauber + "_gemini.png")


def bild_info_pfad(pfad):
    return os.path.splitext(pfad)[0] + ".json"


def bild_wort_muster(wort):
    """Match the word itself and common German inflected endings."""
    formen = {wort.casefold()}
    for endung in ("er", "en", "es", "em", "e", "s"):
        if wort.casefold().endswith(endung):
            stamm = wort.casefold()[:-len(endung)]
            if len(stamm) >= 5:
                formen.add(stamm)
                formen.update(stamm + suffix for suffix in ("e", "en", "er", "es", "em"))
    muster = "|".join(sorted((re.escape(form) for form in formen), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{muster})(?!\w)", re.IGNORECASE)


def bild_suchbegriff(tokens, ziel_index):
    """Add nearby articles and time/quantity expressions to an image search."""
    relevante_indices = {ziel_index}
    wort_indices = [
        i for i, token in enumerate(tokens)
        if ist_wort(token["rein"])
        or re.fullmatch(r"\d+(?:[.,]\d+)?", token["rein"])
    ]
    ziel_position = wort_indices.index(ziel_index)
    links = wort_indices[max(0, ziel_position - 3):ziel_position]
    rechts = wort_indices[ziel_position + 1:ziel_position + 4]

    artikel_index = next(
        (i for i in reversed(links) if tokens[i]["rein"].lower() in ARTIKEL_WOERTER),
        None,
    )
    if artikel_index is not None:
        relevante_indices.add(artikel_index)

    for i in (*links, *rechts):
        wort = tokens[i]["rein"].lower()
        if wort in ZEIT_MENGEN_WOERTER or re.fullmatch(r"\d+(?:[.,]\d+)?", wort):
            relevante_indices.add(i)
        elif wort not in ARTIKEL_WOERTER and wort not in SUCH_STOP_WOERTER:
            relevante_indices.add(i)

    return " ".join(tokens[i]["rein"] for i in sorted(relevante_indices))


def format_zeit(ms):
    s = max(0, int(ms // 1000))
    stunden, rest = divmod(s, 3600)
    minuten, sekunden = divmod(rest, 60)
    if stunden:
        return f"{stunden:02d}:{minuten:02d}:{sekunden:02d}"
    return f"{minuten:02d}:{sekunden:02d}"


def ist_wort(text):
    """Nur Tokens mit mindestens einem Buchstaben zählen als Wort (keine reinen Zahlen)."""
    return bool(text) and any(c.isalpha() for c in text)


def gemini_interaction(prompt, modell, timeout=60):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    anfrage = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps({
            "model": modell,
            "input": [{"type": "text", "text": prompt}],
            "store": False,
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            return json.load(antwort)
    except urllib.error.HTTPError as error:
        details = error.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {error.code}: {details}") from error


def gemini_output_text(ergebnis):
    text = ergebnis.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    for ausgabe in ergebnis.get("output", []):
        if not isinstance(ausgabe, dict):
            continue
        if ausgabe.get("type") == "text" and ausgabe.get("text"):
            return str(ausgabe["text"]).strip()
    raise RuntimeError("Gemini returned no text.")


def gemini_bild_suchdaten(wort, kontext):
    prompt = (
        "You improve image-search relevance for a German vocabulary learner. "
        "Resolve the intended sense of the German target word using its sentence "
        "context. Return only valid JSON with three fields: "
        '"query" (a concise English image-search query), '
        '"target_terms" (an array of 2-5 short English words or phrases that '
        "name the target concept and its common forms), and "
        '"context_terms" (an array of 2-6 short English words for visible '
        "context clues). Do not include explanations.\n"
        f"German target: {wort}\nGerman sentence context: {kontext}"
    )
    text = gemini_output_text(
        gemini_interaction(prompt, "gemini-3.8-flash", timeout=30)
    )
    start = text.find("{")
    ende = text.rfind("}")
    if start < 0 or ende < start:
        raise ValueError("Gemini returned no JSON image-search terms.")
    daten = json.loads(text[start:ende + 1])
    query = daten.get("query")
    zielwoerter = daten.get("target_terms")
    kontextwoerter = daten.get("context_terms")
    if (not isinstance(query, str) or not query.strip()
            or not isinstance(zielwoerter, list)
            or not isinstance(kontextwoerter, list)):
        raise ValueError("Gemini returned invalid image-search terms.")
    zielwoerter = [
        eintrag.strip()[:80] for eintrag in zielwoerter
        if isinstance(eintrag, str) and eintrag.strip()
    ][:5]
    kontextwoerter = [
        eintrag.strip()[:80] for eintrag in kontextwoerter
        if isinstance(eintrag, str) and eintrag.strip()
    ][:6]
    if not zielwoerter:
        raise ValueError("Gemini returned no target search terms.")
    return query.strip()[:180], zielwoerter, kontextwoerter


# --------------------------------------------------------------------------- #
#  Hintergrund-Thread: Whisper (Satzebene) + Bilder laden
# --------------------------------------------------------------------------- #
class AnalyseThread(QThread):
    analyse_beendet = pyqtSignal(object)
    status_update = pyqtSignal(str)

    def __init__(self, mp3_pfad, modell_name):
        super().__init__()
        self.mp3_pfad = mp3_pfad
        self.modell_name = modell_name

    def cache_pfad(self):
        st = os.stat(self.mp3_pfad)
        schluessel = f"{os.path.abspath(self.mp3_pfad)}|{st.st_mtime_ns}|{self.modell_name}_segments"
        h = hashlib.md5(schluessel.encode("utf-8")).hexdigest()
        return os.path.join(CACHE_ORDNER, h + ".json")

    def run(self):
        try:
            os.makedirs(BILDER_ORDNER, exist_ok=True)
            os.makedirs(CACHE_ORDNER, exist_ok=True)
            cache = self.cache_pfad()

            daten = None
            if os.path.exists(cache):
                try:
                    with open(cache, "r", encoding="utf-8") as f:
                        daten = json.load(f)
                    if not isinstance(daten, dict) or "segmente" not in daten:
                        daten = None
                except (OSError, ValueError):
                    daten = None  # beschädigter Cache -> neu transkribieren
            if daten is not None:
                self.status_update.emit("Transkript aus dem Cache geladen.")
            else:
                daten = self.transkribiere()
                with open(cache, "w", encoding="utf-8") as f:
                    json.dump(daten, f, ensure_ascii=False)

            self.status_update.emit("Analyse abgeschlossen. Bereit zum Abspielen.")
            self.analyse_beendet.emit(daten)
        except Exception as e:
            self.status_update.emit(f"Fehler bei der Analyse: {e}")
            self.analyse_beendet.emit(None)

    def transkribiere(self):
        if not shutil.which("ffmpeg"):
            for verzeichnis in ("/opt/homebrew/bin", "/usr/local/bin"):
                ffmpeg_pfad = os.path.join(verzeichnis, "ffmpeg")
                if os.path.isfile(ffmpeg_pfad) and os.access(ffmpeg_pfad, os.X_OK):
                    os.environ["PATH"] = verzeichnis + os.pathsep + os.environ.get("PATH", "")
                    break
        if not shutil.which("ffmpeg"):
            raise FileNotFoundError(
                "ffmpeg не найден. Установите его командой «brew install ffmpeg»."
            )

        self.status_update.emit(f"Whisper-Modell wird geladen ({self.modell_name})...")
        modell = whisper.load_model(self.modell_name)
        self.status_update.emit("Audio wird nach Sätzen analysiert (bitte warten)...")
        ergebnis = modell.transcribe(
            self.mp3_pfad,
            word_timestamps=False,  # schneller, es reicht die Satzebene
            language="de",
            fp16=modell.device.type != "cpu",
        )

        segmente = []
        for segment in ergebnis.get("segments", []):
            text = segment.get("text", "").strip()
            if not text:
                continue
            tokens = []
            for token in re.split(r"(\s+)", text):
                if token == "":
                    continue
                tokens.append({"roh": token, "rein": token.strip(SATZZEICHEN)})
            segmente.append({"start": segment["start"], "ende": segment["end"], "tokens": tokens})
        return {"segmente": segmente}


class TextAudioThread(QThread):
    fertig = pyqtSignal(str, str)

    def __init__(self, text_pfad, stimme, parent=None):
        super().__init__(parent)
        self.text_pfad = text_pfad
        self.stimme = stimme

    def run(self):
        try:
            with open(self.text_pfad, "rb") as f:
                rohtext = f.read()
            try:
                text = rohtext.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = rohtext.decode("cp1252")
            text = text.strip()
            if not text:
                raise ValueError("Die Textdatei ist leer.")

            if not self.stimme:
                raise RuntimeError("Kein deutscher macOS-Systemsprecher (de_DE, de_AT oder de_CH) verfügbar.")

            os.makedirs(os.path.join(CACHE_ORDNER, "tts"), exist_ok=True)
            schluessel = hashlib.sha256(
                rohtext + b"\0" + self.stimme.encode("utf-8")
            ).hexdigest()
            cache_basis = os.path.join(CACHE_ORDNER, "tts", schluessel)
            text_cache = cache_basis + ".txt"
            audio_cache = cache_basis + ".aiff"
            audio_valid = False
            if os.path.isfile(audio_cache) and os.path.getsize(audio_cache) >= 12:
                with open(audio_cache, "rb") as f:
                    header = f.read(12)
                audio_valid = header[:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC")
            if not audio_valid:
                with open(text_cache, "w", encoding="utf-8") as f:
                    f.write(text)
                subprocess.run(
                    ["/usr/bin/say", "-v", self.stimme, "-f", text_cache, "-o", audio_cache],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                with open(audio_cache, "rb") as f:
                    header = f.read(12)
                if header[:4] != b"FORM" or header[8:12] not in (b"AIFF", b"AIFC"):
                    raise RuntimeError("Der macOS-Sprachdienst hat keine gültige AIFF-Datei erstellt.")
            self.fertig.emit(audio_cache, "")
        except Exception as e:
            self.fertig.emit("", f"Textdatei kann nicht vorgelesen werden: {e}")


class UebersetzungThread(QThread):
    fertig = pyqtSignal(str, str, str, str)
    _request_lock = threading.Lock()
    _naechster_request = 0.0
    _sperre_bis = 0.0

    def __init__(self, text, zielsprache, parent=None):
        super().__init__(parent)
        self.text = text
        self.zielsprache = zielsprache

    @classmethod
    def warte_auf_request(cls):
        with cls._request_lock:
            jetzt = time.monotonic()
            if cls._sperre_bis > jetzt:
                raise RuntimeError(
                    f"RATE_LIMITED:{max(1, int(cls._sperre_bis - jetzt + 0.99))}"
                )
            pause = cls._naechster_request - jetzt
            if pause > 0:
                time.sleep(pause)
            jetzt = time.monotonic()
            if cls._sperre_bis > jetzt:
                raise RuntimeError(
                    f"RATE_LIMITED:{max(1, int(cls._sperre_bis - jetzt + 0.99))}"
                )
            cls._naechster_request = jetzt + 1.5

    @classmethod
    def setze_rate_limit(cls, retry_after):
        with cls._request_lock:
            cls._sperre_bis = max(
                cls._sperre_bis,
                time.monotonic() + max(1, retry_after),
            )

    def run(self):
        try:
            if len(self.text.encode("utf-8")) > 500:
                raise ValueError(
                    "Der Satz ist zu lang für den kostenlosen Übersetzungsdienst."
                )
            else:
                self.warte_auf_request()
                query = urllib.parse.urlencode({
                    "q": self.text,
                    "langpair": f"de|{self.zielsprache}",
                })
                request = urllib.request.Request(
                    f"https://api.mymemory.translated.net/get?{query}",
                    headers={"User-Agent": "Sprachtrainer/3"},
                )
                try:
                    with urllib.request.urlopen(request, timeout=15) as response:
                        daten = json.load(response)
                except urllib.error.HTTPError as fehler:
                    if fehler.code == 429:
                        retry_header = fehler.headers.get("Retry-After", "60")
                        try:
                            retry_after = max(1, int(retry_header))
                        except (TypeError, ValueError):
                            try:
                                retry_date = parsedate_to_datetime(retry_header)
                                if retry_date.tzinfo is None:
                                    retry_date = retry_date.replace(tzinfo=timezone.utc)
                                retry_after = max(
                                    1,
                                    int(
                                        (retry_date - datetime.now(timezone.utc))
                                        .total_seconds() + 0.99
                                    ),
                                )
                            except (TypeError, ValueError, OverflowError):
                                retry_after = 60
                        self.setze_rate_limit(retry_after)
                        raise RuntimeError(
                            f"RATE_LIMITED:{max(1, retry_after)}"
                        ) from fehler
                    raise
                if str(daten.get("responseStatus")) != "200":
                    if str(daten.get("responseStatus")) == "429":
                        self.setze_rate_limit(60)
                        raise RuntimeError("RATE_LIMITED:60")
                    raise RuntimeError(
                        daten.get("responseDetails")
                        or "Übersetzungsdienst hat den Satz abgelehnt."
                    )
                uebersetzung = daten.get("responseData", {}).get(
                    "translatedText", ""
                )
                if not uebersetzung:
                    raise RuntimeError(
                        "Übersetzungsdienst hat keinen Text zurückgegeben."
                    )
                if uebersetzung.upper().startswith("MYMEMORY WARNING"):
                    raise RuntimeError(
                        "Tageslimit des Übersetzungsdienstes erreicht."
                    )
                self.fertig.emit(
                    self.text, self.zielsprache, unescape(uebersetzung), ""
                )
                return
        except Exception as memory_error:
            if not os.environ.get("GEMINI_API_KEY", "").strip():
                self.fertig.emit(self.text, self.zielsprache, "", str(memory_error))
                return
            sprachname = {
                "ru": "Russian",
                "uk": "Ukrainian",
                "en": "English",
                "fr": "French",
                "es": "Spanish",
            }.get(self.zielsprache, self.zielsprache)
            prompt = (
                f"Translate the following German sentence into {sprachname}. "
                "Preserve its meaning and punctuation. Return only the translation.\n\n"
                f"German sentence: {self.text}"
            )
            try:
                daten = gemini_interaction(prompt, "gemini-3.8-flash", timeout=30)
                uebersetzung = gemini_output_text(daten)
                self.fertig.emit(self.text, self.zielsprache, uebersetzung, "")
            except Exception as gemini_error:
                self.fertig.emit(
                    self.text,
                    self.zielsprache,
                    "",
                    f"{memory_error}; Gemini fallback failed: {gemini_error}",
                )


class BildLadeThread(QThread):
    bild_abgeschlossen = pyqtSignal(str, bool, str, object)

    def __init__(self, bilder, parent=None):
        super().__init__(parent)
        self.bilder = bilder

    def run(self):
        for wort_lower, wort, suchbegriff, _ in self.bilder:
            if self.isInterruptionRequested():
                self.bild_abgeschlossen.emit(wort_lower, False, "", None)
                continue
            kandidatenpfade = openverse_bild_pfade(wort_lower)
            if any(os.path.exists(kandidatenpfad) for kandidatenpfad in kandidatenpfade):
                self.bild_abgeschlossen.emit(wort_lower, True, "", None)
                continue

            geladen = False
            fehler = ""
            bild_details = None
            try:
                header = {"User-Agent": "Sprachtrainer/3.0 (local vocabulary learning app)"}
                wort_muster = bild_wort_muster(wort)
                kontextwoerter = [
                    token.lower() for token in suchbegriff.split()
                    if token.lower() != wort.lower()
                    and token.lower() not in ARTIKEL_WOERTER
                    and token.lower() not in SUCH_STOP_WOERTER
                ]
                gemini_query = ""
                gemini_zielwoerter = []
                gemini_kontextwoerter = []
                suchdaten_fehler = ""
                if os.environ.get("GEMINI_API_KEY", "").strip():
                    try:
                        (
                            gemini_query,
                            gemini_zielwoerter,
                            gemini_kontextwoerter,
                        ) = gemini_bild_suchdaten(wort, suchbegriff)
                    except Exception as error:
                        suchdaten_fehler = str(error)
                suchkontextwoerter = tuple(dict.fromkeys(
                    token.casefold()
                    for token in (*kontextwoerter, *gemini_kontextwoerter)
                ))
                alternativen = BILD_SUCH_ALTERNATIVEN.get(wort.lower(), ())
                alternative_woerter = [
                    re.findall(r"[\wäöüß-]+", alternative.casefold())
                    for alternative in alternativen
                ]
                ist_verb = wort.lower().endswith(("en", "ern", "eln"))

                def trefferzahl(woerter, metadaten):
                    return sum(
                        bool(bild_wort_muster(token).search(metadaten))
                        for token in woerter
                    )

                def bild_metadaten(bild):
                    titel = bild.get("title") or ""
                    tags = " ".join(
                        tag.get("name", "") for tag in bild.get("tags", [])
                        if isinstance(tag, dict)
                    )
                    beschreibung = bild.get("description") or ""
                    return titel, tags, beschreibung, f"{titel} {tags} {beschreibung}"

                ergebnisse_gesamt = []
                suchanfragen = [suchbegriff, wort]
                if gemini_query:
                    suchanfragen.insert(0, gemini_query)
                suchanfragen = list(dict.fromkeys(
                    query for query in suchanfragen if query.strip()
                ))

                def suche(suchanfrage, ist_alternative=False):
                    parameter = urllib.parse.urlencode({
                        "q": suchanfrage,
                        "page_size": 20,
                    })
                    url = f"https://api.openverse.org/v1/images/?{parameter}"
                    anfrage = urllib.request.Request(url, headers=header)
                    with urllib.request.urlopen(anfrage, timeout=15) as antwort:
                        ergebnis = json.load(antwort)

                    ergebnisse_gesamt.extend(
                        (bild, rang, ist_alternative)
                        for rang, bild in enumerate(ergebnis.get("results", []))
                    )

                for suchanfrage in suchanfragen:
                    suche(suchanfrage)

                hat_passenden_zieltreffer = any(
                    (
                        wort_muster.search(bild_metadaten(bild)[3])
                        or trefferzahl(
                            gemini_zielwoerter, bild_metadaten(bild)[3]
                        )
                    )
                    and trefferzahl(
                        [*kontextwoerter, *gemini_kontextwoerter],
                        bild_metadaten(bild)[3],
                    )
                    for bild, _, _ in ergebnisse_gesamt
                )
                if alternativen and not hat_passenden_zieltreffer:
                    for alternative in alternativen:
                        suche(alternative, ist_alternative=True)

                passende = []
                for bild, rang, ausweichsuche in ergebnisse_gesamt:
                    title, tags, beschreibung, metadaten = bild_metadaten(bild)
                    kontext_treffer = trefferzahl(
                        suchkontextwoerter, f"{title} {tags}"
                    )
                    beschreibungs_treffer = trefferzahl(
                        suchkontextwoerter, beschreibung
                    )
                    wort_titel = bool(wort_muster.search(title))
                    wort_tags = bool(wort_muster.search(tags))
                    wort_beschreibung = bool(wort_muster.search(beschreibung))
                    gemini_ziel_treffer = trefferzahl(
                        gemini_zielwoerter, metadaten
                    )
                    alternative_treffer = max(
                        (trefferzahl(woerter, metadaten)
                         for woerter in alternative_woerter),
                        default=0,
                    ) if ausweichsuche else 0
                    if not (wort_titel or wort_tags or wort_beschreibung
                            or gemini_ziel_treffer or alternative_treffer):
                        continue

                    verb_position = 0.0
                    if ist_verb:
                        titelwoerter = re.findall(r"[\wäöüß-]+", title.casefold())
                        fundstellen = [
                            i for i, titelwort in enumerate(titelwoerter)
                            if wort_muster.fullmatch(titelwort)
                        ]
                        if fundstellen:
                            verb_position = fundstellen[-1] / max(1, len(titelwoerter) - 1)
                    score = (
                        -kontext_treffer,
                        -beschreibungs_treffer,
                        -gemini_ziel_treffer,
                        -alternative_treffer,
                        -int(wort_titel),
                        -int(wort_tags),
                        -int(wort_beschreibung),
                        -verb_position,
                        rang,
                    )
                    passende.append((
                        score, bild, title, tags, beschreibung,
                        wort_titel, wort_tags, wort_beschreibung,
                        gemini_ziel_treffer, alternative_treffer,
                    ))

                passende.sort(key=lambda eintrag: eintrag[0])
                eindeutige_passende = []
                gesehen = set()
                for eintrag in passende:
                    bildinfo = eintrag[1]
                    bild_url = bildinfo.get("url") or bildinfo.get("thumbnail")
                    if bild_url in gesehen:
                        continue
                    gesehen.add(bild_url)
                    eindeutige_passende.append(eintrag)
                passende = eindeutige_passende

                if not passende:
                    fehler = f"Kein passendes Bild gefunden: {wort}"

                bild_details = []
                for nummer, eintrag in enumerate(passende[:3]):
                    (
                        _, bildinfo, title, tags, beschreibung,
                        wort_titel, wort_tags, wort_beschreibung,
                        _, alternative_treffer,
                    ) = eintrag
                    zielpfad = kandidatenpfade[nummer]
                    bild_urls = dict.fromkeys(
                        url for url in (bildinfo.get("thumbnail"), bildinfo.get("url"))
                        if url
                    )
                    for bild_url in bild_urls:
                        try:
                            bild_anfrage = urllib.request.Request(bild_url, headers=header)
                            with urllib.request.urlopen(bild_anfrage, timeout=15) as antwort:
                                bild = QImage.fromData(antwort.read())
                            if not bild.isNull() and bild.save(
                                zielpfad, "JPEG", quality=90
                            ):
                                metadaten_text = f"{title} {tags} {beschreibung}"
                                einzelheiten = {
                                    "query": suchbegriff,
                                    "translated_query": gemini_query,
                                    "translated_target_terms": gemini_zielwoerter,
                                    "search_refinement_error": suchdaten_fehler,
                                    "title": title,
                                    "description": re.sub(
                                        r"\s+",
                                        " ",
                                        re.sub(r"<[^>]+>", " ", unescape(beschreibung)),
                                    )[:400],
                                    "tags": [
                                        tag.get("name", "")
                                        for tag in bildinfo.get("tags", [])
                                        if isinstance(tag, dict) and tag.get("name")
                                    ][:12],
                                    "context_matches": [
                                        token for token in (
                                            *suchbegriff.split(),
                                            *gemini_kontextwoerter,
                                        )
                                        if (
                                            token.casefold() in suchkontextwoerter
                                            and bild_wort_muster(token).search(
                                                metadaten_text
                                            )
                                        )
                                    ],
                                    "target_match": (
                                        "gemini_terms" if gemini_ziel_treffer
                                        and not (wort_titel or wort_tags or wort_beschreibung)
                                        else "alternative" if alternative_treffer
                                        and not (wort_titel or wort_tags or wort_beschreibung)
                                        else "title_and_tags" if wort_titel and wort_tags
                                        else "title" if wort_titel
                                        else "tags" if wort_tags
                                        else "description" if wort_beschreibung
                                        else "gemini_terms"
                                    ),
                                    "source": (
                                        bildinfo.get("foreign_landing_url")
                                        or bildinfo.get("url")
                                        or ""
                                    ),
                                }
                                try:
                                    with open(
                                        bild_info_pfad(zielpfad), "w", encoding="utf-8"
                                    ) as f:
                                        json.dump(einzelheiten, f, ensure_ascii=False)
                                except OSError as error:
                                    fehler = f"IMAGE_INFO_SAVE_ERROR:{error}"
                                bild_details.append({
                                    "path": zielpfad,
                                    "details": einzelheiten,
                                })
                                geladen = True
                                break
                        except Exception:
                            continue

                if not geladen and not fehler:
                    fehler = f"Kein passendes Bild gefunden: {wort}"
            except Exception as e:
                fehler = f"Bild für „{wort}“ nicht geladen: {e}"

            self.bild_abgeschlossen.emit(wort_lower, geladen, fehler, bild_details)


class GeminiBildThread(QThread):
    fertig = pyqtSignal(str, bool, str)

    def __init__(self, wort_lower, wort, kontext, pfad, parent=None):
        super().__init__(parent)
        self.wort_lower = wort_lower
        self.wort = wort
        self.kontext = kontext
        self.pfad = pfad

    def run(self):
        try:
            prompt = (
                "Create one clear, simple educational illustration for a German "
                "vocabulary learner. Show the concrete meaning of the German "
                f"word “{self.wort}” in this sentence context: “{self.kontext}”. "
                "Make the target concept visually obvious, use one central subject "
                "and a clean background, square composition, no captions, no letters, "
                "no labels, and no collage."
            )
            ergebnis = gemini_interaction(
                prompt, "gemini-3.1-flash-lite-image", timeout=60
            )
            bilddaten = ergebnis.get("output_image")
            if isinstance(bilddaten, dict):
                kodiert = bilddaten.get("data")
            else:
                kodiert = None
            if not kodiert:
                for ausgabe in ergebnis.get("output", []):
                    if isinstance(ausgabe, dict) and ausgabe.get("type") == "image":
                        kodiert = ausgabe.get("data")
                        if kodiert:
                            break
            if not kodiert:
                raise RuntimeError("Gemini returned no image data.")
            bild = QImage.fromData(base64.b64decode(kodiert, validate=True))
            if bild.isNull():
                raise RuntimeError("Gemini returned an invalid image.")
            os.makedirs(os.path.dirname(self.pfad), exist_ok=True)
            if not bild.save(self.pfad, "PNG"):
                raise OSError(f"Could not save generated image to {self.pfad}.")
            self.fertig.emit(self.wort_lower, True, "")
        except Exception as error:
            self.fertig.emit(self.wort_lower, False, str(error))


# --------------------------------------------------------------------------- #
#  Bild-Karte mit abgerundeten Ecken (klickbar, mit Beschriftung)
# --------------------------------------------------------------------------- #
class BildKarte(QWidget):
    geklickt = pyqtSignal(str)

    def __init__(
        self, wort=None, nummer=None, pixmap=None, text="", interaktiv=True,
        tooltip="",
    ):
        super().__init__()
        self.wort = wort
        self.nummer = nummer
        self.pixmap = pixmap
        self.text = text
        self.interaktiv = interaktiv
        self.setFixedSize(220, 200)
        if wort and interaktiv:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def mousePressEvent(self, event):
        if self.interaktiv and self.wort and event.button() == Qt.MouseButton.LeftButton:
            self.geklickt.emit(self.wort)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pfad = QPainterPath()
        pfad.addRoundedRect(rect, 16, 16)
        p.fillPath(pfad, QColor("#1b1e2b"))
        p.setClipPath(pfad)

        if self.pixmap and not self.pixmap.isNull():
            ziel = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - ziel.width()) / 2
            y = (self.height() - ziel.height()) / 2
            p.drawPixmap(QRectF(x, y, ziel.width(), ziel.height()),
                         self.pixmap, QRectF(self.pixmap.rect()))
        else:
            p.setPen(QColor("#5b6079"))
            font = QFont(self.font())
            font.setPointSize(11)
            p.setFont(font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.text or "Kein Bild")

        if self.wort:
            leiste = QRectF(rect.left(), rect.bottom() - 36, rect.width(), 36)
            p.fillRect(leiste, QColor(0, 0, 0, 170))
            p.setPen(QColor("#ffffff"))
            schrift = QFont(self.font())
            schrift.setPointSize(12)
            schrift.setBold(True)
            p.setFont(schrift)
            beschriftung = f"{self.nummer} · {self.wort}" if self.nummer else self.wort
            beschriftung = p.fontMetrics().elidedText(beschriftung, Qt.TextElideMode.ElideRight,
                                                      int(leiste.width() - 16))
            p.drawText(leiste, Qt.AlignmentFlag.AlignCenter, beschriftung)
            if self.toolTip():
                info_rect = QRectF(rect.right() - 30, rect.top() + 8, 22, 22)
                p.setBrush(QColor(0, 0, 0, 190))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(info_rect)
                p.setPen(QColor("#ffffff"))
                info_font = QFont(self.font())
                info_font.setBold(True)
                info_font.setPointSize(12)
                p.setFont(info_font)
                p.drawText(info_rect, Qt.AlignmentFlag.AlignCenter, "i")


class BildVergleichKarte(QWidget):
    bewertet = pyqtSignal(str, int)
    erneut_anfordern = pyqtSignal()

    def __init__(
        self, quelle, titel, wort, nummer, pixmap, platzhalter, interaktiv,
        tooltip, rating, positive, gesamt, rate_ja, rate_nein, retry_text="",
    ):
        super().__init__()
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        label = QLabel(titel)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self.bildkarte = BildKarte(
            wort=wort,
            nummer=nummer,
            pixmap=pixmap,
            text=platzhalter,
            interaktiv=interaktiv,
            tooltip=tooltip,
        )
        layout.addWidget(self.bildkarte)

        self.bewertungswidget = QWidget()
        bewertungszeile = QHBoxLayout(self.bewertungswidget)
        bewertungszeile.setContentsMargins(0, 0, 0, 0)
        self.ja_button = QPushButton("👍")
        self.nein_button = QPushButton("👎")
        self.ja_button.setToolTip(rate_ja)
        self.nein_button.setToolTip(rate_nein)
        self.ja_button.setCheckable(True)
        self.nein_button.setCheckable(True)
        self.ja_button.setChecked(rating == 1)
        self.nein_button.setChecked(rating == -1)
        self.ja_button.clicked.connect(lambda: self.bewertet.emit(quelle, 1))
        self.nein_button.clicked.connect(lambda: self.bewertet.emit(quelle, -1))
        bewertungszeile.addStretch(1)
        bewertungszeile.addWidget(self.ja_button)
        bewertungszeile.addWidget(self.nein_button)
        self.statistik_label = QLabel(f"{positive}/{gesamt}")
        self.statistik_label.setToolTip(rate_ja)
        bewertungszeile.addWidget(self.statistik_label)
        bewertungszeile.addStretch(1)
        self.bewertungswidget.setVisible(bool(pixmap and not pixmap.isNull()))
        layout.addWidget(self.bewertungswidget)

        self.retry_button = QPushButton(retry_text)
        self.retry_button.setVisible(bool(retry_text))
        self.retry_button.clicked.connect(self.erneut_anfordern.emit)
        layout.addWidget(self.retry_button)
        self.setMinimumHeight(self.sizeHint().height())


# --------------------------------------------------------------------------- #
#  Stylesheet
# --------------------------------------------------------------------------- #
STYLE = """
* { color: #e8eaf2; }
QMainWindow, QWidget#root { background: #12141c; }
QLabel { background: transparent; }
QToolTip {
    color: #111111;
    background-color: #f5f5f5;
    border: 1px solid #9a9a9a;
    padding: 6px;
}
QLabel#status { color: #9aa0bd; font-size: 13px; }
QTextBrowser#satz { background: transparent; border: none; font-size: 28px; font-weight: 600; color: #ffffff; padding: 15px; }
QLabel#uebersetzung { color: #c9ccdd; font-size: 17px; padding: 0 15px 8px; }
QLabel#zeit, QLabel#hinweis, QLabel#stat { color: #7d829e; font-size: 12px; }
QLabel#titel { font-size: 15px; font-weight: 600; }
QFrame#sidebar { background: #181b26; border-radius: 18px; }

QPushButton {
    background: #232738; border: none; border-radius: 12px;
    padding: 11px 20px; font-size: 14px; font-weight: 600;
}
QPushButton:hover { background: #2c3148; }
QPushButton:pressed { background: #1d2031; }
QPushButton:disabled { color: #50546b; background: #1a1d2a; }
QPushButton#primary { background: #7c5cff; }
QPushButton#primary:hover { background: #8f73ff; }
QPushButton#primary:disabled { background: #2d2750; color: #6a6490; }
QPushButton#gut { background: #1f7a54; }
QPushButton#gut:hover { background: #26946a; }
QPushButton#gut:disabled { background: #1a2a25; color: #4b6a5d; }

QSlider::groove:horizontal { height: 6px; background: #2a2e40; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #7c5cff; border-radius: 3px; }
QSlider::handle:horizontal { background: #ffffff; width: 14px; margin: -5px 0; border-radius: 7px; }

QProgressBar {
    background: #232738; border: none; border-radius: 6px;
    height: 10px; text-align: center; font-size: 10px; color: transparent;
}
QProgressBar::chunk { background: #7c5cff; border-radius: 6px; }

QComboBox {
    background: #232738; border: none; border-radius: 10px; padding: 7px 12px;
}
QComboBox QAbstractItemView { background: #232738; selection-background-color: #7c5cff; border: none; }
QComboBox::drop-down { border: none; width: 22px; }

QCheckBox { spacing: 8px; color: #c9ccdd; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; background: #232738; }
QCheckBox::indicator:checked { background: #7c5cff; }

QListWidget { background: transparent; border: none; outline: none; font-size: 14px; }
QListWidget::item { padding: 9px 12px; border-radius: 9px; }
QListWidget::item:hover { background: #232738; }
QListWidget::item:selected { background: #7c5cff; color: #ffffff; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #2f3450; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# --------------------------------------------------------------------------- #
#  Hauptfenster
# --------------------------------------------------------------------------- #
class SprachLernPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1180, 780)

        self.bekannte_woerter = set()
        self.rueckgaengig_stack = []  # Liste von Gruppen (Listen von Wörtern)
        self.lade_woerterbuch()

        self.segmente = []
        self.starts = []
        self.aktueller_index = -1
        self.gerenderter_index = -2
        self.zeitwort_key = None
        self.pause_erledigt_index = -1
        self.auto_pausiert = False
        self.bilder_key = None
        self.fokus_index = 0  # Position des aktuellen Wortes in aktuelle_unbekannte
        self.ausgewaehltes_bekanntes_wort = None
        self.mp3_pfad = None
        self.quell_pfad = None
        self.analyse_thread = None
        self.text_audio_thread = None
        self.aktive_threads = set()
        self.aktuelle_textstimme = None
        self.tts_wechsel_aktiv = False
        self.satz_index_nach_analyse = None
        self.einstellungen = QSettings()
        self.position_beim_wiederherstellen = 0
        self.automatisch_starten = False
        self.navigation_ziel_index = None
        self.audio_bereit = False
        self.aktuell_modell_name = "base"
        self.bild_queue = []
        self.bilder_in_arbeit = set()
        self.bild_details = {}
        self.bilder_fehlgeschlagen = set()
        self.bild_thread = None
        self.gemini_bilder_in_arbeit = set()
        self.gemini_bilder_fehlgeschlagen = {}
        self.neue_woerter_anzahl = 0
        self.uebersetzungen = {}
        self.uebersetzung_fehler = {}
        self.uebersetzung_threads = {}
        self.aktuelle_uebersetzung = None
        self.status_key = "initial_status"
        self.status_args = {}
        self.placeholder_key = None
        self.placeholder_args = {}

        # unbekannte Wörter des aktuell angezeigten Satzes (Reihenfolge wie im Satz)
        self.aktuelle_unbekannte = []

        self.init_ui()
        self.aktualisiere_oberflaeche()
        self.aktualisiere_dateiliste()
        self.init_audio()
        self.init_shortcuts()
        self.aktualisiere_statistik()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.aktualisiere_anzeige)
        self.timer.start(50)

        self.speicher_timer = QTimer(self)
        self.speicher_timer.setInterval(2000)
        self.speicher_timer.timeout.connect(self.speichere_wiedergabestand)
        self.speicher_timer.start()
        QTimer.singleShot(0, self.wiederherstelle_wiedergabe)

    # ------------------------------ UI -------------------------------------- #
    def init_ui(self):
        root = QWidget()
        root.setObjectName("root")
        haupt = QHBoxLayout(root)
        haupt.setContentsMargins(24, 22, 24, 22)
        haupt.setSpacing(22)

        # ---- linke Spalte ----
        links = QVBoxLayout()
        links.setSpacing(12)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        links.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.hide()
        links.addWidget(self.progress_bar)

        # Bereich für Bilder (dynamisch)
        self.bilder_scroll = QScrollArea()
        self.bilder_scroll.setWidgetResizable(True)
        self.bilder_scroll.setFixedHeight(300)
        self.bilder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.bilder_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.bilder_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.bilder_container = QWidget()
        self.bilder_layout = QHBoxLayout(self.bilder_container)
        self.bilder_layout.setContentsMargins(0, 0, 0, 0)
        self.bilder_layout.setSpacing(12)
        self.bilder_scroll.setWidget(self.bilder_container)
        links.addWidget(self.bilder_scroll)
        # Satz-Anzeige mit klickbaren Wörtern
        self.satz_label = QTextBrowser()
        self.satz_label.setObjectName("satz")
        self.satz_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.satz_label.setMinimumHeight(120)
        self.satz_label.setMaximumHeight(210)
        self.satz_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.satz_label.setOpenLinks(False)
        self.satz_label.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.satz_label.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.satz_label.anchorClicked.connect(
            lambda url: self.wort_angeklickt(url.toString())
        )
        links.addWidget(self.satz_label)

        uebersetzung_zeile = QHBoxLayout()
        self.lbl_uebersetzung = QLabel()
        uebersetzung_zeile.addWidget(self.lbl_uebersetzung)
        self.combo_uebersetzung = QComboBox()
        for name, code in (
            ("Русский", "ru"),
            ("Українська", "uk"),
            ("English", "en"),
            ("Français", "fr"),
            ("Español", "es"),
        ):
            self.combo_uebersetzung.addItem(name, code)
        gespeicherte_sprache = self.einstellungen.value(
            "translation/language", "ru", type=str
        )
        index_sprache = self.combo_uebersetzung.findData(gespeicherte_sprache)
        if index_sprache >= 0:
            self.combo_uebersetzung.setCurrentIndex(index_sprache)
        self.combo_uebersetzung.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.combo_uebersetzung.currentIndexChanged.connect(
            lambda _: self.uebersetzungssprache_geaendert()
        )
        uebersetzung_zeile.addWidget(self.combo_uebersetzung)
        self.btn_uebersetzung_retry = QPushButton("↻")
        self.btn_uebersetzung_retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_uebersetzung_retry.clicked.connect(
            self.uebersetzung_man_wiederholen
        )
        self.btn_uebersetzung_retry.hide()
        uebersetzung_zeile.addWidget(self.btn_uebersetzung_retry)
        uebersetzung_zeile.addStretch(1)
        links.addLayout(uebersetzung_zeile)

        self.uebersetzung_label = QLabel("")
        self.uebersetzung_label.setObjectName("uebersetzung")
        self.uebersetzung_label.setWordWrap(True)
        self.uebersetzung_label.setTextFormat(Qt.TextFormat.RichText)
        self.uebersetzung_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.uebersetzung_label.setToolTip(
            self.ui_text("translation_word_match_tooltip")
        )
        self.uebersetzung_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.uebersetzung_label.hide()
        links.addWidget(self.uebersetzung_label)

        # Zeitleiste
        zeile_pos = QHBoxLayout()
        self.slider_pos = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider_pos.setRange(0, 0)
        self.slider_pos.sliderMoved.connect(lambda v: self.player.setPosition(v))
        zeile_pos.addWidget(self.slider_pos, 1)
        self.zeit_label = QLabel("00:00 / 00:00")
        self.zeit_label.setObjectName("zeit")
        zeile_pos.addWidget(self.zeit_label)
        links.addLayout(zeile_pos)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.btn_laden = QPushButton()
        self.btn_laden.clicked.connect(self.lade_datei)
        self.btn_zurueck = QPushButton("⏮")
        self.btn_zurueck.clicked.connect(self.vorheriger_satz)
        self.btn_play = QPushButton()
        self.btn_play.setObjectName("primary")
        self.btn_play.clicked.connect(self.toggle_wiedergabe)
        self.btn_weiter = QPushButton("⏭")
        self.btn_weiter.clicked.connect(self.naechster_satz)
        self.btn_wiederholen = QPushButton()
        self.btn_wiederholen.clicked.connect(self.wiederhole_satz)
        self.btn_gemerkt = QPushButton()
        self.btn_gemerkt.setObjectName("gut")
        self.btn_gemerkt.clicked.connect(self.merke_fokus_wort)
        self.btn_skip = QPushButton()
        self.btn_skip.clicked.connect(self.weiter_zum_naechsten_wort)

        alle = (self.btn_laden, self.btn_zurueck, self.btn_play, self.btn_weiter,
                self.btn_wiederholen, self.btn_gemerkt, self.btn_skip)
        for b in alle:
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btns.addWidget(b)
        for b in alle[1:]:
            b.setEnabled(False)
        btns.insertStretch(1, 1)
        links.addLayout(btns)

        # Optionen
        optionen = QHBoxLayout()
        optionen.setSpacing(14)

        self.combo_modell = QComboBox()
        self.combo_modell.addItems(["tiny", "base", "small", "medium"])
        self.combo_modell.setCurrentText(
            self.einstellungen.value("whisper/model", "base", type=str)
            if self.einstellungen.value("whisper/model", "base", type=str)
            in ("tiny", "base", "small", "medium") else "base"
        )
        self.combo_modell.currentTextChanged.connect(
            lambda name: self.einstellungen.setValue("whisper/model", name)
        )
        self.lbl_modell = QLabel()
        optionen.addWidget(self.lbl_modell)
        optionen.addWidget(self.combo_modell)

        self.combo_tempo = QComboBox()
        for t in ("0.5", "0.75", "1.0", "1.25", "1.5"):
            self.combo_tempo.addItem(f"{t}×", float(t))
        self.combo_tempo.setCurrentIndex(2)
        self.combo_tempo.currentIndexChanged.connect(
            lambda _: self.player.setPlaybackRate(self.combo_tempo.currentData()))
        self.lbl_tempo = QLabel()
        optionen.addWidget(self.lbl_tempo)
        optionen.addWidget(self.combo_tempo)

        self.stimmen_widget = QWidget()
        stimmen_zeile = QHBoxLayout(self.stimmen_widget)
        stimmen_zeile.setContentsMargins(0, 0, 0, 0)
        self.lbl_stimme = QLabel()
        stimmen_zeile.addWidget(self.lbl_stimme)
        self.combo_stimme = QComboBox()
        try:
            stimmen = deutsche_systemstimmen()
        except (OSError, subprocess.CalledProcessError) as fehler:
            stimmen = []
            self.set_status("system_voice_error", error=fehler)
        for name, locale in stimmen:
            self.combo_stimme.addItem(f"{name} ({locale})", name)
        gespeicherte_stimme = self.einstellungen.value("tts/voice", "", type=str)
        gespeicherte_index = self.combo_stimme.findData(gespeicherte_stimme)
        if gespeicherte_index >= 0:
            self.combo_stimme.setCurrentIndex(gespeicherte_index)
        elif self.combo_stimme.count():
            self.einstellungen.setValue("tts/voice", self.combo_stimme.currentData())
        else:
            self.combo_stimme.addItem("", "")
            self.combo_stimme.setEnabled(False)
        self.combo_stimme.currentIndexChanged.connect(self.textstimme_geaendert)
        stimmen_zeile.addWidget(self.combo_stimme, 1)
        self.stimmen_widget.hide()
        links.addWidget(self.stimmen_widget)

        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(80)
        self.slider_vol.setFixedWidth(100)
        self.slider_vol.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100))
        optionen.addWidget(QLabel("🔊"))
        optionen.addWidget(self.slider_vol)

        self.check_autopause = QCheckBox()
        self.check_autopause.setChecked(True)
        optionen.addWidget(self.check_autopause)
        optionen.addStretch(1)

        for w in (self.combo_modell, self.combo_tempo, self.combo_stimme,
                  self.slider_vol, self.check_autopause):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        links.addLayout(optionen)

        self.hinweis = QLabel()
        self.hinweis.setObjectName("hinweis")
        self.hinweis.setWordWrap(True)
        links.addWidget(self.hinweis)

        haupt.addLayout(links, 1)

        # ---- rechte Seitenleiste ----
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(290)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(16, 16, 16, 16)
        self.stat_label = QLabel("")
        self.stat_label.setObjectName("stat")
        self.stat_label.setWordWrap(True)
        self.datei_titel = QLabel()
        self.datei_titel.setObjectName("titel")
        sv.addWidget(self.datei_titel)
        self.datei_liste = QListWidget()
        self.datei_liste.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.datei_liste.setFixedHeight(170)
        self.datei_liste.itemClicked.connect(self.waehle_analysierte_datei)
        sv.addWidget(self.datei_liste)

        self.wort_titel = QLabel()
        self.wort_titel.setObjectName("titel")
        sv.addWidget(self.wort_titel)

        self.liste = QListWidget()
        self.liste.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.liste.itemClicked.connect(self.springe_zu_listenwort)
        sv.addWidget(self.liste, 1)

        sv.addWidget(self.stat_label)

        self.btn_undo = QPushButton()
        self.btn_undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_undo.clicked.connect(self.rueckgaengig)
        self.btn_undo.setEnabled(False)
        sv.addWidget(self.btn_undo)

        haupt.addWidget(sidebar)
        self.setCentralWidget(root)

    def ui_text(self, key, **werte):
        sprache = self.combo_uebersetzung.currentData()
        texte = UI_TEXTE[key]
        return texte.get(sprache, texte["en"]).format(**werte)

    def set_status(self, key, **werte):
        self.status_key = key
        self.status_args = werte
        self.status_label.setText(self.ui_text(key, **werte))

    def starte_thread(self, thread):
        self.aktive_threads.add(thread)
        thread.finished.connect(
            lambda laufender_thread=thread:
            self.aktive_threads.discard(laufender_thread)
        )
        thread.start()

    def thread_beendet(self, thread):
        if self.analyse_thread is thread:
            self.analyse_thread = None
        if self.text_audio_thread is thread:
            self.text_audio_thread = None
        thread.deleteLater()

    def uebersetzung_thread_beendet(self, key, thread):
        if self.uebersetzung_threads.get(key) is thread:
            self.uebersetzung_threads.pop(key)
        thread.deleteLater()

    def analyse_status_geaendert(self, text):
        if text.startswith("Transkript aus dem Cache"):
            self.set_status("cached_transcript")
        elif text.startswith("Analyse abgeschlossen"):
            self.set_status("analysis_ready")
        elif text.startswith("Whisper-Modell wird geladen"):
            modell = text.partition("(")[2].rstrip(")...")
            self.set_status("loading_model", model=modell)
        elif text.startswith("Audio wird nach Sätzen analysiert"):
            self.set_status("analyzing_audio")
        elif text.startswith("Fehler bei der Analyse:"):
            self.set_status("analysis_error", error=text.partition(":")[2].strip())
        else:
            self.status_key = None
            self.status_args = {}
            self.status_label.setText(text)

    def aktualisiere_oberflaeche(self):
        self.setWindowTitle(self.ui_text("title"))
        if self.status_key:
            self.status_label.setText(self.ui_text(self.status_key, **self.status_args))
        self.lbl_uebersetzung.setText(self.ui_text("translation"))
        self.combo_uebersetzung.setToolTip(self.ui_text("translation_tooltip"))
        self.btn_uebersetzung_retry.setToolTip(
            self.ui_text("translation_retry_tooltip")
        )
        self.uebersetzung_label.setToolTip(
            self.ui_text("translation_word_match_tooltip")
        )
        self.btn_laden.setText(self.ui_text("load_file"))
        self.btn_zurueck.setToolTip(self.ui_text("previous_sentence"))
        self.btn_weiter.setToolTip(self.ui_text("next_sentence"))
        self.btn_wiederholen.setText(self.ui_text("repeat_sentence"))
        self.btn_wiederholen.setToolTip(self.ui_text("repeat_tooltip"))
        self.btn_gemerkt.setText(self.ui_text("remember"))
        self.btn_gemerkt.setToolTip(self.ui_text("remember_tooltip"))
        self.btn_skip.setText(self.ui_text("skip"))
        self.btn_skip.setToolTip(self.ui_text("skip_tooltip"))
        self.btn_play.setText(
            self.ui_text("pause") if self.audio_bereit
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            else self.ui_text("play")
        )
        self.lbl_modell.setText(self.ui_text("model"))
        self.combo_modell.setToolTip(self.ui_text("model_tooltip"))
        self.lbl_tempo.setText(self.ui_text("speed"))
        self.lbl_stimme.setText(self.ui_text("text_voice"))
        kein_stimme_index = self.combo_stimme.findData("")
        if kein_stimme_index >= 0:
            self.combo_stimme.setItemText(kein_stimme_index, self.ui_text("no_voices"))
        self.check_autopause.setText(self.ui_text("autopause"))
        self.check_autopause.setToolTip(self.ui_text("autopause_tooltip"))
        self.hinweis.setText(self.ui_text("hint"))
        self.datei_titel.setText(self.ui_text("analyzed_files"))
        self.wort_titel.setText(self.ui_text("new_words"))
        self.btn_undo.setText(self.ui_text("undo"))
        self.aktualisiere_statistik()
        if self.placeholder_key:
            self.zeige_platzhalter(
                self.ui_text(self.placeholder_key, **self.placeholder_args),
                key=self.placeholder_key,
                **self.placeholder_args,
            )
        elif not self.quell_pfad and not self.segmente:
            self.zeige_platzhalter(self.ui_text("placeholder"))
        elif not self.segmente and self.progress_bar.isVisible():
            key = (
                "preparing_text"
                if os.path.splitext(self.quell_pfad or "")[1].lower() == ".txt"
                else "analyzing"
            )
            self.zeige_platzhalter(self.ui_text(key))
        elif self.segmente and self.aktueller_index >= 0:
            self.baue_bildkarten()
        elif self.status_key == "text_read_error":
            self.zeige_platzhalter(
                self.ui_text("text_read_error", **self.status_args),
                key="text_read_error",
                **self.status_args,
            )

    def lokalisierter_fehler(self, fehler):
        text_start = "Textdatei kann nicht vorgelesen werden:"
        bild_fehler_start = "Kein passendes Bild gefunden: "
        bild_lade_start = "Bild für „"
        if fehler.startswith(text_start):
            return "text_read_error", {
                "error": fehler[len(text_start):].strip(),
            }
        if fehler.startswith(bild_fehler_start):
            return "image_not_found_error", {
                "word": fehler[len(bild_fehler_start):].strip(),
            }
        if fehler.startswith(bild_lade_start) and " nicht geladen: " in fehler:
            rest = fehler[len(bild_lade_start):]
            wort, _, detail = rest.partition("“ nicht geladen: ")
            if not detail:
                wort, _, detail = rest.partition("” nicht geladen: ")
            return "image_load_error", {"word": wort, "error": detail}
        if fehler.startswith("IMAGE_INFO_SAVE_ERROR:"):
            return "image_info_save_error", {
                "error": fehler.partition(":")[2].strip(),
            }
        return None, {}

    def set_error_status(self, fehler):
        key, werte = self.lokalisierter_fehler(fehler)
        if key:
            self.set_status(key, **werte)
            return self.ui_text(key, **werte)
        self.status_key = None
        self.status_args = {}
        self.status_label.setText(fehler)
        return fehler

    def init_audio(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self.position_geaendert)
        self.player.durationChanged.connect(lambda d: self.slider_pos.setRange(0, d))
        self.player.playbackStateChanged.connect(self.zustand_geaendert)
        self.player.mediaStatusChanged.connect(self.medienstatus_geaendert)

    def init_shortcuts(self):
        def sc(taste, funktion):
            QShortcut(QKeySequence(taste), self).activated.connect(funktion)
        sc("Space", self.merke_fokus_wort)
        sc("P", self.toggle_wiedergabe)
        sc("Return", self.weiter_zum_naechsten_wort)
        sc("Enter", self.weiter_zum_naechsten_wort)
        sc("Up", lambda: self.fokus_verschieben(-1))
        sc("Down", lambda: self.fokus_verschieben(1))
        sc("R", self.wiederhole_satz)
        sc("Left", self.vorheriger_satz)
        sc("Right", self.naechster_satz)
        sc("Ctrl+Z", self.rueckgaengig)

    # --------------------------- Wörterbuch --------------------------------- #
    def lade_woerterbuch(self):
        if not os.path.exists(WOERTERBUCH_DATEI):
            return
        with open(WOERTERBUCH_DATEI, "rb") as f:
            roh = f.read()
        try:
            text = roh.decode("utf-8")
        except UnicodeDecodeError:
            text = roh.decode("cp1251", errors="ignore")  # alte Dateien
        for zeile in text.splitlines():
            if zeile.strip():
                self.bekannte_woerter.add(zeile.strip().lower())

    def schreibe_woerterbuch(self):
        with open(WOERTERBUCH_DATEI, "w", encoding="utf-8") as f:
            for w in sorted(self.bekannte_woerter):
                f.write(w + "\n")

    # ------------------------------ Datei ----------------------------------- #
    def lade_datei(self):
        pfad, _ = QFileDialog.getOpenFileName(
            self,
            self.ui_text("choose_file_title"),
            "",
            self.ui_text("supported_files"),
        )
        if not pfad:
            return
        self.oeffne_datei(pfad)

    def oeffne_datei(self, pfad):
        if self.progress_bar.isVisible():
            return  # es läuft bereits eine Analyse / Sprachsynthese
        pfad = os.path.abspath(pfad)
        self.speichere_wiedergabestand()
        # Stop setzt die Position auf 0 -> danach darf nichts mehr gespeichert werden
        self.audio_bereit = False
        self.player.stop()
        if os.path.splitext(pfad)[1].lower() == ".txt":
            self.stimmen_widget.show()
            self.lade_text_datei(pfad)
        else:
            self.stimmen_widget.hide()
            self.lade_audio_pfad(pfad)

    def waehle_analysierte_datei(self, item):
        pfad = item.data(Qt.ItemDataRole.UserRole)
        if not pfad:
            return
        if not os.path.isfile(pfad):
            self.set_status("file_not_found", path=pfad)
            return
        if os.path.normcase(os.path.abspath(pfad)) == os.path.normcase(
            os.path.abspath(self.quell_pfad or "")
        ):
            return
        self.oeffne_datei(pfad)

    def registriere_analysierte_datei(self, pfad):
        pfad = os.path.abspath(pfad)
        dateien = self.analysierte_dateien()
        dateien = [eintrag for eintrag in dateien if os.path.normcase(eintrag)
                   != os.path.normcase(pfad)]
        dateien.insert(0, pfad)
        self.einstellungen.setValue("playback/recent_files", dateien)
        self.einstellungen.sync()
        self.aktualisiere_dateiliste()

    def analysierte_dateien(self):
        dateien = self.einstellungen.value("playback/recent_files", [])
        if isinstance(dateien, str):
            dateien = [dateien]
        dateien = [os.path.abspath(pfad) for pfad in (dateien or []) if pfad]
        self.einstellungen.beginGroup("playback/books")
        for gruppe in self.einstellungen.childGroups():
            self.einstellungen.beginGroup(gruppe)
            pfad = self.einstellungen.value("path", "", type=str)
            self.einstellungen.endGroup()
            if pfad:
                dateien.append(os.path.abspath(pfad))
        self.einstellungen.endGroup()

        unique = []
        gesehen = set()
        for pfad in dateien:
            normiert = os.path.normcase(pfad)
            if normiert not in gesehen and os.path.isfile(pfad):
                gesehen.add(normiert)
                unique.append(pfad)
        return unique

    def aktualisiere_dateiliste(self):
        dateien = self.analysierte_dateien()
        aktuell = os.path.normcase(os.path.abspath(self.quell_pfad or ""))
        vorhanden = [self.datei_liste.item(k).data(Qt.ItemDataRole.UserRole)
                     for k in range(self.datei_liste.count())]
        nur_texte = vorhanden == [os.path.abspath(p) for p in dateien]
        if not nur_texte:
            self.datei_liste.clear()
        for zeile, pfad in enumerate(dateien):
            pfad = os.path.abspath(pfad)
            gruppe = self.wiedergabe_einstellungsgruppe(pfad)
            position = self.einstellungen.value(f"{gruppe}/position_ms", 0, type=int)
            dauer = self.einstellungen.value(f"{gruppe}/duration_ms", 0, type=int)
            if os.path.normcase(pfad) == aktuell and self.mp3_pfad and self.audio_bereit:
                position = self.player.position()
                dauer = self.player.duration()
            dauer_text = format_zeit(dauer) if dauer > 0 else "--:--"
            text = f"{os.path.basename(pfad)}  {format_zeit(position)} / {dauer_text}"
            if nur_texte:
                item = self.datei_liste.item(zeile)
                if item.text() != text:
                    item.setText(text)
            else:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, pfad)
                item.setToolTip(pfad)
                self.datei_liste.addItem(item)
            if os.path.normcase(pfad) == aktuell and self.datei_liste.currentItem() is not item:
                self.datei_liste.setCurrentItem(item)

    def lade_text_datei(self, pfad, automatisch_starten=False):
        self.stimmen_widget.show()
        self.quell_pfad = os.path.abspath(pfad)
        self.einstellungen.setValue("playback/last_file", self.quell_pfad)
        self.einstellungen.sync()
        self.btn_laden.setEnabled(False)
        self.setze_bedienung(False)
        self.zeige_platzhalter(
            self.ui_text("preparing_text"), key="preparing_text"
        )
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.set_status("preparing_text")
        self.starte_text_audio(self.quell_pfad, automatisch_starten)

    def starte_text_audio(self, quell_pfad, automatisch_starten=False, satz_index=None):
        quell_pfad = os.path.abspath(quell_pfad)
        stimme = self.combo_stimme.currentData()
        self.text_audio_thread = TextAudioThread(
            quell_pfad, stimme, self
        )
        self.text_audio_thread.fertig.connect(
            lambda audio_pfad, fehler, pfad=quell_pfad, tts_stimme=stimme,
            autoplay=automatisch_starten, index=satz_index: self.text_audio_fertig(
                audio_pfad, fehler, pfad, autoplay, tts_stimme, index
            )
        )
        self.text_audio_thread.finished.connect(
            lambda thread=self.text_audio_thread: self.thread_beendet(thread)
        )
        self.starte_thread(self.text_audio_thread)

    def textstimme_geaendert(self):
        stimme = self.combo_stimme.currentData()
        self.einstellungen.setValue("tts/voice", stimme)
        if (not stimme or not self.quell_pfad
                or os.path.splitext(self.quell_pfad)[1].lower() != ".txt"
                or not self.audio_bereit or self.tts_wechsel_aktiv
                or stimme == self.aktuelle_textstimme):
            return

        index = self.finde_index(self.player.position() / 1000.0)
        index = min(len(self.segmente) - 1, max(0, index))
        war_am_laufen = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.speichere_wiedergabestand()
        self.player.pause()
        self.tts_wechsel_aktiv = True
        self.combo_stimme.setEnabled(False)
        self.btn_laden.setEnabled(False)
        self.setze_bedienung(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.set_status("changing_voice")
        self.starte_text_audio(self.quell_pfad, war_am_laufen, index)

    def text_audio_fertig(
        self, audio_pfad, fehler, quell_pfad, automatisch_starten,
        stimme, satz_index=None
    ):
        if fehler:
            self.progress_bar.hide()
            self.btn_laden.setEnabled(not self.tts_wechsel_aktiv)
            meldung = self.set_error_status(fehler)
            self.zeige_platzhalter(
                meldung,
                key=self.status_key or None,
                **self.status_args,
            )
            if self.tts_wechsel_aktiv:
                self.tts_wechsel_aktiv = False
                self.combo_stimme.setEnabled(True)
                self.setze_bedienung(self.audio_bereit)
                alter_index = self.combo_stimme.findData(self.aktuelle_textstimme)
                if alter_index >= 0:
                    with QSignalBlocker(self.combo_stimme):
                        self.combo_stimme.setCurrentIndex(alter_index)
                    self.einstellungen.setValue("tts/voice", self.aktuelle_textstimme)
            return
        self.aktuelle_textstimme = stimme
        self.lade_audio_pfad(
            audio_pfad,
            automatisch_starten=automatisch_starten,
            einstellungs_pfad=quell_pfad,
            satz_index_beim_wiederherstellen=satz_index,
        )

    @staticmethod
    def wiedergabe_einstellungsgruppe(pfad):
        pfad_norm = os.path.normcase(os.path.abspath(pfad))
        schluessel = hashlib.sha256(pfad_norm.encode("utf-8")).hexdigest()
        return f"playback/books/{schluessel}"

    def lade_audio_pfad(
        self, pfad, automatisch_starten=False, einstellungs_pfad=None,
        satz_index_beim_wiederherstellen=None
    ):
        quellpfad = einstellungs_pfad or pfad
        self.stimmen_widget.setVisible(
            os.path.splitext(quellpfad)[1].lower() == ".txt"
        )
        self.mp3_pfad = os.path.abspath(pfad)
        self.quell_pfad = os.path.abspath(quellpfad)
        gruppe = self.wiedergabe_einstellungsgruppe(self.quell_pfad)
        alter_pfad = self.einstellungen.value("playback/file", "", type=str)
        if (
            not self.einstellungen.contains(f"{gruppe}/position_ms")
            and alter_pfad
            and os.path.normcase(os.path.abspath(alter_pfad))
            == os.path.normcase(self.mp3_pfad)
        ):
            self.einstellungen.setValue(
                f"{gruppe}/position_ms",
                self.einstellungen.value("playback/position_ms", 0, type=int),
            )
        self.position_beim_wiederherstellen = max(
            0, self.einstellungen.value(f"{gruppe}/position_ms", 0, type=int)
        )
        self.aktuell_modell_name = self.combo_modell.currentText()
        self.automatisch_starten = automatisch_starten
        self.satz_index_nach_analyse = satz_index_beim_wiederherstellen
        self.audio_bereit = False
        self.einstellungen.setValue("playback/last_file", self.quell_pfad)
        self.einstellungen.sync()
        self.setze_daten([])
        self.btn_laden.setEnabled(False)
        self.setze_bedienung(False)
        self.zeige_platzhalter(self.ui_text("analyzing"), key="analyzing")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        self.analyse_thread = AnalyseThread(self.mp3_pfad, self.aktuell_modell_name)
        self.analyse_thread.status_update.connect(self.analyse_status_geaendert)
        self.analyse_thread.analyse_beendet.connect(self.analyse_fertig)
        self.analyse_thread.finished.connect(
            lambda thread=self.analyse_thread: self.thread_beendet(thread)
        )
        self.starte_thread(self.analyse_thread)

    def wiederherstelle_wiedergabe(self):
        pfad = self.einstellungen.value("playback/last_file", "", type=str)
        if not pfad:
            pfad = self.einstellungen.value("playback/file", "", type=str)
        if not pfad:
            return
        if not os.path.isfile(pfad):
            self.set_status("recent_file_not_found", path=pfad)
            return

        self.set_status("restoring")
        if os.path.splitext(pfad)[1].lower() == ".txt":
            self.lade_text_datei(pfad, automatisch_starten=True)
        else:
            self.lade_audio_pfad(pfad, automatisch_starten=True)

    def speichere_wiedergabestand(self):
        if not self.mp3_pfad or not self.audio_bereit:
            return
        gruppe = self.wiedergabe_einstellungsgruppe(self.quell_pfad)
        self.einstellungen.setValue(f"{gruppe}/path", self.quell_pfad)
        self.einstellungen.setValue(f"{gruppe}/position_ms", self.player.position())
        self.einstellungen.setValue(f"{gruppe}/duration_ms", self.player.duration())
        self.einstellungen.setValue(f"{gruppe}/model", self.aktuell_modell_name)
        self.einstellungen.setValue("playback/last_file", self.quell_pfad)
        self.einstellungen.sync()
        self.aktualisiere_dateiliste()

    def setze_bedienung(self, aktiv):
        for b in (self.btn_zurueck, self.btn_play, self.btn_weiter, self.btn_wiederholen,
                  self.btn_gemerkt, self.btn_skip):
            b.setEnabled(aktiv)

    def analyse_fertig(self, daten):
        self.progress_bar.hide()
        self.btn_laden.setEnabled(True)
        if not daten or not daten.get("segmente"):
            self.zeige_platzhalter(
                self.ui_text("no_sentences"), key="no_sentences"
            )
            if self.tts_wechsel_aktiv:
                self.tts_wechsel_aktiv = False
                self.combo_stimme.setEnabled(True)
            return
        self.registriere_analysierte_datei(self.quell_pfad)
        self.setze_daten(daten["segmente"])
        if self.satz_index_nach_analyse is not None:
            index = min(len(self.segmente) - 1, max(0, self.satz_index_nach_analyse))
            self.position_beim_wiederherstellen = round(self.starts[index] * 1000)
            self.satz_index_nach_analyse = None
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(self.mp3_pfad)))
        self.player.setPlaybackRate(self.combo_tempo.currentData())
        self.setze_bedienung(True)
        if self.tts_wechsel_aktiv:
            self.tts_wechsel_aktiv = False
            self.combo_stimme.setEnabled(True)
        self.zeige_platzhalter(self.ui_text("press_play"), key="press_play")
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia:
            self.medienstatus_geaendert(self.player.mediaStatus())

    def setze_daten(self, segmente):
        self.segmente = segmente
        self.starts = [s["start"] for s in segmente]
        self.navigation_ziel_index = None
        self.aktueller_index = -1
        self.gerenderter_index = -2
        self.zeitwort_key = None
        self.pause_erledigt_index = -1
        self.auto_pausiert = False
        self.aktuelle_unbekannte = []
        self.fokus_index = 0
        self.satz_label.setText("")
        self.uebersetzung_label.clear()
        self.uebersetzung_label.hide()
        self.aktuelle_uebersetzung = None
        self.baue_liste()
        self.aktualisiere_statistik()

    # ----------------------------- Wiedergabe ------------------------------- #
    def toggle_wiedergabe(self):
        if not self.segmente:
            return
        self.auto_pausiert = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def zustand_geaendert(self, zustand):
        spielt = zustand == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText(self.ui_text("pause" if spielt else "play"))
        if zustand == QMediaPlayer.PlaybackState.PausedState:
            self.speichere_wiedergabestand()

    def medienstatus_geaendert(self, status):
        if (status != QMediaPlayer.MediaStatus.LoadedMedia or not self.mp3_pfad
                or self.audio_bereit):
            return
        self.audio_bereit = True
        dauer = self.player.duration()
        position = self.position_beim_wiederherstellen
        if dauer > 0:
            position = max(0, min(position, dauer - 1000))
        self.player.setPosition(position)
        if self.automatisch_starten:
            self.automatisch_starten = False
            self.player.play()
        self.speichere_wiedergabestand()

    def position_geaendert(self, ms):
        if not self.slider_pos.isSliderDown():
            self.slider_pos.setValue(ms)
        self.zeit_label.setText(f"{format_zeit(ms)} / {format_zeit(self.player.duration())}")
        self.aktualisiere_anzeige()

    def springe_zu_satz(self, index, abspielen=True):
        if not 0 <= index < len(self.segmente):
            return
        self.navigation_ziel_index = index
        self.pause_erledigt_index = -1
        self.auto_pausiert = False
        self.player.setPosition(math.ceil(max(0.0, self.starts[index]) * 1000) + SEEK_VORLAUF_MS)
        if abspielen:
            self.player.play()
        else:
            self.player.pause()
        self.aktualisiere_anzeige()

    def wiederhole_satz(self):
        if self.aktueller_index >= 0:
            self.springe_zu_satz(self.aktueller_index)

    def navigations_index(self):
        if not self.segmente:
            return -1
        if self.navigation_ziel_index is not None:
            return self.navigation_ziel_index
        index = self.finde_index(self.player.position() / 1000.0)
        return min(len(self.segmente) - 1, max(0, index))

    def naechster_satz(self):
        index = self.navigations_index()
        if index < 0:
            return
        self.springe_zu_satz(index + 1)

    def vorheriger_satz(self):
        index = self.navigations_index()
        if index <= 0:
            return
        self.springe_zu_satz(index - 1)

    def springe_zu_listenwort(self, item):
        index = item.data(Qt.ItemDataRole.UserRole + 1)
        self.springe_zu_satz(index)

    # ----------------------------- Anzeige ---------------------------------- #
    def finde_index(self, pos):
        # bleibt auf dem letzten Satz, bis der nächste beginnt (kein Flackern in Pausen)
        return bisect.bisect_right(self.starts, pos) - 1

    def unbekannte_in_satz(self, index):
        gesehen = set()
        ergebnis = []
        for t in self.segmente[index]["tokens"]:
            r = t["rein"]
            if ist_wort(r):
                wl = r.lower()
                if wl not in self.bekannte_woerter and wl not in gesehen:
                    gesehen.add(wl)
                    ergebnis.append(r)
        return ergebnis

    def aktualisiere_anzeige(self):
        if not self.segmente:
            return
        pos = self.player.position() / 1000.0
        position_index = self.finde_index(pos)
        if (self.navigation_ziel_index is not None
                and position_index == self.navigation_ziel_index):
            self.navigation_ziel_index = None
        i = position_index
        self.aktueller_index = i
        wort_token_index = self.zeitwort_token_index(i, pos)
        neuer_zeitwort_key = (i, wort_token_index)
        wort_geaendert = neuer_zeitwort_key != self.zeitwort_key
        self.zeitwort_key = neuer_zeitwort_key
        if i != self.gerenderter_index:
            self.aktualisiere_satz_ansicht()
        elif wort_geaendert:
            self.aktualisiere_wort_highlights()
        if i != self.pause_erledigt_index:
            self.pause_erledigt_index = -1

        if (self.check_autopause.isChecked() and i >= 0 and self.aktuelle_unbekannte
                and i != self.pause_erledigt_index
                and self.navigation_ziel_index is None
                and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and pos >= self.segmente[i]["ende"] - 0.08):
            self.player.pause()
            self.auto_pausiert = True
            self.pause_erledigt_index = i

    def fokus_wort(self):
        if not self.aktuelle_unbekannte:
            return None
        return self.aktuelle_unbekannte[self.fokus_index]

    def zeitwort_token_index(self, index, position):
        if not 0 <= index < len(self.segmente):
            return None
        segment = self.segmente[index]
        woerter = [
            (token_index, token["rein"])
            for token_index, token in enumerate(segment["tokens"])
            if ist_wort(token["rein"])
        ]
        if not woerter:
            return None
        start = segment["start"]
        dauer = segment["ende"] - start
        if position < start:
            return None
        if dauer <= 0:
            return woerter[0][0]

        fortschritt = min(1.0, max(0.0, (position - start) / dauer))
        gesamtgewicht = sum(max(1, len(wort)) for _, wort in woerter)
        zielgewicht = fortschritt * gesamtgewicht
        bisheriges_gewicht = 0
        for token_index, wort in woerter:
            bisheriges_gewicht += max(1, len(wort))
            if zielgewicht < bisheriges_gewicht:
                return token_index
        return woerter[-1][0]

    def aktualisiere_wort_highlights(self):
        index = self.aktueller_index
        if not 0 <= index < len(self.segmente):
            return
        wort_token_index = self.zeitwort_key[1]
        scroll_position = self.satz_label.verticalScrollBar().value()
        self.satz_label.setHtml(
            f"<p align=\"center\">"
            f"{self.satz_html(index, self.fokus_wort(), wort_token_index)}</p>"
        )
        self.satz_label.verticalScrollBar().setValue(scroll_position)
        key = self.aktuelle_uebersetzung
        if key and key in self.uebersetzungen:
            self.set_uebersetzungstext(self.uebersetzungen[key])

    def aktualisiere_satz_ansicht(self):
        i = self.aktueller_index
        neuer_satz = i != self.gerenderter_index
        self.gerenderter_index = i
        if i < 0:
            self.aktuelle_unbekannte = []
            self.fokus_index = 0
            self.ausgewaehltes_bekanntes_wort = None
            self.satz_label.setText("")
            self.uebersetzung_label.clear()
            self.uebersetzung_label.hide()
            self.aktuelle_uebersetzung = None
            if self.bilder_key is not None:
                self.zeige_platzhalter(self.ui_text("press_play"), key="press_play")
            return

        if neuer_satz:
            self.ausgewaehltes_bekanntes_wort = None
        self.aktuelle_unbekannte = self.unbekannte_in_satz(i)
        # neuer Satz -> beim ersten Wort beginnen; sonst Position behalten (am Ende von vorn)
        if neuer_satz or self.fokus_index >= len(self.aktuelle_unbekannte):
            self.fokus_index = 0
        fokus = self.fokus_wort()
        spielwort_index = (
            self.zeitwort_key[1]
            if self.zeitwort_key and self.zeitwort_key[0] == i
            else None
        )
        self.satz_label.setHtml(
            f"<p align=\"center\">"
            f"{self.satz_html(i, fokus, spielwort_index)}</p>"
        )
        self.zeige_uebersetzung(i, neu_versuchen=neuer_satz)

        key = (i, fokus, self.fokus_index, len(self.aktuelle_unbekannte),
               self.ausgewaehltes_bekanntes_wort)
        if key != self.bilder_key:
            self.bilder_key = key
            self.baue_bildkarten()
        self.vorlade_bilder(i)

    def uebersetzungssprache_geaendert(self):
        sprache = self.combo_uebersetzung.currentData()
        self.einstellungen.setValue("translation/language", sprache)
        self.aktualisiere_oberflaeche()
        if 0 <= self.aktueller_index < len(self.segmente):
            self.zeige_uebersetzung(self.aktueller_index)

    @staticmethod
    def uebersetzung_cache_schluessel(text, sprache):
        inhalt = f"{sprache}\0{text}".encode("utf-8")
        return hashlib.sha256(inhalt).hexdigest()

    def uebersetzung_fehlertext(self, fehler):
        if fehler.startswith("RATE_LIMITED:"):
            try:
                sekunden = max(1, int(fehler.partition(":")[2]))
            except ValueError:
                sekunden = 60
            minuten = max(1, (sekunden + 59) // 60)
            stunden, minuten = divmod(minuten, 60)
            sprache = self.combo_uebersetzung.currentData()
            einheiten = {
                "ru": ("ч", "мин"),
                "uk": ("год", "хв"),
                "en": ("h", "min"),
                "fr": ("h", "min"),
                "es": ("h", "min"),
            }
            stunden_einheit, minuten_einheit = einheiten.get(sprache, einheiten["en"])
            teile = []
            if stunden:
                teile.append(f"{stunden} {stunden_einheit}")
            if minuten or not stunden:
                teile.append(f"{minuten} {minuten_einheit}")
            return self.ui_text("translation_rate_limited", time=" ".join(teile))
        return self.ui_text("translation_error", error=fehler)

    def uebersetzung_man_wiederholen(self):
        if 0 <= self.aktueller_index < len(self.segmente):
            self.zeige_uebersetzung(self.aktueller_index, neu_versuchen=True)

    def zeige_uebersetzung(self, index, neu_versuchen=True):
        text = "".join(token["roh"] for token in self.segmente[index]["tokens"]).strip()
        sprache = self.combo_uebersetzung.currentData()
        if not text or not sprache:
            self.aktuelle_uebersetzung = None
            self.uebersetzung_label.hide()
            return

        key = (text, sprache)
        self.aktuelle_uebersetzung = key
        self.uebersetzung_label.show()
        if key not in self.uebersetzungen:
            cache_key = self.uebersetzung_cache_schluessel(text, sprache)
            gespeicherte_uebersetzung = self.einstellungen.value(
                f"translation/cache/{cache_key}", "", type=str
            )
            if gespeicherte_uebersetzung:
                self.uebersetzungen[key] = gespeicherte_uebersetzung
        if key in self.uebersetzungen:
            self.btn_uebersetzung_retry.hide()
            self.set_uebersetzungstext(self.uebersetzungen[key])
            return
        if key in self.uebersetzung_threads:
            self.uebersetzung_label.setText(self.ui_text("translation_loading"))
            return
        if key in self.uebersetzung_fehler and not neu_versuchen:
            self.btn_uebersetzung_retry.setVisible(
                self.uebersetzung_fehler[key].startswith("RATE_LIMITED:")
            )
            self.uebersetzung_label.setText(escape(
                self.uebersetzung_fehlertext(self.uebersetzung_fehler[key])
            ))
            return

        self.btn_uebersetzung_retry.hide()
        self.uebersetzung_label.setText(self.ui_text("translation_loading"))
        thread = UebersetzungThread(text, sprache, self)
        self.uebersetzung_threads[key] = thread
        thread.fertig.connect(self.uebersetzung_fertig)
        thread.finished.connect(
            lambda k=key, laufender_thread=thread:
            self.uebersetzung_thread_beendet(k, laufender_thread)
        )
        self.starte_thread(thread)

    def uebersetzung_fertig(self, text, sprache, uebersetzung, fehler):
        key = (text, sprache)
        if fehler:
            self.uebersetzung_fehler[key] = fehler
            ergebnis = self.uebersetzung_fehlertext(fehler)
            rate_limited = fehler.startswith("RATE_LIMITED:")
        else:
            self.uebersetzung_fehler.pop(key, None)
            self.uebersetzungen[key] = uebersetzung
            cache_key = self.uebersetzung_cache_schluessel(text, sprache)
            self.einstellungen.setValue(
                f"translation/cache/{cache_key}", uebersetzung
            )
            ergebnis = uebersetzung
            rate_limited = False
        if self.aktuelle_uebersetzung == key:
            if not fehler:
                self.btn_uebersetzung_retry.hide()
                self.set_uebersetzungstext(ergebnis)
            else:
                self.btn_uebersetzung_retry.setVisible(rate_limited)
                self.uebersetzung_label.setText(escape(ergebnis))

    def set_uebersetzungstext(self, text):
        zielwoerter = list(re.finditer(r"\w+", text, re.UNICODE))
        hervorheben = set()
        zeitwort_token_index = None
        if (self.zeitwort_key
                and self.zeitwort_key[0] == self.aktueller_index):
            zeitwort_token_index = self.zeitwort_key[1]

        if zielwoerter and zeitwort_token_index is not None:
            quellwoerter = [
                token["rein"]
                for token in self.segmente[self.aktueller_index]["tokens"]
                if ist_wort(token["rein"])
            ]
            aktuelle_quellposition = sum(
                1 for token_index, token in enumerate(
                    self.segmente[self.aktueller_index]["tokens"]
                )
                if token_index < zeitwort_token_index and ist_wort(token["rein"])
            )
            if quellwoerter and aktuelle_quellposition < len(quellwoerter):
                aktives_wort = quellwoerter[aktuelle_quellposition].casefold()
                treffer = [
                    i for i, fund in enumerate(zielwoerter)
                    if fund.group().casefold() == aktives_wort
                ]
                if treffer:
                    hervorheben.update(treffer)
                else:
                    ungefaehre_position = int(
                        (aktuelle_quellposition + 0.5)
                        * len(zielwoerter) / len(quellwoerter)
                    )
                    hervorheben.add(min(len(zielwoerter) - 1, ungefaehre_position))
        else:
            wort = self.ausgewaehltes_bekanntes_wort or self.fokus_wort()
            if wort:
                muster = re.compile(
                    rf"(?<!\w){re.escape(wort)}(?!\w)", re.IGNORECASE
                )
                hervorheben.update(
                    i for i, fund in enumerate(zielwoerter)
                    if muster.fullmatch(fund.group())
                )

        teile = []
        letzte_position = 0
        for i, fund in enumerate(zielwoerter):
            if i not in hervorheben:
                continue
            teile.append(escape(text[letzte_position:fund.start()]))
            teile.append(
                '<span style="background-color:#20a89e; color:#ffffff; '
                'border-radius:3px;">'
                f'{escape(fund.group())}</span>'
            )
            letzte_position = fund.end()
        teile.append(escape(text[letzte_position:]))
        self.uebersetzung_label.setText("".join(teile))

    def satz_html(self, index, fokus, spielwort_index=None):
        teile = []
        for token_index, t in enumerate(self.segmente[index]["tokens"]):
            roh, rein = t["roh"], t["rein"]
            if not ist_wort(rein):
                teile.append(escape(roh))
                continue
            pos = roh.find(rein)
            vor, nach = escape(roh[:pos]), escape(roh[pos + len(rein):])
            wort = escape(rein)
            href = urllib.parse.quote(rein.lower())
            if token_index == spielwort_index:
                teile.append(
                    f'{vor}<span style="background-color:#20a89e;">&nbsp;'
                    f'<a href="{href}" style="color:#ffffff; text-decoration:none;">'
                    f'{wort}</a>&nbsp;</span>{nach}'
                )
                continue
            if rein.lower() in self.bekannte_woerter:
                if self.ausgewaehltes_bekanntes_wort == rein.lower():
                    teile.append(f'{vor}<span style="background-color:#45405f;">&nbsp;'
                                 f'<a href="{href}" style="color:#ffffff; text-decoration:none;">'
                                 f'{wort}</a>&nbsp;</span>{nach}')
                else:
                    teile.append(f'{vor}<a href="{href}" '
                                 f'style="color:#6b7090; text-decoration:underline;">'
                                 f'{wort}</a>{nach}')
                continue
            if fokus and rein.lower() == fokus.lower():
                # aktuelles Wort: kräftig hervorgehoben
                teile.append(f'{vor}<span style="background-color:#7c5cff;">&nbsp;'
                             f'<a href="{href}" style="color:#ffffff; text-decoration:none;">{wort}</a>'
                             f'&nbsp;</span>{nach}')
            else:
                teile.append(f'{vor}<a href="{href}" style="color:#ffcf6b; text-decoration:underline;">'
                             f'{wort}</a>{nach}')
        return "".join(teile)

    def leere_bilder(self):
        while self.bilder_layout.count():
            item = self.bilder_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.bilder_container.setMinimumSize(0, 0)

    def aktualisiere_bilder_container(self):
        anzahl = self.bilder_layout.count()
        if not anzahl:
            self.bilder_container.setMinimumSize(0, 0)
            return
        erste_karte = self.bilder_layout.itemAt(0).widget()
        raender = self.bilder_layout.contentsMargins()
        breite = (
            anzahl * erste_karte.minimumWidth()
            + (anzahl - 1) * self.bilder_layout.spacing()
            + raender.left()
            + raender.right()
        )
        hoehe = erste_karte.minimumHeight() + raender.top() + raender.bottom()
        self.bilder_container.setMinimumSize(breite, hoehe)

    def zeige_platzhalter(self, text, key=None, **werte):
        self.placeholder_key = key
        self.placeholder_args = werte
        self.bilder_key = None
        self.leere_bilder()
        self.bilder_layout.addWidget(BildKarte(text=text))
        self.aktualisiere_bilder_container()

    @staticmethod
    def bild_feedback_id(wort, variante=""):
        kennung = f"{wort.casefold()}\0{variante}".encode("utf-8")
        return hashlib.sha256(kennung).hexdigest()[:20]

    def bild_feedback_statistik(self, wort, quelle, variante=""):
        kennung = self.bild_feedback_id(wort, variante)
        pfad = f"images/feedback/{quelle}/ratings/{kennung}"
        rating = self.einstellungen.value(f"{pfad}/rating", 0, type=int)
        positive = self.einstellungen.value(
            f"images/feedback/stats/{quelle}/positive", 0, type=int
        )
        gesamt = self.einstellungen.value(
            f"images/feedback/stats/{quelle}/total", 0, type=int
        )
        return rating, positive, gesamt

    def bild_bewerten(self, wort, quelle, bewertung, variante=""):
        kennung = self.bild_feedback_id(wort, variante)
        pfad = f"images/feedback/{quelle}/ratings/{kennung}"
        alter_wert = self.einstellungen.value(f"{pfad}/rating", 0, type=int)
        if alter_wert == bewertung:
            self.baue_bildkarten()
            return
        positive_key = f"images/feedback/stats/{quelle}/positive"
        total_key = f"images/feedback/stats/{quelle}/total"
        positive = self.einstellungen.value(positive_key, 0, type=int)
        gesamt = self.einstellungen.value(total_key, 0, type=int)
        positive += int(bewertung == 1) - int(alter_wert == 1)
        gesamt += int(alter_wert == 0)
        self.einstellungen.setValue(f"{pfad}/rating", bewertung)
        self.einstellungen.setValue(positive_key, positive)
        self.einstellungen.setValue(total_key, gesamt)
        self.einstellungen.sync()
        self.baue_bildkarten()

    def aktueller_bildkontext(self, wort):
        if not 0 <= self.aktueller_index < len(self.segmente):
            return wort
        tokens = self.segmente[self.aktueller_index]["tokens"]
        ziel_index = next(
            (i for i, token in enumerate(tokens)
             if token["rein"].casefold() == wort.casefold()),
            None,
        )
        if ziel_index is None:
            return wort
        return bild_suchbegriff(tokens, ziel_index)

    def gemini_bild_anfordern(self, wort, kontext, erneut=False):
        wort_lower = wort.casefold()
        if (not os.environ.get("GEMINI_API_KEY", "").strip()
                or os.path.isfile(gemini_bild_pfad(wort_lower))
                or wort_lower in self.gemini_bilder_in_arbeit
                or (wort_lower in self.gemini_bilder_fehlgeschlagen and not erneut)):
            return
        anzahl_woerter = sum(
            ist_wort(token["rein"])
            for segment in self.segmente
            for token in segment["tokens"]
            if token["rein"].casefold() == wort_lower
        )
        if anzahl_woerter > 1:
            feedback_key = f"images/feedback/stats/gemini/generate/{self.bild_feedback_id(wort)}"
            bereits_generiert = self.einstellungen.value(
                feedback_key, 0, type=int
            )
            if bereits_generiert >= 1:
                return
            self.einstellungen.setValue(feedback_key, bereits_generiert + 1)
            self.einstellungen.sync()
        self.gemini_bilder_fehlgeschlagen.pop(wort_lower, None)
        thread = GeminiBildThread(
            wort_lower, wort, kontext, gemini_bild_pfad(wort_lower), self
        )
        thread.fertig.connect(self.gemini_bild_fertig)
        thread.finished.connect(
            lambda w=wort_lower, laufender_thread=thread:
            self.gemini_bild_thread_beendet(w, laufender_thread)
        )
        self.gemini_bilder_in_arbeit.add(wort_lower)
        self.starte_thread(thread)

    def gemini_bild_fertig(self, wort_lower, generiert, fehler):
        self.gemini_bilder_in_arbeit.discard(wort_lower)
        if generiert:
            self.gemini_bilder_fehlgeschlagen.pop(wort_lower, None)
        else:
            self.gemini_bilder_fehlgeschlagen[wort_lower] = fehler
        aktuelles_wort = self.ausgewaehltes_bekanntes_wort or self.fokus_wort()
        if aktuelles_wort and aktuelles_wort.casefold() == wort_lower:
            self.baue_bildkarten()

    def gemini_bild_thread_beendet(self, wort_lower, thread):
        self.gemini_bilder_in_arbeit.discard(wort_lower)
        thread.deleteLater()

    def baue_bildkarten(self):
        self.placeholder_key = None
        self.placeholder_args = {}
        self.leere_bilder()
        bekanntes_wort = self.ausgewaehltes_bekanntes_wort
        wort = bekanntes_wort or self.fokus_wort()
        if wort is not None:
            wort_lower = wort.casefold()
            kontext = self.aktueller_bildkontext(wort)
            zaehler = (None if bekanntes_wort else
                       f"{self.fokus_index + 1}/{len(self.aktuelle_unbekannte)}")
            for variante, openverse_pfad in enumerate(
                openverse_bild_pfade(wort_lower), start=1
            ):
                openverse_pix = (
                    QPixmap(openverse_pfad)
                    if os.path.exists(openverse_pfad) else None
                )
                if not openverse_pix and variante > 1:
                    continue
                openverse_rating, openverse_positive, openverse_total = (
                    self.bild_feedback_statistik(
                        wort, "openverse", variante=str(variante)
                    )
                )
                openverse_karte = BildVergleichKarte(
                    "openverse",
                    f"{self.ui_text('image_openverse')} #{variante}",
                    wort=wort,
                    nummer=zaehler,
                    pixmap=openverse_pix,
                    platzhalter=self.ui_text("no_image"),
                    interaktiv=bekanntes_wort is None,
                    tooltip=(
                        self.bild_tooltip(
                            openverse_pfad, bekanntes_wort is None
                        ) if openverse_pix else ""
                    ),
                    rating=openverse_rating,
                    positive=openverse_positive,
                    gesamt=openverse_total,
                    rate_ja=self.ui_text("image_rate_up"),
                    rate_nein=self.ui_text("image_rate_down"),
                )
                openverse_karte.bildkarte.geklickt.connect(
                    self.wort_angeklickt_text
                )
                openverse_karte.bewertet.connect(
                    lambda quelle, wert, zielwort=wort, bildvariante=variante:
                    self.bild_bewerten(
                        zielwort, quelle, wert, variante=str(bildvariante)
                    )
                )
                self.bilder_layout.addWidget(openverse_karte)

            gemini_pfad = gemini_bild_pfad(wort_lower)
            gemini_pix = QPixmap(gemini_pfad) if os.path.exists(gemini_pfad) else None
            gemini_rating, gemini_positive, gemini_total = (
                self.bild_feedback_statistik(wort, "gemini")
            )
            gemini_fehler = self.gemini_bilder_fehlgeschlagen.get(wort_lower)
            if gemini_pix:
                gemini_text = self.ui_text("no_image")
                retry_text = ""
            elif wort_lower in self.gemini_bilder_in_arbeit:
                gemini_text = self.ui_text("image_gemini_loading")
                retry_text = ""
            elif not os.environ.get("GEMINI_API_KEY", "").strip():
                gemini_text = self.ui_text("image_gemini_no_key")
                retry_text = ""
            elif gemini_fehler:
                gemini_text = self.ui_text(
                    "image_gemini_error", error=gemini_fehler
                )
                retry_text = self.ui_text("image_retry")
            else:
                gemini_text = self.ui_text("image_gemini_loading")
                retry_text = ""
            gemini_karte = BildVergleichKarte(
                "gemini",
                self.ui_text("image_gemini"),
                wort=wort,
                nummer=zaehler,
                pixmap=gemini_pix,
                platzhalter=gemini_text,
                interaktiv=bekanntes_wort is None,
                tooltip=self.ui_text("image_gemini_warning"),
                rating=gemini_rating,
                positive=gemini_positive,
                gesamt=gemini_total,
                rate_ja=self.ui_text("image_rate_up"),
                rate_nein=self.ui_text("image_rate_down"),
                retry_text=retry_text,
            )
            gemini_karte.bildkarte.geklickt.connect(self.wort_angeklickt_text)
            gemini_karte.bewertet.connect(
                lambda quelle, wert, zielwort=wort:
                self.bild_bewerten(zielwort, quelle, wert)
            )
            gemini_karte.erneut_anfordern.connect(
                lambda zielwort=wort, bildkontext=kontext:
                self.gemini_bild_anfordern(zielwort, bildkontext, erneut=True)
            )
            self.bilder_layout.addWidget(gemini_karte)
            self.gemini_bild_anfordern(wort, kontext)

        if self.bilder_layout.count() == 0:
            text = (
                self.ui_text("no_new_words") if wort is None
                else self.ui_text("no_image")
            )
            self.bilder_layout.addWidget(BildKarte(text=text))
        self.aktualisiere_bilder_container()

    def bild_tooltip(self, pfad, interaktiv):
        details = self.bild_details.get(os.path.abspath(pfad))
        erklaerung = ""
        if details is None:
            try:
                with open(bild_info_pfad(pfad), "r", encoding="utf-8") as f:
                    details = json.load(f)
            except FileNotFoundError:
                pass
            except (OSError, json.JSONDecodeError) as error:
                erklaerung = self.ui_text("image_info_unavailable", error=error)

        if details is None and not erklaerung:
            erklaerung = self.ui_text("image_info_legacy")
        elif details is not None:
            tags = ", ".join(details.get("tags", [])) or self.ui_text("image_no_tags")
            kontext = ", ".join(details.get("context_matches", []))
            if not kontext:
                kontext = self.ui_text("image_no_context_match")
            ziel = {
                "title": "image_target_title",
                "tags": "image_target_tags",
                "title_and_tags": "image_target_title_tags",
                "alternative": "image_target_alternative",
                "description": "image_target_description",
                "gemini_terms": "image_target_gemini_terms",
            }.get(details.get("target_match"), "image_target_tags")
            verfeinerungsfehler = details.get("search_refinement_error")
            erklaerung = self.ui_text(
                "image_info",
                query=details.get("query", ""),
                translated_query=details.get("translated_query")
                or self.ui_text("image_source_missing"),
                title=details.get("title") or self.ui_text("image_unknown_title"),
                description=details.get("description")
                or self.ui_text("image_no_description"),
                tags=tags,
                context=kontext,
                target=self.ui_text(ziel),
                source=details.get("source") or self.ui_text("image_source_missing"),
                refinement_error=(
                    self.ui_text(
                        "image_query_refinement_error",
                        error=verfeinerungsfehler,
                    ) if verfeinerungsfehler else ""
                ),
            )
        erklaerung = f"{erklaerung}\n\n{self.ui_text('image_match_warning')}"
        if interaktiv:
            return f"{erklaerung}\n\n{self.ui_text('remembered_tooltip')}"
        return erklaerung

    def vorlade_bilder(self, index):
        if index < 0:
            return

        indices = [index]
        naechster = index + 1
        while naechster < len(self.segmente) and not self.unbekannte_in_satz(naechster):
            naechster += 1
        if naechster < len(self.segmente):
            indices.append(naechster)

        for satz_index in indices:
            tokens = self.segmente[satz_index]["tokens"]
            for token_index, token in enumerate(tokens):
                wort = token["rein"]
                if not ist_wort(wort) or wort.lower() in self.bekannte_woerter:
                    continue
                wl = wort.lower()
                pfad = bild_pfad(wl)
                if (os.path.exists(pfad) or wl in self.bilder_in_arbeit
                        or wl in self.bilder_fehlgeschlagen):
                    continue
                self.bilder_in_arbeit.add(wl)
                suchbegriff = bild_suchbegriff(tokens, token_index)
                self.bild_queue.append((wl, wort, suchbegriff, pfad))
        self.starte_bild_thread()

    def starte_bild_thread(self):
        if self.bild_thread is not None or not self.bild_queue:
            return
        bilder = self.bild_queue
        self.bild_queue = []
        self.bild_thread = BildLadeThread(bilder, self)
        self.bild_thread.bild_abgeschlossen.connect(self.bild_ladung_abgeschlossen)
        self.bild_thread.finished.connect(self.bild_thread_beendet)
        self.starte_thread(self.bild_thread)

    def bild_ladung_abgeschlossen(self, wort_lower, geladen, fehler, details):
        self.bilder_in_arbeit.discard(wort_lower)
        if details is not None:
            self.bild_details.update({
                os.path.abspath(eintrag["path"]): eintrag["details"]
                for eintrag in details
            })
        if fehler and not geladen:
            self.bilder_fehlgeschlagen.add(wort_lower)
        if fehler:
            self.set_error_status(fehler)
        if geladen and self.aktueller_index >= 0 and any(
            token["rein"].lower() == wort_lower
            for token in self.segmente[self.aktueller_index]["tokens"]
        ):
            self.baue_bildkarten()

    def bild_thread_beendet(self):
        thread = self.bild_thread
        self.bild_thread = None
        if thread is not None:
            thread.deleteLater()
        self.starte_bild_thread()

    # --------------------------- Lernen / Liste ----------------------------- #
    def wort_angeklickt(self, href):
        """Klick auf ein Wort im Satz: dieses Wort wird zum aktuellen Wort."""
        wl = urllib.parse.unquote(href).lower()
        for k, w in enumerate(self.aktuelle_unbekannte):
            if w.lower() == wl:
                self.ausgewaehltes_bekanntes_wort = None
                self.fokus_index = k
                self.aktualisiere_satz_ansicht()
                return
        if self.aktueller_index < 0:
            return
        if any(
            token["rein"].lower() == wl and wl in self.bekannte_woerter
            for token in self.segmente[self.aktueller_index]["tokens"]
        ):
            self.ausgewaehltes_bekanntes_wort = wl
            self.aktualisiere_satz_ansicht()

    def wort_angeklickt_text(self, wort):
        """Klick auf die Bildkarte: Wort merken."""
        self.markiere_woerter([wort])

    def merke_fokus_wort(self):
        """Space: aktuelles Wort merken. Ohne neue Wörter im Satz: Play/Pause."""
        wort = self.fokus_wort()
        if wort is None:
            self.toggle_wiedergabe()
        else:
            self.markiere_woerter([wort])

    def fokus_verschieben(self, delta):
        n = len(self.aktuelle_unbekannte)
        if n:
            self.ausgewaehltes_bekanntes_wort = None
            self.fokus_index = (self.fokus_index + delta) % n
            self.aktualisiere_satz_ansicht()

    def weiter_zum_naechsten_wort(self):
        """Enter: Wort überspringen. Nach dem letzten Wort: weiterspielen (wenn pausiert)."""
        n = len(self.aktuelle_unbekannte)
        if n == 0 or self.fokus_index >= n - 1:
            if self.auto_pausiert:
                self.auto_pausiert = False
                self.player.play()
            elif n:
                self.fokus_index = 0
                self.aktualisiere_satz_ansicht()
            return
        self.fokus_index += 1
        self.aktualisiere_satz_ansicht()

    def markiere_woerter(self, woerter):
        neu = []
        for w in woerter:
            wl = w.lower()
            if wl not in self.bekannte_woerter:
                self.bekannte_woerter.add(wl)
                neu.append(wl)
        if not neu:
            return
        self.ausgewaehltes_bekanntes_wort = None
        with open(WOERTERBUCH_DATEI, "a", encoding="utf-8") as f:
            for wl in neu:
                f.write(wl + "\n")  # UTF-8: ä, ö, ü, ß sind kein Problem
        self.rueckgaengig_stack.append(neu)
        self.set_status("marked", words=", ".join(neu))
        self.nach_aenderung()
        # alles gelernt und am Satzende pausiert -> automatisch weiter
        if self.auto_pausiert and not self.aktuelle_unbekannte:
            self.auto_pausiert = False
            self.player.play()

    def rueckgaengig(self):
        if not self.rueckgaengig_stack:
            return
        gruppe = self.rueckgaengig_stack.pop()
        for wl in gruppe:
            self.bekannte_woerter.discard(wl)
        self.schreibe_woerterbuch()
        self.set_status("undone", words=", ".join(gruppe))
        self.nach_aenderung()

    def nach_aenderung(self):
        self.aktualisiere_satz_ansicht()
        self.baue_liste()
        self.aktualisiere_statistik()

    def baue_liste(self):
        self.liste.clear()
        zaehler = Counter()
        erste = {}
        for idx, s in enumerate(self.segmente):
            for t in s["tokens"]:
                r = t["rein"]
                if not ist_wort(r):
                    continue
                wl = r.lower()
                if wl in self.bekannte_woerter:
                    continue
                zaehler[wl] += 1
                erste.setdefault(wl, (r, idx))
        for wl in sorted(erste, key=lambda wort: zaehler[wort], reverse=True):
            wort, idx = erste[wl]
            text = f"{wort}   ×{zaehler[wl]}" if zaehler[wl] > 1 else wort
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, wl)
            item.setData(Qt.ItemDataRole.UserRole + 1, idx)
            self.liste.addItem(item)
        self.neue_woerter_anzahl = len(erste)

    def aktualisiere_statistik(self):
        self.stat_label.setText(self.ui_text(
            "stats", new=self.neue_woerter_anzahl, known=len(self.bekannte_woerter)
        ))
        self.btn_undo.setEnabled(bool(self.rueckgaengig_stack))

    def closeEvent(self, event):
        self.speichere_wiedergabestand()
        self.audio_bereit = False  # player.stop() setzt die Position auf 0 – nicht mehr speichern
        self.timer.stop()
        self.speicher_timer.stop()
        self.player.stop()

        for thread in tuple(self.aktive_threads):
            if thread.isRunning():
                thread.requestInterruption()
        for thread in tuple(self.aktive_threads):
            if thread.isRunning():
                thread.wait()

        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("Sprachtrainer")
    app.setApplicationName("Sprachtrainer v3")
    icon = erstelle_app_icon()
    app.setWindowIcon(icon)
    app.setStyleSheet(STYLE)
    fenster = SprachLernPlayer()
    fenster.setWindowIcon(icon)
    fenster.show()
    sys.exit(app.exec())
    