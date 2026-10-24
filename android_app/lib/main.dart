import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';

const maxMobileBookBytes = 512 * 1024 * 1024;

void main() => runApp(const SprachtrainerApp());

class SprachtrainerApp extends StatelessWidget {
  const SprachtrainerApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Sprachtrainer',
    theme: ThemeData(colorSchemeSeed: const Color(0xff20a89e)),
    home: const LibraryPage(),
  );
}

class _BookPlaceholder extends StatelessWidget {
  const _BookPlaceholder();

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.secondaryContainer,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Icon(
      Icons.menu_book_rounded,
      color: Theme.of(context).colorScheme.onSecondaryContainer,
    ),
  );
}

TextSpan _translationSpan(
  String text,
  List tokens,
  List<int> wordTokenIndices,
  int? activeTokenIndex,
) {
  if (activeTokenIndex == null || wordTokenIndices.isEmpty) {
    return TextSpan(text: text);
  }
  final sourcePosition = wordTokenIndices.indexOf(activeTokenIndex);
  final sourceWord = (tokens[activeTokenIndex]['rein'] as String).toLowerCase();
  final targetWords = RegExp(r'\w+', unicode: true).allMatches(text).toList();
  if (targetWords.isEmpty) return TextSpan(text: text);
  final exact = targetWords.indexWhere(
    (match) => match.group(0)!.toLowerCase() == sourceWord,
  );
  final targetIndex = exact >= 0
      ? exact
      : min(
          targetWords.length - 1,
          ((sourcePosition + 0.5) *
                  targetWords.length /
                  wordTokenIndices.length)
              .floor(),
        );
  final match = targetWords[targetIndex];
  return TextSpan(
    children: [
      TextSpan(text: text.substring(0, match.start)),
      TextSpan(
        text: match.group(0),
        style: const TextStyle(
          color: Colors.white,
          backgroundColor: Color(0xff20a89e),
          fontWeight: FontWeight.w700,
        ),
      ),
      TextSpan(text: text.substring(match.end)),
    ],
  );
}

String _formatAudioTime(int milliseconds) {
  final seconds = max(0, milliseconds) ~/ 1000;
  final hours = seconds ~/ 3600;
  final minutes = (seconds % 3600) ~/ 60;
  final remainingSeconds = seconds % 60;
  final minuteText = minutes.toString().padLeft(2, '0');
  final secondText = remainingSeconds.toString().padLeft(2, '0');
  return hours > 0
      ? '$hours:$minuteText:$secondText'
      : '$minuteText:$secondText';
}

String _formatAudioMinutes(int milliseconds) {
  if (milliseconds <= 0) return 'Duration unavailable';
  final minutes = (milliseconds + 59999) ~/ 60000;
  return '$minutes min';
}

class Book {
  Book({required this.id, required this.root, required this.metadata}) {
    _sentenceStarts = List<int>.generate(segments.length, (i) {
      final seg = segments[i] as Map<String, dynamic>;
      if (hasWordTimestamps) {
        final tokens = seg['tokens'] as List;
        for (final token in tokens) {
          if ((token['rein'] as String).isNotEmpty && token['start'] is num) {
            return ((token['start'] as num) * 1000).round();
          }
        }
      }
      return (((seg['start'] as num) * 1000)).round();
    });
    _sentenceEnds = List<int>.generate(segments.length, (i) {
      final seg = segments[i] as Map<String, dynamic>;
      if (hasWordTimestamps) {
        final tokens = seg['tokens'] as List;
        for (var t = tokens.length - 1; t >= 0; t--) {
          final token = tokens[t];
          if ((token['rein'] as String).isNotEmpty && token['ende'] is num) {
            return ((token['ende'] as num) * 1000).round();
          }
        }
      }
      return (((seg['ende'] as num) * 1000)).round();
    });
  }

  final String id;
  final Directory root;
  final Map<String, dynamic> metadata;
  late final List<int> _sentenceStarts;
  late final List<int> _sentenceEnds;

  int sentenceStartMs(int index) =>
      (index >= 0 && index < _sentenceStarts.length)
      ? _sentenceStarts[index]
      : 0;

  int sentenceEndMs(int index) =>
      (index >= 0 && index < _sentenceEnds.length) ? _sentenceEnds[index] : 0;

  String get audioPath => '${root.path}/${metadata['audio']}';
  List<dynamic> get segments => metadata['segments'] as List<dynamic>;
  List<dynamic> get translations => metadata['translations'] as List<dynamic>;
  List<dynamic> get assets => metadata['assets'] as List<dynamic>;
  String? get coverImagePath {
    for (final asset in assets) {
      final path = asset as String;
      if ((path.endsWith('.jpg') || path.endsWith('.png')) &&
          File('${root.path}/$path').existsSync()) {
        return '${root.path}/$path';
      }
    }
    return null;
  }

  bool get hasWordTimestamps => metadata['word_timestamps'] == true;
  int get durationMs {
    final savedDuration = metadata['duration_ms'];
    if (savedDuration is num && savedDuration > 0) {
      return savedDuration.round();
    }
    var duration = 0;
    for (final raw in segments) {
      final endMs = ((((raw as Map<String, dynamic>)['ende']) as num) * 1000)
          .round();
      if (endMs > duration) duration = endMs;
    }
    return duration;
  }

