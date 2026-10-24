import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sprachtrainer_mobile/main.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const pathProviderChannel = MethodChannel('plugins.flutter.io/path_provider');
  late Directory documentsDirectory;

  setUp(() async {
    documentsDirectory = await Directory.systemTemp.createTemp(
      'sprachtrainer-test-',
    );
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          pathProviderChannel,
          (_) async => documentsDirectory.path,
        );
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(pathProviderChannel, null);
    await documentsDirectory.delete(recursive: true);
  });

  test('imports audio and metadata from a valid book', () async {
    final bytes = _bookBytes();
    final source = File('${documentsDirectory.path}/sample.stbook');
    await source.writeAsBytes(bytes);

    final book = await importBook(source);

    expect(book.metadata['source_name'], 'sample.mp3');
    expect(await File(book.audioPath).readAsBytes(), [1, 2, 3]);
  });

  test('imports optional word timestamps and audio duration', () async {
    final source = File('${documentsDirectory.path}/timed.stbook');
    await source.writeAsBytes(
      _bookBytes(
        extraMetadata: {
          'word_timestamps': true,
          'duration_ms': 2500,
          'segments': [
            {
              'start': 0,
              'ende': 1,
              'tokens': [
                {'roh': 'Hallo', 'rein': 'hallo', 'start': 0.1, 'ende': 0.5},
              ],
            },
          ],
        },
      ),
    );

    final book = await importBook(source);

    expect(book.hasWordTimestamps, isTrue);
    expect(book.durationMs, 2500);
  });

  test('uses the first bundled image as the library cover', () async {
    final root = Directory('${documentsDirectory.path}/cover');
    final image = File('${root.path}/bilder/cover.jpg');
    await image.parent.create(recursive: true);
    await image.writeAsBytes([1, 2, 3]);
    final book = Book(
      id: 'cover',
      root: root,
      metadata: {
        'segments': [],
        'assets': ['bilder/cover.jpg'],
      },
    );

    expect(book.coverImagePath, image.path);
  });

  test('rejects archive entries with traversal paths', () async {
    final bytes = _bookBytes(
      extraEntries: {
        'bilder/../outside.png': [1],
      },
    );
    final source = File('${documentsDirectory.path}/unsafe.stbook');
    await source.writeAsBytes(bytes);

    await expectLater(importBook(source), throwsFormatException);
  });

  test('selects only the latest sentence at boundaries and during pauses', () {
    final book = Book(
      id: 'timeline',
      root: documentsDirectory,
      metadata: {
        'segments': [
          {'start': 0, 'ende': 1.5, 'tokens': []},
          {'start': 2, 'ende': 3, 'tokens': []},
          {'start': 8, 'ende': 9, 'tokens': []},
        ],
      },
    );

    expect(book.sentenceIndexAt(1999), 0);
    expect(book.sentenceIndexAt(2000), 1);
    expect(book.sentenceIndexAt(7000), 1);
    expect(book.sentenceIndexAt(8000), 2);
  });

  test('weights active word timing by word length like the desktop player', () {
    final book = Book(
      id: 'word-timing',
      root: documentsDirectory,
      metadata: {
        'segments': [
          {
            'start': 0,
            'ende': 4,
            'tokens': [
              {'roh': 'a ', 'rein': 'a'},
              {'roh': 'Komposition ', 'rein': 'Komposition'},
              {'roh': 'ist', 'rein': 'ist'},
            ],
          },
        ],
      },
    );

    expect(book.wordTokenIndexAt(0, 1000), 1);
    expect(book.wordTokenIndexAt(0, 3500), 2);
  });

  test(
    'uses aligned word times instead of overlapping sentence boundaries',
    () {
      final book = Book(
        id: 'aligned-timing',
        root: documentsDirectory,
        metadata: {
          'word_timestamps': true,
          'duration_ms': 4000,
          'segments': [
            {
              'start': 0,
              'ende': 3,
              'tokens': [
                {'roh': 'Anfang ', 'rein': 'Anfang', 'start': 0.1, 'ende': 0.5},
                {'roh': 'Ende', 'rein': 'ende', 'start': 2, 'ende': 3},
              ],
            },
            {
              'start': 2.5,
              'ende': 4,
              'tokens': [
                {'roh': 'Weiter', 'rein': 'weiter', 'start': 3.1, 'ende': 3.8},
              ],
            },
          ],
        },
      );

      expect(book.sentenceIndexAt(2800), 0);
      expect(book.wordTokenIndexAt(0, 2800), 1);
      expect(book.sentenceIndexAt(3100), 1);
      expect(book.wordTokenIndexAt(1, 3100), 0);
      expect(book.durationMs, 4000);
    },
  );

  test('uses available word timings and falls back per untimed sentence', () {
    final book = Book(
      id: 'partially-timed',
      root: documentsDirectory,
      metadata: {
        'word_timestamps': true,
        'segments': [
          {
            'start': 0,
            'ende': 2,
            'tokens': [
              {'roh': 'Hallo ', 'rein': 'hallo', 'start': 0.2, 'ende': 0.8},
              {'roh': 'Welt', 'rein': 'welt', 'start': 1, 'ende': 1.8},
            ],
          },
          {
            'start': 2.5,
            'ende': 4,
            'tokens': [
              {'roh': 'Guten ', 'rein': 'guten'},
              {'roh': 'Morgen', 'rein': 'morgen'},
            ],
          },
        ],
      },
    );

    expect(book.sentenceIndexAt(1200), 0);
    expect(book.wordTokenIndexAt(0, 1200), 1);
    expect(book.sentenceIndexAt(2600), 1);
    expect(book.wordTokenIndexAt(1, 3200), 1);
  });

  test('computes consistent sentence start and end times for navigation', () {
    final book = Book(
      id: 'navigation-timings',
      root: documentsDirectory,
      metadata: {
        'word_timestamps': true,
        'segments': [
          {
            'start': 1.0,
            'ende': 5.0,
            'tokens': [
              {'roh': 'Die ', 'rein': 'die', 'start': 1.2, 'ende': 1.5},
              {'roh': 'Burg', 'rein': 'burg', 'start': 4.0, 'ende': 4.8},
            ],
          },
          {
            'start': 5.0,
            'ende': 9.0,
            'tokens': [
              {'roh': 'Im ', 'rein': 'im', 'start': 5.2, 'ende': 5.5},
              {'roh': 'Wald', 'rein': 'wald', 'start': 8.0, 'ende': 8.9},
            ],
          },
        ],
      },
    );

    expect(book.sentenceStartMs(0), 1200);
    expect(book.sentenceEndMs(0), 4800);
    expect(book.sentenceStartMs(1), 5200);
    expect(book.sentenceEndMs(1), 8900);

    // Boundary behaviors
    expect(book.sentenceIndexAt(1199), -1);
    expect(book.sentenceIndexAt(1200), 0);
    expect(book.sentenceIndexAt(4800), 0);
    expect(book.sentenceIndexAt(5199), 0); // Stays on previous during pause
    expect(book.sentenceIndexAt(5200), 1);
    expect(book.sentenceIndexAt(8900), 1);
    expect(book.sentenceIndexAt(9500), 1);
  });

  test('turns a rejected pairing response into a handled error', () async {
    await expectLater(
      SyncClient.pair(
        DiscoveredComputer(InternetAddress.loopbackIPv4, 43982, 'test'),
        '000000',
        'test-device',
        'Default',
      ),
      throwsA(
        isA<HttpException>().having(
          (error) => error.message,
          'message',
          contains('Pairing failed'),
        ),
      ),
    );
  });
}

Uint8List _bookBytes({
  Map<String, List<int>> extraEntries = const {},
  Map<String, dynamic> extraMetadata = const {},
}) {
  final metadata = utf8.encode(
    jsonEncode({
      'format': 'Sprachtrainer Book',
      'version': 1,
      'source_name': 'sample.mp3',
      'audio': 'audio/sample.mp3',
      'segments': [
        {
          'start': 0,
          'ende': 1,
          'tokens': [
            {'roh': 'Hallo', 'rein': 'hallo'},
          ],
        },
      ],
      'translations': [],
      'assets': [],
      ...extraMetadata,
    }),
  );
  final archive = Archive()
    ..addFile(ArchiveFile('metadata.json', metadata.length, metadata))
    ..addFile(ArchiveFile('audio/sample.mp3', 3, [1, 2, 3]));
  for (final entry in extraEntries.entries) {
    archive.addFile(ArchiveFile(entry.key, entry.value.length, entry.value));
  }
  return Uint8List.fromList(ZipEncoder().encode(archive)!);
}