  int sentenceIndexAt(int positionMs) {
    if (_sentenceStarts.isEmpty || positionMs < _sentenceStarts.first) {
      return -1;
    }
    var low = 0;
    var high = _sentenceStarts.length - 1;
    var result = 0;
    while (low <= high) {
      final mid = (low + high) ~/ 2;
      if (_sentenceStarts[mid] <= positionMs) {
        result = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return result;
  }

  int? wordTokenIndexAt(int sentenceIndex, int positionMs) {
    if (sentenceIndex < 0 || sentenceIndex >= segments.length) return null;
    final segment = segments[sentenceIndex] as Map<String, dynamic>;
    final startMs = ((segment['start'] as num) * 1000).round();
    final endMs = ((segment['ende'] as num) * 1000).round();
    final tokens = segment['tokens'] as List;
    final words = <int>[
      for (var i = 0; i < tokens.length; i++)
        if ((tokens[i]['rein'] as String).isNotEmpty) i,
    ];
    if (words.isEmpty || positionMs < startMs) return null;
    final allWordsAreTimed = words.every(
      (index) => tokens[index]['start'] is num && tokens[index]['ende'] is num,
    );
    if (hasWordTimestamps && allWordsAreTimed) {
      var activeWord = words.first;
      for (final index in words) {
        final wordStartMs = ((tokens[index]['start'] as num) * 1000).round();
        if (wordStartMs > positionMs) break;
        activeWord = index;
      }
      return activeWord;
    }
    final duration = endMs - startMs;
    if (duration <= 0) return words.first;
    final progress = ((positionMs - startMs) / duration).clamp(0.0, 1.0);
    var totalWeight = 0;
    for (final index in words) {
      final length = (tokens[index]['rein'] as String).length;
      totalWeight += length > 0 ? length : 1;
    }
    final targetWeight = progress * totalWeight;
    var traversedWeight = 0;
    for (final index in words) {
      final length = (tokens[index]['rein'] as String).length;
      traversedWeight += length > 0 ? length : 1;
      if (targetWeight < traversedWeight) return index;
    }
    return words.last;
  }
}

Future<Book> importBook(File file, {String profileId = 'default'}) async {
  if (await file.length() > maxMobileBookBytes) {
    throw const FormatException('Mobile .stbook limit is 512 MiB.');
  }
  final id = (await sha256.bind(file.openRead()).first).toString();
  final root = Directory(
    '${(await getApplicationDocumentsDirectory()).path}/books/'
    '$profileId/$id',
  );
  final readyMarker = File('${root.path}/metadata.json');
  if (await readyMarker.exists()) {
    try {
      final cached = jsonDecode(utf8.decode(await readyMarker.readAsBytes()));
      if (cached is Map<String, dynamic>) {
        return Book(id: id, root: root, metadata: cached);
      }
    } on FormatException {
      // Unreadable marker: extract the book again.
    }
  }
  final input = InputFileStream(file.path);
  try {
    return await _importBookArchive(ZipDecoder().decodeBuffer(input), id, root);
  } finally {
    await input.close();
  }
}

Future<Book> _importBookArchive(
  Archive archive,
  String id,
  Directory root,
) async {
  if (archive.length > 20000) {
    throw const FormatException('Book contains too many files.');
  }
  final entries = <String, ArchiveFile>{};
  final names = <String>{};
  var totalSize = 0;
  for (final entry in archive) {
    final name = entry.name.replaceAll(r'\', '/');
    final isDirectory = name.endsWith('/');
    final parts = name.split('/');
    final safeParts = isDirectory ? parts.sublist(0, parts.length - 1) : parts;
    if (name != entry.name ||
        name.startsWith('/') ||
        safeParts.isEmpty ||
        safeParts.any((part) => part.isEmpty || part == '.' || part == '..') ||
        !names.add(name)) {
      throw const FormatException('Book contains an unsafe file path.');
    }
    if (isDirectory) continue;
    totalSize += entry.size;
    if (totalSize > maxMobileBookBytes) {
      throw const FormatException('Uncompressed book exceeds 512 MiB.');
    }
    entries[name] = entry;
  }
  final manifestEntry = entries['metadata.json'];
  if (manifestEntry == null || manifestEntry.size > 64 * 1024 * 1024) {
    throw const FormatException('Book metadata is missing or too large.');
  }
  final manifestBytes = manifestEntry.content as List<int>;
  final metadata = jsonDecode(utf8.decode(manifestBytes));
  if (metadata is! Map<String, dynamic> ||
      metadata['format'] != 'Sprachtrainer Book' ||
      metadata['version'] != 1 ||
      metadata['segments'] is! List ||
      (metadata['segments'] as List).isEmpty ||
      metadata['translations'] is! List ||
      metadata['assets'] is! List) {
    throw const FormatException('Unsupported or invalid .stbook file.');
  }
  if ((metadata['duration_ms'] != null &&
          (metadata['duration_ms'] is! num ||
              !(metadata['duration_ms'] as num).isFinite ||
              (metadata['duration_ms'] as num) < 0)) ||
      (metadata['word_timestamps'] != null &&
          metadata['word_timestamps'] is! bool)) {
    throw const FormatException('Book contains invalid audio timing data.');
  }
  final audio = metadata['audio'];
  final audioExtension = audio is String && audio.contains('.')
      ? '.${audio.split('.').last.toLowerCase()}'
      : '';
  if (audio is! String ||
      !audio.startsWith('audio/') ||
      audio.split('/').length != 2 ||
      !{
        '.mp3',
        '.wav',
        '.m4a',
        '.ogg',
        '.aif',
        '.aiff',
      }.contains(audioExtension) ||
      !entries.containsKey(audio)) {
    throw const FormatException('Book audio is missing.');
  }
  for (final segment in metadata['segments'] as List) {
    if (segment is! Map ||
        segment['start'] is! num ||
        segment['ende'] is! num ||
        !(segment['start'] as num).isFinite ||
        !(segment['ende'] as num).isFinite ||
        (segment['start'] as num) < 0 ||
        (segment['ende'] as num) < (segment['start'] as num) ||
        segment['tokens'] is! List ||
        (segment['tokens'] as List).isEmpty ||
        (segment['tokens'] as List).any(
          (token) =>
              token is! Map ||
              token['roh'] is! String ||
              token['rein'] is! String,
        )) {
      throw const FormatException('Book contains invalid sentence data.');
    }
    final segmentStartMs = ((segment['start'] as num) * 1000).round();
    var previousWordStartMs = segmentStartMs;
    for (final token in segment['tokens'] as List) {
      final hasStart = token['start'] != null;
      final hasEnd = token['ende'] != null;
      final isWord = (token['rein'] as String).isNotEmpty;
      if (hasStart != hasEnd) {
        throw const FormatException('Book contains incomplete word timings.');
      }
      if (!hasStart) continue;
      final wordStart = token['start'];
      final wordEnd = token['ende'];
      if (wordStart is! num ||
          wordEnd is! num ||
          !wordStart.isFinite ||
          !wordEnd.isFinite ||
          wordStart < (segment['start'] as num) - 0.001 ||
          wordEnd > (segment['ende'] as num) + 0.001 ||
          wordEnd <= wordStart ||
          (isWord && wordStart * 1000 < previousWordStartMs - 1)) {
        throw const FormatException('Book contains invalid word timings.');
      }
      if (isWord) previousWordStartMs = (wordStart * 1000).round();
    }
  }
  for (final translation in metadata['translations'] as List) {
    if (translation is! Map ||
        translation['original'] is! String ||
        translation['language'] is! String ||
        translation['text'] is! String) {
      throw const FormatException('Book contains an invalid translation.');
    }
  }
  for (final asset in metadata['assets'] as List) {
    if (asset is! String ||
        !asset.startsWith('bilder/') ||
        asset.split('/').length != 2 ||
        !entries.containsKey(asset)) {
      throw const FormatException('Book contains an invalid image path.');
    }
  }
  await root.create(recursive: true);
  for (final name in <String>[
    audio,
    ...(metadata['assets'] as List).cast<String>(),
  ]) {
    final output = File('${root.path}/$name');
    await output.parent.create(recursive: true);
    final stream = OutputFileStream(output.path);
    try {
      entries[name]!.writeContent(stream);
    } finally {
      await stream.close();
    }
  }
  await File('${root.path}/metadata.json').writeAsBytes(manifestBytes);
  return Book(id: id, root: root, metadata: metadata);
}

const _initialFingerprint = '0x0000000000000000';

class DiscoveredComputer {
  const DiscoveredComputer(this.address, this.port, this.name);

  final InternetAddress address;
  final int port;
  final String name;
}

class SyncClient {
  SyncClient(this.deviceId, this.token, this.profileId);

  final String deviceId;
  final String token;
  final String profileId;
  final HttpClient _http = HttpClient()
    ..connectionTimeout = const Duration(seconds: 8);

  static Future<List<DiscoveredComputer>> discover() async {
    final socket = await RawDatagramSocket.bind(
      InternetAddress.anyIPv4,
      0,
      reuseAddress: true,
    );
    socket.broadcastEnabled = true;
    final found = <String, DiscoveredComputer>{};
    final result = Completer<List<DiscoveredComputer>>();
    final subscription = socket.listen((event) {
      if (event != RawSocketEvent.read) return;
      final datagram = socket.receive();
      if (datagram == null) return;
      try {
        final decoded = jsonDecode(utf8.decode(datagram.data));
        if (decoded is! Map<String, dynamic>) return;
        final data = decoded;
        if (data['service'] == 'Sprachtrainer' &&
            data['version'] == 1 &&
            data['http_port'] is int &&
            (data['name'] == null || data['name'] is String)) {
          found[datagram.address.address] = DiscoveredComputer(
            datagram.address,
            data['http_port'] as int,
            data['name'] as String? ?? 'Sprachtrainer',
          );
        }
      } on FormatException {
        // Ignore unrelated LAN broadcast packets.
      }
    });
    socket.send(
      utf8.encode('STBOOK_DISCOVER_V1'),
      InternetAddress('255.255.255.255'),
      43981,
    );
    Timer(const Duration(seconds: 3), () {
      if (!result.isCompleted) result.complete(found.values.toList());
      subscription.cancel();
      socket.close();
    });
    return result.future;
  }

  static Future<SyncClient> pair(
    DiscoveredComputer computer,
    String code,
    String deviceId,
    String profileName,
  ) async {
    final client = HttpClient();
    try {
      final request = await client.postUrl(
        Uri.http(
          '${computer.address.address}:${computer.port}',
          '/api/v1/pair',
        ),
      );
      request.headers.contentType = ContentType.json;
      final body = utf8.encode(
        jsonEncode({
          'code': code,
          'device_id': deviceId,
          'name': Platform.operatingSystem,
          'profile_name': profileName,
        }),
      );
      request.contentLength = body.length;
      request.add(body);
      final response = await request.close();
      final responseBody = await response.transform(utf8.decoder).join();
      dynamic data;
      try {
        data = jsonDecode(responseBody);
      } on FormatException {
        if (response.statusCode != HttpStatus.ok) {
          throw HttpException('Pairing failed (${response.statusCode}).');
        }
        rethrow;
      }
      if (response.statusCode != 200 ||
          data is! Map<String, dynamic> ||
          data['token'] is! String ||
          data['profile_id'] is! String ||
          !RegExp(
            r'^(default|[a-f0-9]{32})$',
          ).hasMatch(data['profile_id'] as String)) {
        throw HttpException(
          data is Map && data['error'] is String
              ? data['error'] as String
              : 'Pairing failed (${response.statusCode}).',
        );
      }
      return SyncClient(
        deviceId,
        data['token'] as String,
        data['profile_id'] as String,
      );
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> requestJson(
    DiscoveredComputer computer,
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final bytes = body == null
        ? Uint8List(0)
        : Uint8List.fromList(utf8.encode(jsonEncode(body)));
    final response = await _request(computer, method, path, body: bytes);
    final decoded = jsonDecode(utf8.decode(response.body));
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid server response.');
    }
    if (response.status < 200 || response.status >= 300) {
      throw HttpException('${decoded['error'] ?? 'Sync request failed.'}');
    }
    _verifyResponse(response, sha256.convert(response.body).toString());
    return decoded;
  }

  Future<void> uploadBook(DiscoveredComputer computer, File file) async {
    final digest = await sha256.bind(file.openRead()).first;
    final response = await _request(
      computer,
      'PUT',
      '/api/v1/books/$digest',
      file: file,
      contentDigest: digest.toString(),
    );
    final body = response.body;
    final decoded = jsonDecode(utf8.decode(body));
    if (response.status < 200 || response.status >= 300) {
      throw HttpException('${decoded['error'] ?? 'Book upload failed.'}');
    }
    _verifyResponse(response, sha256.convert(body).toString());
  }

  Future<File> downloadBook(
    DiscoveredComputer computer,
    String id,
    Directory destination,
  ) async {
    final file = File('${destination.path}/$id.stbook');
    final temporary = File('${file.path}.part');
    await temporary.parent.create(recursive: true);
    late final _SyncResponse response;
    var completed = false;
    try {
      response = await _request(
        computer,
        'GET',
        '/api/v1/books/$id',
        responseFile: temporary,
      );
      completed = true;
    } finally {
      if (!completed && await temporary.exists()) await temporary.delete();
    }
    try {
      if (response.status != 200) {
        throw HttpException('Book download failed (${response.status}).');
      }
      _verifyResponse(response, id);
      if (response.bodyDigest != id) {
        throw const FormatException('Downloaded book SHA-256 does not match.');
      }
      await temporary.rename(file.path);
      return file;
    } finally {
      if (await temporary.exists()) await temporary.delete();
    }
  }

  Future<_SyncResponse> _request(
    DiscoveredComputer computer,
    String method,
    String path, {
    Uint8List? body,
    File? file,
    String? contentDigest,
    File? responseFile,
  }) async {
    final payload = body ?? Uint8List(0);
    final digest = contentDigest ?? sha256.convert(payload).toString();
    final timestamp = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    final random = Random.secure();
    final nonce = List<int>.generate(
      16,
      (_) => random.nextInt(256),
    ).map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
    final signed = '$timestamp\n$nonce\n$method\n$path\n$digest';
    final signature = Hmac(
      sha256,
      utf8.encode(token),
    ).convert(utf8.encode(signed)).toString();
    final request = await _http.openUrl(
      method,
      Uri.http('${computer.address.address}:${computer.port}', path),
    );
    request.headers
      ..set('X-ST-Device', deviceId)
      ..set('X-ST-Timestamp', '$timestamp')
      ..set('X-ST-Nonce', nonce)
      ..set('X-ST-Content-SHA256', digest)
      ..set('X-ST-Signature', signature);
    if (file != null) {
      request.contentLength = await file.length();
      await request.addStream(file.openRead());
    } else if (body != null) {
      request.contentLength = body.length;
      request.add(body);
    }
    final response = await request.close();
    if (responseFile != null && response.contentLength > maxMobileBookBytes) {
      await response.drain<void>();
      throw const FormatException('Downloaded book exceeds 512 MiB.');
    }
    final output = responseFile?.openWrite();
    final bytesBuilder = BytesBuilder(copy: false);
    var received = 0;
    try {
      await for (final chunk in response) {
        received += chunk.length;
        if (responseFile != null && received > maxMobileBookBytes) {
          throw const FormatException('Downloaded book exceeds 512 MiB.');
        }
        output?.add(chunk);
        if (responseFile == null) bytesBuilder.add(chunk);
      }
      await output?.flush();
    } finally {
      await output?.close();
    }
    final responseBody = bytesBuilder.takeBytes();
    final responseDigest = responseFile == null
        ? sha256.convert(responseBody).toString()
        : (await sha256.bind(responseFile.openRead()).first).toString();
    return _SyncResponse(
      response.statusCode,
      responseBody,
      response.headers.value('X-ST-Response-Signature'),
      responseDigest,
    );
  }

  void _verifyResponse(_SyncResponse response, String digest) {
    final actual = response.signature;
    final expected = Hmac(
      sha256,
      utf8.encode(token),
    ).convert(utf8.encode('${response.status}\n$digest')).toString();
    if (actual == null || !_constantTimeEquals(actual, expected)) {
      throw const FormatException('Server response signature is invalid.');
    }
  }

  bool _constantTimeEquals(String left, String right) {
    if (left.length != right.length) return false;
    var difference = 0;
    for (var index = 0; index < left.length; index++) {
      difference |= left.codeUnitAt(index) ^ right.codeUnitAt(index);
    }
    return difference == 0;
  }

  void close() => _http.close(force: true);
}

class _SyncResponse {
  _SyncResponse(this.status, this.body, this.signature, this.bodyDigest);
  final int status;
  final Uint8List body;
  final String? signature;
  final String bodyDigest;
}

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key});

  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  final _storage = const FlutterSecureStorage();
  final _books = <Book>[];
  final _knownWords = <String>{};
  final _player = AudioPlayer();
  int _durationMs = 0;
  bool _autoPause = true;
  int _pausedSentence = -1;
  StreamSubscription<Duration>? _durationSubscription;
  final _deviceId = const Uuid().v4();
  SyncClient? _syncClient;
  DiscoveredComputer? _computer;
  String? _error;
  bool _busy = false;
  StreamSubscription<Duration>? _positionSubscription;
  int _watchGeneration = 0;
  String _watchFingerprint = _initialFingerprint;
  StreamSubscription<PlayerState>? _stateSubscription;
  Timer? _navigationTimer;
  int _lastSavedPositionMs = 0;
  Book? _activeBook;
  int _positionMs = 0;
  int? _navigationTargetIndex;
  int? _pendingSeekPositionMs;
  String? _previewWord;
  int? _previewSentenceIndex;
  int? _previewTokenIndex;
  final _listController = ScrollController();
  GlobalKey _activeSentenceKey = GlobalKey();
  String? _followedSentence;
  Map<String, dynamic> _progress = {};
  Map<String, dynamic> _wordRecords = {};
  String _profileId = 'default';
  String _profileName = 'Default';

  @override
  void initState() {
    super.initState();
    _stateSubscription = _player.onPlayerStateChanged.listen((state) {
      if (_activeBook == null || _syncClient == null || _busy) return;
      if (state == PlayerState.paused ||
          state == PlayerState.completed ||
          state == PlayerState.stopped) {
        unawaited(
          _saveProgress().then((_) => _syncState()).catchError((Object _) {}),
        );
      }
    });
    _loadLocalState();
  }

  Future<void> _loadLocalState() async {
    final directory = await getApplicationDocumentsDirectory();
    final saved = await _readPairing();
    final savedProfileId = saved['profileId'] ?? 'default';
    final profileIdValid = RegExp(
      r'^(default|[a-f0-9]{32})$',
    ).hasMatch(savedProfileId);
    _profileId = profileIdValid ? savedProfileId : 'default';
    _profileName = saved['profileName'] ?? 'Default';
    if (!profileIdValid) {
      _error = 'Stored profile is invalid. Pair this device again.';
    }
    final scopedState = File('${directory.path}/sync_state_$_profileId.json');
    final legacyState = File('${directory.path}/sync_state.json');
    final stateFile =
        await scopedState.exists() ||
            _profileId != 'default' ||
            !await legacyState.exists()
        ? scopedState
        : legacyState;
    try {
      if (await stateFile.exists()) {
        final decoded = jsonDecode(await stateFile.readAsString());
        if (decoded is! Map<String, dynamic> ||
            decoded['words'] is! Map ||
            decoded['progress'] is! Map) {
          throw const FormatException('Invalid local synchronization state.');
        }
        _wordRecords = Map<String, dynamic>.from(decoded['words'] as Map);
        _progress = Map<String, dynamic>.from(decoded['progress'] as Map);
        for (final entry in _wordRecords.entries) {
          if (entry.value is! Map ||
              entry.value['known'] is! bool ||
              entry.value['updated_at'] is! int) {
            throw const FormatException('Invalid local dictionary state.');
          }
          if (entry.value['known'] == true) _knownWords.add(entry.key);
        }
        for (final entry in _progress.entries) {
          if (entry.value is! Map ||
              entry.value['position_ms'] is! int ||
              entry.value['updated_at'] is! int) {
            throw const FormatException('Invalid local playback state.');
          }
        }
      }
    } on FormatException catch (error) {
      _error = '$error';
    } on TypeError catch (error) {
      _error = 'Invalid local synchronization state: $error';
    } on FileSystemException catch (error) {
      _error = 'Could not read local synchronization state: $error';
    }
    final host = saved['host'];
    final port = int.tryParse(saved['port'] ?? '');
    final deviceId = saved['deviceId'];
    final token = saved['token'];
    if (profileIdValid &&
        host != null &&
        port != null &&
        deviceId != null &&
        token != null) {
      _computer = DiscoveredComputer(
        InternetAddress(host),
        port,
        'Paired computer',
      );
      _syncClient = SyncClient(deviceId, token, _profileId);
    }
    await _loadProfileBooks();
    if (mounted) {
      setState(() {});
      if (_syncClient != null) {
        _startAutoSync();
        unawaited(_run(_syncAll, background: true));
      }
    }
  }

  Future<Directory> _profileBooksDirectory([String? profileId]) async {
    final directory = await getApplicationDocumentsDirectory();
    return Directory('${directory.path}/books/${profileId ?? _profileId}');
  }

  Future<void> _loadProfileBooks() async {
    final directory = await _profileBooksDirectory();
    if (_profileId == 'default' && !await directory.exists()) {
      final legacy = Directory(
        '${(await getApplicationDocumentsDirectory()).path}/books',
      );
      if (await legacy.exists()) {
        await directory.create(recursive: true);
        for (final file in legacy.listSync().whereType<File>()) {
          if (file.path.endsWith('.stbook')) {
            await file.rename(
              '${directory.path}/${file.uri.pathSegments.last}',
            );
          }
        }
      }
    }
    _books.clear();
    if (!await directory.exists()) return;
    for (final entity in directory.listSync().whereType<File>()) {
      if (!entity.path.endsWith('.stbook')) continue;
      try {
        final book = await importBook(entity, profileId: _profileId);
        if (!_books.any((existing) => existing.id == book.id)) {
          _books.add(book);
        }
      } catch (error) {
        _error = 'Could not open ${entity.uri.pathSegments.last}: $error';
      }
    }
  }

  void _startAutoSync() {
    final generation = ++_watchGeneration;
    unawaited(_watchChanges(generation));
  }

  bool _watchActive(int generation) =>
      mounted && generation == _watchGeneration && _syncClient != null;

  Future<void> _waitWhileBusy(int generation) async {
    while (_busy && _watchActive(generation)) {
      await Future<void>.delayed(const Duration(seconds: 1));
    }
  }

  // Waits on the computer for a change and syncs only when something changed.
  Future<void> _watchChanges(int generation) async {
    await Future<void>.delayed(const Duration(seconds: 2));
    await _waitWhileBusy(generation);
    var baseline = true;
    _watchFingerprint = _initialFingerprint;
    while (_watchActive(generation)) {
      final client = _syncClient!;
      final computer = _computer;
      if (computer == null) return;
      try {
        final result = await client.requestJson(
          computer,
          'GET',
          '/api/v1/changes?since=$_watchFingerprint',
        );
        if (!_watchActive(generation)) return;
        final fingerprint = result['fingerprint'] as String;
        if (baseline) {
          baseline = false;
        } else if (result['changed'] == true) {
          final booksChanged =
              fingerprint.split('x').last != _watchFingerprint.split('x').last;
          await _waitWhileBusy(generation);
          if (!_watchActive(generation)) return;
          await _run(booksChanged ? _syncAll : _syncState, background: true);
          if (!_watchActive(generation)) return;
          final current = await client.requestJson(
            computer,
            'GET',
            '/api/v1/changes?since=$_initialFingerprint',
          );
          _watchFingerprint = current['fingerprint'] as String;
          continue;
        }
        _watchFingerprint = fingerprint;
      } catch (_) {
        if (!_watchActive(generation)) return;
        await Future<void>.delayed(const Duration(seconds: 30));
        if (!_watchActive(generation)) return;
        await _waitWhileBusy(generation);
        await _run(_syncAll, background: true);
        baseline = true;
        _watchFingerprint = _initialFingerprint;
      }
    }
  }

  Future<void> _importFile() async {
    final picked = await FilePicker.pickFile(
      type: FileType.custom,
      allowedExtensions: ['stbook'],
    );
    final path = picked?.path;
    if (path == null) return;
    await _run(() async {
      final book = await importBook(File(path), profileId: _profileId);
      final booksDirectory = await _profileBooksDirectory();
      final libraryFile = File('${booksDirectory.path}/${book.id}.stbook');
      await libraryFile.parent.create(recursive: true);
      if (File(path).absolute.path != libraryFile.absolute.path) {
        await File(path).copy(libraryFile.path);
      }
      if (!_books.any((existing) => existing.id == book.id)) {
        _books.add(book);
      }
      await _openBook(book);
    });
  }

  Future<void> _openBook(Book book) async {
    _activeBook = book;
    _followedSentence = null;
    _pausedSentence = -1;
    _navigationTargetIndex = null;
    _pendingSeekPositionMs = null;
    _navigationTimer?.cancel();
    _previewWord = null;
    _previewSentenceIndex = null;
    _previewTokenIndex = null;
    if (_listController.hasClients) _listController.jumpTo(0);
    await _player.stop();
    await _player.setSourceDeviceFile(book.audioPath);
    await _durationSubscription?.cancel();
    _durationSubscription = _player.onDurationChanged.listen((duration) {
      if (mounted) setState(() => _durationMs = duration.inMilliseconds);
    });
    _durationMs =
        (await _player.getDuration())?.inMilliseconds ?? book.durationMs;
    _positionMs = (_progress[book.id]?['position_ms'] as int?) ?? 0;
    _lastSavedPositionMs = _positionMs;
    await _player.seek(Duration(milliseconds: _positionMs));
    await _positionSubscription?.cancel();
    _positionSubscription = _player.onPositionChanged.listen((position) {
      if (!mounted || _activeBook?.id != book.id) return;
      final positionMs = position.inMilliseconds;
      final previousSentenceIndex = book.sentenceIndexAt(_positionMs);
      if (_pendingSeekPositionMs != null) {
        final target = _navigationTargetIndex;
        if (target != null) {
          if (book.sentenceIndexAt(positionMs) != target) return;
          _navigationTargetIndex = null;
        } else if ((positionMs - _pendingSeekPositionMs!).abs() > 750) {
          return;
        }
        _pendingSeekPositionMs = null;
        _navigationTimer?.cancel();
      }
      if (_previewSentenceIndex != null &&
          book.sentenceIndexAt(_positionMs) == _previewSentenceIndex &&
          book.sentenceIndexAt(positionMs) != _previewSentenceIndex) {
        _previewWord = null;
        _previewSentenceIndex = null;
        _previewTokenIndex = null;
      }
      setState(() => _positionMs = positionMs);
      final sentenceIndex = book.sentenceIndexAt(positionMs);
      if (sentenceIndex >= 0 && sentenceIndex != previousSentenceIndex) {
        _followSentence('${book.id}:$sentenceIndex', sentenceIndex);
      }
      _autoPauseCheck(book, positionMs, previousSentenceIndex);
      if ((positionMs - _lastSavedPositionMs).abs() >= 5000) {
        _lastSavedPositionMs = positionMs;
        unawaited(
          _saveProgress().catchError((Object error) {
            if (mounted) setState(() => _error = '$error');
          }),
        );
      }
    });
    if (mounted) {
      setState(() {});
      final sentenceIndex = book.sentenceIndexAt(_positionMs);
      if (sentenceIndex >= 0) {
        _followSentence('${book.id}:$sentenceIndex', sentenceIndex);
      }
    }
  }

  Timer? _autoPauseTimer;
  int? _autoPauseTimerSentence;

  bool _hasUnknownWord(Map<String, dynamic> segment) =>
      (segment['tokens'] as List).any((token) {
        final word = (token['rein'] as String).toLowerCase();
        return word.isNotEmpty && !_knownWords.contains(word);
      });

  void _pauseAtSentenceEnd(int index) {
    _autoPauseTimer?.cancel();
    _autoPauseTimerSentence = null;
    _pausedSentence = index;
    unawaited(_player.pause());
  }

  // Position events arrive only every few hundred ms, so the pause is
  // scheduled with a timer to stop at the exact end of the sentence.
  void _autoPauseCheck(Book book, int positionMs, int previousIndex) {
    if (!_autoPause || _player.state != PlayerState.playing) {
      _autoPauseTimer?.cancel();
      _autoPauseTimerSentence = null;
      return;
    }
    final index = book.sentenceIndexAt(positionMs);
    if (previousIndex >= 0 &&
        previousIndex < index &&
        _pausedSentence != previousIndex) {
      final previous = book.segments[previousIndex] as Map<String, dynamic>;
      if (_hasUnknownWord(previous)) {
        final endMs = book.sentenceEndMs(previousIndex);
        _pauseAtSentenceEnd(previousIndex);
        unawaited(_player.seek(Duration(milliseconds: endMs)));
        return;
      }
    }
    if (index < 0 || _pausedSentence == index) return;
    final segment = book.segments[index] as Map<String, dynamic>;
    if (!_hasUnknownWord(segment)) return;
    final endMs = book.sentenceEndMs(index);
    final nextStartMs = index + 1 < book.segments.length
        ? book.sentenceStartMs(index + 1)
        : endMs;
    final targetEndMs = min(endMs, nextStartMs);
    if (positionMs >= targetEndMs) {
      _pauseAtSentenceEnd(index);
      return;
    }
    final remaining = targetEndMs - positionMs;
    if (remaining <= 80) {
      _pauseAtSentenceEnd(index);
    } else if (remaining <= 1500 && _autoPauseTimerSentence != index) {
      _autoPauseTimer?.cancel();
      _autoPauseTimerSentence = index;
      final delayMs = max(0, remaining - 80);
      _autoPauseTimer = Timer(Duration(milliseconds: delayMs), () {
        if (_autoPause && _player.state == PlayerState.playing) {
          _pauseAtSentenceEnd(index);
        }
      });
    }
  }

  Future<void> _seekToPosition(int positionMs, {int? sentenceIndex}) async {
    final book = _activeBook;
    if (book == null) return;
    final totalDurationMs = _durationMs > 0 ? _durationMs : book.durationMs;
    final targetMs = positionMs.clamp(0, max(0, totalDurationMs)).toInt();
    final targetIndex = sentenceIndex ?? book.sentenceIndexAt(targetMs);
    _navigationTimer?.cancel();
    _navigationTargetIndex =
        targetIndex >= 0 && targetIndex < book.segments.length
        ? targetIndex
        : null;
    _pendingSeekPositionMs = targetMs;
    _pausedSentence = -1;
    _autoPauseTimer?.cancel();
    _autoPauseTimerSentence = null;
    setState(() => _positionMs = targetMs);
    if (_navigationTargetIndex != null) {
      _followSentence('${book.id}:$targetIndex', targetIndex);
    }
    _navigationTimer = Timer(const Duration(seconds: 2), () async {
      if (!mounted || _pendingSeekPositionMs != targetMs) return;
      final actualPosition = await _player.getCurrentPosition();
      if (!mounted || _pendingSeekPositionMs != targetMs) return;
      _navigationTargetIndex = null;
      _pendingSeekPositionMs = null;
      if (actualPosition != null) {
        _positionMs = actualPosition.inMilliseconds;
      }
      setState(() {});
    });
    await _player.seek(Duration(milliseconds: targetMs));
    await _saveProgress();
  }

  Future<void> _seekToSentence(int index, {bool autoPlay = true}) async {
    final book = _activeBook;
    if (book == null || index < 0 || index >= book.segments.length) return;
    final wasPlaying = _player.state == PlayerState.playing;
    if (wasPlaying) {
      await _player.pause();
    }
    final startMs = book.sentenceStartMs(index);
    await _seekToPosition(startMs, sentenceIndex: index);
    if (autoPlay || wasPlaying) {
      unawaited(
        _player.resume().catchError((Object error) {
          if (mounted) setState(() => _error = '$error');
        }),
      );
    }
  }

  int _currentSentenceIndex() {
    final book = _activeBook;
    if (book == null || book.segments.isEmpty) return -1;
    if (_navigationTargetIndex != null) return _navigationTargetIndex!;
    final index = book.sentenceIndexAt(_positionMs);
    return index < 0 ? 0 : index.clamp(0, book.segments.length - 1);
  }

  Future<void> _previousSentence() async {
    final book = _activeBook;
    if (book == null || book.segments.isEmpty) return;
    final currentIndex = _currentSentenceIndex();
    if (currentIndex <= 0) {
      await _seekToSentence(0);
      return;
    }
    await _seekToSentence(currentIndex - 1);
  }

  Future<void> _nextSentence() async {
    final book = _activeBook;
    if (book == null || book.segments.isEmpty) return;
    final currentIndex = _currentSentenceIndex();
    if (currentIndex < 0) {
      await _seekToSentence(0);
      return;
    }
    if (currentIndex + 1 < book.segments.length) {
      await _seekToSentence(currentIndex + 1);
    }
  }

  Future<void> _replaySentence() async {
    final book = _activeBook;
    if (book == null || book.segments.isEmpty) return;
    final currentIndex = _currentSentenceIndex();
    if (currentIndex >= 0) {
      await _seekToSentence(currentIndex);
    }
  }

  Future<void> _markWord(String word) async {
    final normalized = word.toLowerCase();
    if (_knownWords.contains(normalized)) return;
    final now = DateTime.now().millisecondsSinceEpoch;
    setState(() {
      _knownWords.add(normalized);
      _wordRecords[normalized] = {'known': true, 'updated_at': now};
    });
    await _saveState();
    await _syncState();
  }

  Future<void> _saveState() async {
    final directory = await getApplicationDocumentsDirectory();
    final file = File('${directory.path}/sync_state_$_profileId.json');
    await file.parent.create(recursive: true);
    await file.writeAsString(
      jsonEncode({'version': 1, 'words': _wordRecords, 'progress': _progress}),
    );
  }

  Future<void> _saveProgress() async {
    final book = _activeBook;
    if (book == null) return;
    _progress[book.id] = {
      'position_ms': _positionMs,
      'updated_at': DateTime.now().millisecondsSinceEpoch,
    };
    await _saveState();
  }

  Future<void> _discoverAndPair() async {
    await _run(() async {
      final computers = await SyncClient.discover();
      if (computers.isEmpty) {
        throw const SocketException(
          'No Sprachtrainer computer found on Wi-Fi.',
        );
      }
      if (!mounted) return;
      final selected = await showDialog<DiscoveredComputer>(
        context: context,
        builder: (context) => SimpleDialog(
          title: const Text('Choose computer'),
          children: [
            for (final computer in computers)
              SimpleDialogOption(
                onPressed: () => Navigator.pop(context, computer),
                child: Text('${computer.name} (${computer.address.address})'),
              ),
          ],
        ),
      );
      if (!mounted || selected == null) return;
      final codeController = TextEditingController();
      final profileController = TextEditingController(text: _profileName);
      var selectedProfileName = _profileName;
      late final SyncClient? pairedClient;
      try {
        pairedClient = await showDialog<SyncClient>(
          context: context,
          builder: (dialogContext) {
            var pairing = false;
            var pairingError = '';
            return StatefulBuilder(
              builder: (context, setDialogState) {
                Future<void> submitCode() async {
                  final code = codeController.text.trim();
                  if (!RegExp(r'^\d{6}$').hasMatch(code)) {
                    setDialogState(
                      () => pairingError = 'Enter the six-digit code.',
                    );
                    return;
                  }
                  setDialogState(() {
                    pairing = true;
                    pairingError = '';
                  });
                  try {
                    final profileName = profileController.text.trim();
                    if (profileName.isEmpty) {
                      setDialogState(
                        () => pairingError = 'Enter a profile name.',
                      );
                      return;
                    }
                    selectedProfileName = profileName;
                    final client = await SyncClient.pair(
                      selected,
                      code,
                      _syncClient?.deviceId ?? _deviceId,
                      profileName,
                    );
                    if (!dialogContext.mounted) {
                      client.close();
                      return;
                    }
                    Navigator.pop(dialogContext, client);
                  } catch (error) {
                    if (!dialogContext.mounted) return;
                    setDialogState(() {
                      pairing = false;
                      pairingError = error is HttpException
                          ? error.message
                          : '$error';
                    });
                  }
                }

                return AlertDialog(
                  title: const Text('Pair device'),
                  content: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text(
                        'Pair only on a trusted private Wi-Fi network. '
                        'Local sync traffic is not encrypted. Use the same '
                        'profile name on devices that should share books and '
                        'progress; use different names for separate users.',
                      ),
                      TextField(
                        controller: profileController,
                        maxLength: 80,
                        decoration: const InputDecoration(
                          labelText: 'User/profile name',
                        ),
                      ),
                      TextField(
                        controller: codeController,
                        keyboardType: TextInputType.number,
                        maxLength: 6,
                        onSubmitted: (_) => submitCode(),
                        decoration: InputDecoration(
                          labelText: 'One-time code',
                          errorText: pairingError.isEmpty ? null : pairingError,
                        ),
                      ),
                    ],
                  ),
                  actions: [
                    TextButton(
                      onPressed: pairing
                          ? null
                          : () => Navigator.pop(dialogContext),
                      child: const Text('Cancel'),
                    ),
                    FilledButton(
                      onPressed: pairing ? null : submitCode,
                      child: pairing
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Pair'),
                    ),
                  ],
                );
              },
            );
          },
        );
      } finally {
        Future<void>.delayed(
          const Duration(seconds: 1),
          codeController.dispose,
        );
        Future<void>.delayed(
          const Duration(seconds: 1),
          profileController.dispose,
        );
      }
      if (!mounted || pairedClient == null) {
        pairedClient?.close();
        return;
      }
      final client = pairedClient;
      final profileChanged = client.profileId != _profileId;
      _profileId = client.profileId;
      _profileName = selectedProfileName;
      await _writePairing({
        'host': selected.address.address,
        'port': '${selected.port}',
        'deviceId': client.deviceId,
        'token': client.token,
        'profileId': _profileId,
        'profileName': _profileName,
      });
      _syncClient?.close();
      _computer = selected;
      _syncClient = client;
      if (profileChanged) {
        await _player.stop();
        _activeBook = null;
        _positionMs = 0;
        _progress = {};
        _wordRecords = {};
        _knownWords.clear();
        final directory = await getApplicationDocumentsDirectory();
        final stateFile = File('${directory.path}/sync_state_$_profileId.json');
        if (await stateFile.exists()) {
          final decoded = jsonDecode(await stateFile.readAsString());
          _wordRecords = Map<String, dynamic>.from(decoded['words'] as Map);
          _progress = Map<String, dynamic>.from(decoded['progress'] as Map);
          _knownWords.addAll(
            _wordRecords.entries
                .where((entry) => entry.value['known'] == true)
                .map((entry) => entry.key),
          );
        }
        await _loadProfileBooks();
        if (mounted) setState(() {});
      }
      _startAutoSync();
      await _syncAll();
    });
  }

  Future<File> _pairingFile() async =>
      File('${(await getApplicationDocumentsDirectory()).path}/pairing.json');

  // The Keystore-backed storage can lose its key after an app update or
  // restore, so the pairing is also kept in the app's private directory.
  Future<Map<String, String>> _readPairing() async {
    try {
      final file = await _pairingFile();
      if (await file.exists()) {
        final decoded = jsonDecode(await file.readAsString());
        if (decoded is Map) {
          final values = decoded.map((k, v) => MapEntry('$k', '$v'));
          if (['host', 'port', 'deviceId', 'token'].every(values.containsKey)) {
            return values;
          }
        }
      }
    } catch (_) {}
    final values = <String, String>{};
    try {
      for (final key in ['host', 'port', 'deviceId', 'token']) {
        final value = await _storage.read(key: key);
        if (value != null) values[key] = value;
      }
    } catch (_) {
      return {};
    }
    if (values.length == 4) await _writePairing(values, secure: false);
    return values;
  }

  Future<void> _writePairing(
    Map<String, String> values, {
    bool secure = true,
  }) async {
    final file = await _pairingFile();
    final existing = await file.exists()
        ? (jsonDecode(await file.readAsString()) as Map)
        : {};
    final merged = {...existing.map((k, v) => MapEntry('$k', '$v')), ...values};
    await file.writeAsString(jsonEncode(merged), flush: true);
    if (!secure) return;
    try {
      for (final entry in values.entries) {
        await _storage.write(key: entry.key, value: entry.value);
      }
    } catch (_) {}
  }

  bool _syncFailed = false;

  Future<void> _syncAll() async {
    try {
      await _syncAllImpl();
      if (mounted) setState(() => _syncFailed = false);
    } catch (_) {
      if (mounted) setState(() => _syncFailed = true);
      rethrow;
    }
  }

  Future<void> _syncAllImpl() async {
    final client = _syncClient;
    final previousComputer = _computer;
    if (client == null || previousComputer == null) {
      throw const SocketException('Pair with a computer first.');
    }
    var computer = previousComputer;
    try {
      await client.requestJson(computer, 'GET', '/api/v1/books');
    } on SocketException {
      final discovered = await SyncClient.discover();
      if (discovered.isEmpty) rethrow;
      final sameName = discovered.where(
        (candidate) => candidate.name == previousComputer.name,
      );
      final replacement = sameName.isNotEmpty
          ? sameName.first
          : discovered.first;
      if (replacement.address == previousComputer.address &&
          replacement.port == previousComputer.port) {
        rethrow;
      }
      computer = replacement;
      _computer = replacement;
      await _writePairing({
        'host': replacement.address.address,
        'port': '${replacement.port}',
        'deviceId': client.deviceId,
        'token': client.token,
      });
    }
    final bookDirectory = await _profileBooksDirectory();
    await bookDirectory.create(recursive: true);
    final serverBooks = await client.requestJson(
      computer,
      'GET',
      '/api/v1/books',
    );
    final remoteIds = (serverBooks['books'] as List)
        .map((entry) => entry['id'] as String)
        .toSet();
    final remoteState = await client.requestJson(
      computer,
      'GET',
      '/api/v1/state',
    );
    final deletedIds = Map<String, dynamic>.from(
      remoteState['deleted_books'] as Map? ?? {},
    ).keys.toSet();
    for (final file in bookDirectory.listSync().whereType<File>()) {
      if (file.path.endsWith('.stbook')) {
        final id = (await sha256.bind(file.openRead()).first).toString();
        if (deletedIds.contains(id) && !remoteIds.contains(id)) {
          await file.delete();
          _books.removeWhere((book) => book.id == id);
          if (_activeBook?.id == id) _activeBook = null;
        } else if (!remoteIds.contains(id)) {
          await client.uploadBook(computer, file);
        }
      }
    }
    _mergeState(remoteState);
    final localState = {
      'version': 1,
      'words': _wordRecords,
      'progress': _progress,
    };
    final result = await client.requestJson(
      computer,
      'PUT',
      '/api/v1/state',
      body: localState,
    );
    _mergeState(result);
    final refreshed = await client.requestJson(
      computer,
      'GET',
      '/api/v1/books',
    );
    final ids = (refreshed['books'] as List)
        .map((entry) => entry['id'] as String)
        .toSet();
    final failures = <String>[];
    for (final id in ids) {
      final file = File('${bookDirectory.path}/$id.stbook');
      if (await file.exists()) {
        if (!_books.any((existing) => existing.id == id)) {
          try {
            _books.add(await importBook(file, profileId: _profileId));
          } catch (error) {
            await file.delete();
            failures.add('${id.substring(0, 8)}: $error');
          }
        }
        continue;
      }
      try {
        final downloaded = await client.downloadBook(
          computer,
          id,
          bookDirectory,
        );
        final book = await importBook(downloaded, profileId: _profileId);
        if (!_books.any((existing) => existing.id == book.id)) _books.add(book);
      } catch (error) {
        failures.add('${id.substring(0, 8)}: $error');
      }
    }
    await _saveState();
    if (mounted) setState(() {});
    if (failures.isNotEmpty) {
      throw HttpException('Books not loaded: ${failures.join('; ')}');
    }
  }

  void _mergeState(Map<String, dynamic> state) {
    final remoteWords = Map<String, dynamic>.from(state['words'] as Map? ?? {});
    for (final entry in remoteWords.entries) {
      final old = _wordRecords[entry.key];
      if (old == null ||
          (entry.value['updated_at'] as int) > (old['updated_at'] as int) ||
          ((entry.value['updated_at'] as int) == (old['updated_at'] as int) &&
              entry.value['known'] == true &&
              old['known'] == false)) {
        _wordRecords[entry.key] = entry.value;
      }
    }
    final remoteProgress = Map<String, dynamic>.from(
      state['progress'] as Map? ?? {},
    );
    for (final entry in remoteProgress.entries) {
      final old = _progress[entry.key];
      if (old == null ||
          (entry.value['updated_at'] as int) > (old['updated_at'] as int) ||
          ((entry.value['updated_at'] as int) == (old['updated_at'] as int) &&
              (entry.value['position_ms'] as int) >
                  (old['position_ms'] as int))) {
        _progress[entry.key] = entry.value;
        if (_activeBook?.id == entry.key &&
            _player.state != PlayerState.playing) {
          _positionMs = entry.value['position_ms'] as int;
          _lastSavedPositionMs = _positionMs;
          unawaited(_player.seek(Duration(milliseconds: _positionMs)));
        }
      }
    }
    _knownWords
      ..clear()
      ..addAll(
        _wordRecords.entries
            .where((entry) => entry.value['known'] == true)
            .map((entry) => entry.key),
      );
  }

  Future<void> _syncState() async {
    final client = _syncClient;
    final computer = _computer;
    if (client == null || computer == null) return;
    final merged = await client.requestJson(
      computer,
      'PUT',
      '/api/v1/state',
      body: {'version': 1, 'words': _wordRecords, 'progress': _progress},
    );
    _mergeState(merged);
    await _saveState();
    if (mounted) setState(() {});
  }

  Future<void> _run(
    Future<void> Function() action, {
    bool background = false,
  }) async {
    setState(() {
      _busy = true;
      if (!background) _error = null;
    });
    try {
      await action();
    } catch (error) {
      final offline =
          error is SocketException ||
          error is TimeoutException ||
          error is HandshakeException;
      // Background syncs stay silent when the computer is simply unreachable.
      if (background && offline) return;
      if (mounted) {
        setState(
          () => _error = offline
              ? 'Computer not reachable. Changes sync when it is back.'
              : '$error',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    _watchGeneration++;
    _stateSubscription?.cancel();
    _navigationTimer?.cancel();
    _listController.dispose();
    unawaited(_durationSubscription?.cancel());
    _player.dispose();
    _syncClient?.close();
    super.dispose();
  }

  Future<void> _closeBook() async {
    await _player.pause();
    await _saveProgress();
    if (!mounted) return;
    _navigationTimer?.cancel();
    setState(() {
      _activeBook = null;
      _followedSentence = null;
      _pausedSentence = -1;
      _navigationTargetIndex = null;
      _pendingSeekPositionMs = null;
      _previewWord = null;
      _previewSentenceIndex = null;
      _previewTokenIndex = null;
    });
    if (_listController.hasClients) _listController.jumpTo(0);
    await _syncState();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: _activeBook == null,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) _run(_closeBook);
    },
    child: _scaffold(context),
  );

  Widget _scaffold(BuildContext context) => Scaffold(
    appBar: AppBar(
      leading: _activeBook == null
          ? null
          : IconButton(
              icon: const Icon(Icons.arrow_back),
              tooltip: 'Books',
              onPressed: () => _run(_closeBook),
            ),
      title: Text(
        _activeBook?.metadata['source_name'] as String? ?? 'Sprachtrainer',
        overflow: TextOverflow.ellipsis,
      ),
      actions: [
        if (_activeBook == null)
          IconButton(
            tooltip: 'Open .stbook',
            onPressed: _busy ? null : _importFile,
            icon: const Icon(Icons.add),
          ),
        if (_syncClient != null)
          IconButton(
            tooltip: 'Sync with computer',
            onPressed: _busy ? null : () => _run(_syncAll),
            icon: _busy
                ? const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.sync),
          ),
      ],
    ),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          child: Row(
            children: [
              if (_syncClient != null)
                Expanded(child: Text('Profile: $_profileName')),
              OutlinedButton.icon(
                onPressed: _busy ? null : _discoverAndPair,
                icon: Icon(
                  _syncClient == null || _syncFailed
                      ? Icons.wifi
                      : Icons.switch_account,
                ),
                label: Text(
                  _syncClient == null
                      ? 'Pair / discover'
                      : _syncFailed
                      ? 'Reconnect / profile'
                      : 'Change profile',
                ),
              ),
            ],
          ),
        ),
        if (_activeBook != null && !_activeBook!.hasWordTimestamps)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Text(
              'This saved book has no word timings. Re-analyze its original '
              'audio on desktop for precise highlighting.',
              style: TextStyle(fontSize: 12),
            ),
          ),
        if (_activeBook != null) _imageStrip(_activeBook!),
        Expanded(
          child: GestureDetector(
            behavior: HitTestBehavior.translucent,
            onHorizontalDragEnd: (details) {
              if (_activeBook != null &&
                  (details.primaryVelocity ?? 0) < -300) {
                _run(_closeBook);
              }
            },
            child: Stack(
              children: [
                RefreshIndicator(
                  onRefresh: () => _run(_syncAll),
                  child: _books.isEmpty
                      ? ListView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          children: const [
                            SizedBox(height: 160),
                            Center(
                              child: Text(
                                'Open a .stbook or pull down to sync.',
                              ),
                            ),
                          ],
                        )
                      : ListView.builder(
                          controller: _listController,
                          physics: const AlwaysScrollableScrollPhysics(),
                          itemCount:
                              _activeBook?.segments.length ?? _books.length,
                          itemBuilder: (context, index) {
                            if (_activeBook == null) {
                              final book = _books[index];
                              final coverPath = book.coverImagePath;
                              return Card(
                                margin: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 4,
                                ),
                                child: ListTile(
                                  contentPadding: const EdgeInsets.all(12),
                                  leading: SizedBox.square(
                                    dimension: 52,
                                    child: ClipRRect(
                                      borderRadius: BorderRadius.circular(8),
                                      child: coverPath == null
                                          ? const _BookPlaceholder()
                                          : Image.file(
                                              File(coverPath),
                                              fit: BoxFit.cover,
                                              errorBuilder: (_, _, _) =>
                                                  const _BookPlaceholder(),
                                            ),
                                    ),
                                  ),
                                  title: Text(
                                    book.metadata['source_name'] as String? ??
                                        'Sprachtrainer book',
                                  ),
                                  subtitle: Text(
                                    '${book.segments.length} sentences · '
                                    '${_formatAudioMinutes(book.durationMs)}',
                                  ),
                                  onTap: () => _run(() => _openBook(book)),
                                ),
                              );
                            }
                            return _sentenceTile(_activeBook!, index);
                          },
                        ),
                ),
                if (_error != null)
                  Positioned(
                    left: 8,
                    right: 8,
                    bottom: 8,
                    child: GestureDetector(
                      onTap: () => setState(() => _error = null),
                      child: Container(
                        constraints: const BoxConstraints(maxHeight: 56),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.black.withValues(alpha: 0.65),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _error!,
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white70,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        if (_activeBook != null) SafeArea(top: false, child: _playerControls()),
      ],
    ),
  );

  Widget _playerControls() => StreamBuilder<PlayerState>(
    stream: _player.onPlayerStateChanged,
    builder: (context, snapshot) {
      final playing = (snapshot.data ?? _player.state) == PlayerState.playing;
      final totalDurationMs = _durationMs > 0
          ? _durationMs
          : _activeBook?.durationMs ?? 0;
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(_formatAudioTime(_positionMs)),
                Text(_formatAudioTime(totalDurationMs)),
              ],
            ),
          ),
          Slider(
            min: 0,
            max: max(1.0, totalDurationMs.toDouble()),
            value: _positionMs.clamp(0, max(1, totalDurationMs)).toDouble(),
            onChanged: (value) => setState(() => _positionMs = value.round()),
            onChangeEnd: (value) => _run(() => _seekToPosition(value.round())),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Tooltip(
                message: 'Pause after sentences with unknown words',
                child: Switch(
                  value: _autoPause,
                  onChanged: (value) => setState(() => _autoPause = value),
                ),
              ),
              IconButton(
                tooltip: 'Previous sentence',
                onPressed: () => _run(_previousSentence),
                icon: const Icon(Icons.skip_previous),
              ),
              IconButton(
                tooltip: 'Repeat sentence',
                onPressed: () => _run(_replaySentence),
                icon: const Icon(Icons.replay),
              ),
              IconButton.filled(
                tooltip: playing ? 'Pause' : 'Play',
                onPressed: () => _run(() async {
                  if (playing) {
                    await _player.pause();
                    await _saveProgress();
                    await _syncState();
                  } else {
                    unawaited(
                      _player.resume().catchError((Object error) {
                        if (mounted) setState(() => _error = '$error');
                      }),
                    );
                  }
                }),
                icon: Icon(playing ? Icons.pause : Icons.play_arrow),
              ),
              IconButton(
                tooltip: 'Next sentence',
                onPressed: () => _run(_nextSentence),
                icon: const Icon(Icons.skip_next),
              ),
            ],
          ),
        ],
      );
    },
  );

  void _followSentence(String id, int index) {
    if (_followedSentence == id) return;
    _followedSentence = id;
    _activeSentenceKey = GlobalKey();
    _tryFollowSentence(id, index, 0);
  }

  void _tryFollowSentence(String id, int index, int attempt) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          _followedSentence != id ||
          _activeBook == null ||
          index >= _activeBook!.segments.length) {
        return;
      }
      final context = _activeSentenceKey.currentContext;
      if (context != null) {
        unawaited(
          Scrollable.ensureVisible(
            context,
            alignment: 0,
            duration: const Duration(milliseconds: 300),
          ),
        );
      } else if (_listController.hasClients) {
        final itemCount = _activeBook!.segments.length;
        final maxScroll = _listController.position.maxScrollExtent;
        final estimatedOffset = itemCount <= 1
            ? 0.0
            : maxScroll * index / (itemCount - 1);
        _listController.jumpTo(estimatedOffset.clamp(0, maxScroll).toDouble());
        if (attempt < 5) _tryFollowSentence(id, index, attempt + 1);
      }
    });
  }

  Widget _sentenceTile(Book book, int index) {
    final segment = book.segments[index] as Map<String, dynamic>;
    final activeIndex =
        _navigationTargetIndex ?? book.sentenceIndexAt(_positionMs);
    final active = activeIndex == index;
    final tokens = segment['tokens'] as List;
    final wordTokenIndices = <int>[
      for (var tokenIndex = 0; tokenIndex < tokens.length; tokenIndex++)
        if ((tokens[tokenIndex]['rein'] as String).isNotEmpty) tokenIndex,
    ];
    final activeTokenIndex = active
        ? book.wordTokenIndexAt(index, _positionMs)
        : null;
    final original = tokens.map((token) => token['roh'] as String).join();
    final translations = book.translations.cast<Map>().where(
      (item) => item['original'] == original.trim(),
    );
    final locale = Localizations.localeOf(context).languageCode;
    final matchingTranslations = translations.toList();
    final selectedTranslation = matchingTranslations.where(
      (item) => item['language'] == locale,
    );
    final translationText = selectedTranslation.isNotEmpty
        ? selectedTranslation.first['text'] as String
        : matchingTranslations.isNotEmpty
        ? matchingTranslations.first['text'] as String
        : null;
    final selectedTokenIndex = _previewSentenceIndex == index
        ? _previewTokenIndex
        : null;
    final translationTokenIndex =
        selectedTokenIndex ?? (active ? activeTokenIndex : null);
    if (active) _followSentence('${book.id}:$index', index);
    return Card(
      key: active ? _activeSentenceKey : null,
      color: active ? Theme.of(context).colorScheme.secondaryContainer : null,
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: InkWell(
        onTap: () => _run(() => _seekToSentence(index)),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                children: [
                  for (
                    var tokenIndex = 0;
                    tokenIndex < tokens.length;
                    tokenIndex++
                  )
                    Builder(
                      builder: (context) {
                        final token = tokens[tokenIndex];
                        final word = (token['rein'] as String).toLowerCase();
                        final highlighted = activeTokenIndex == tokenIndex;
                        return GestureDetector(
                          onTap: word.isEmpty
                              ? null
                              : () {
                                  _selectWord(word, index, tokenIndex);
                                  if (!active) {
                                    _run(() => _seekToSentence(index));
                                  }
                                },
                          onDoubleTap: word.isEmpty
                              ? null
                              : () {
                                  _selectWord(word, index, tokenIndex);
                                  _run(() => _markWord(word));
                                },
                          behavior: HitTestBehavior.opaque,
                          child: Text(
                            token['roh'] as String,
                            style: TextStyle(
                              fontSize: 18,
                              fontWeight: highlighted
                                  ? FontWeight.w700
                                  : FontWeight.normal,
                              color: highlighted
                                  ? Colors.white
                                  : word.isNotEmpty &&
                                        !_knownWords.contains(word)
                                  ? Colors.deepOrange.shade700
                                  : null,
                              backgroundColor: highlighted
                                  ? const Color(0xff20a89e)
                                  : null,
                            ),
                          ),
                        );
                      },
                    ),
                ],
              ),
              if (translationText != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text.rich(
                    _translationSpan(
                      translationText,
                      tokens,
                      wordTokenIndices,
                      translationTokenIndex,
                    ),
                  ),
                )
              else
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text(
                    'Translation is not included in this book.',
                    style: TextStyle(fontStyle: FontStyle.italic),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  void _selectWord(String word, int sentenceIndex, int tokenIndex) {
    setState(() {
      _previewWord = word;
      _previewSentenceIndex = sentenceIndex;
      _previewTokenIndex = tokenIndex;
    });
  }

  String? _activeWord(Book book) {
    final sentenceIndex =
        _navigationTargetIndex ?? book.sentenceIndexAt(_positionMs);
    final segment = sentenceIndex < 0 ? null : book.segments[sentenceIndex];
    if (segment == null) return null;
    final tokens = (segment as Map<String, dynamic>)['tokens'] as List;
    final tokenIndex = book.wordTokenIndexAt(sentenceIndex, _positionMs);
    if (tokenIndex == null) return null;
    final word = (tokens[tokenIndex]['rein'] as String).toLowerCase();
    return word.isEmpty ? null : word;
  }

  Widget _imageStrip(Book book) {
    final word = _previewWord ?? _activeWord(book);
    final plain = word?.replaceAll(RegExp(r'[^\w-]'), '_');
    final files = <String>[
      if (word != null && plain!.length > 2)
        for (final asset in book.assets)
          if ((asset.toString().endsWith('.jpg') ||
                  asset.toString().endsWith('.png')) &&
              asset
                  .toString()
                  .split('/')
                  .last
                  .toLowerCase()
                  .startsWith('${plain}_context'))
            asset as String,
    ];
    return SizedBox(
      height: 150,
      child: Row(
        children: [
          Expanded(
            child: files.isEmpty
                ? Center(
                    child: Text(
                      word == null ? '' : 'No bundled image for “$word”.',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  )
                : ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.all(8),
                    children: [
                      for (final asset in files)
                        Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: Image.file(
                              File('${book.root.path}/$asset'),
                              height: 134,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) =>
                                  const SizedBox.shrink(),
                            ),
                          ),
                        ),
                    ],
                  ),
          ),
          if (word != null && !_knownWords.contains(word))
            IconButton(
              tooltip: 'Mark “$word” as known',
              onPressed: () => _run(() => _markWord(word)),
              icon: const Icon(Icons.check_circle_outline),
            ),
        ],
      ),
    );
  }
}
