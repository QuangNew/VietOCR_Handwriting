import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/app_controller.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/ocr/cancellation.dart';
import 'package:vietocr_mobile/ocr/engine.dart';
import 'package:vietocr_mobile/ocr/remote_engine.dart';
import 'package:vietocr_mobile/services/gateway_client.dart';
import 'package:vietocr_mobile/services/session_store.dart';

class RecoveringEngine implements OcrEngine, AcceptedResultRecovery {
  int sends = 0, reads = 0;
  @override
  bool get loaded => true;
  @override
  Future<void> close() async {}
  @override
  Future<String> recognize(
    String path, {
    required bool split,
    bool correct = false,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async {
    sends++;
    return 'sent';
  }

  @override
  Future<({String state, String text, String error})?> recoverAccepted(
    String path, {
    required int rotation,
  }) async {
    reads++;
    return path.contains('accepted')
        ? (state: 'succeeded', text: 'Recovered result', error: '')
        : null;
  }
}

class NativeFixtureHttp extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) =>
      super.createHttpClient(context)..findProxy = (_) => 'DIRECT';
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    HttpOverrides.global = NativeFixtureHttp();
  });
  tearDown(() {
    HttpOverrides.global = null;
  });
  test(
    'explicit retry replaces a failed intent and capacity waits upload only once',
    () async {
      final root = await Directory.systemTemp.createTemp(
        'vietocr-deferred-upload-',
      );
      final image = File('${root.path}/image.jpg');
      await File(
        '../../shared/contracts/fixtures/images/test.jpg',
      ).copy(image.path);
      final expected = await image.readAsBytes();
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final origin = 'http://127.0.0.1:${server.port}';
      const id = '10000000-0000-4000-8000-000000000001';
      const failed = '10000000-0000-4000-8000-000000000002';
      final hash = sha256.convert(expected).toString();
      final requests = <String>[];
      await File('${image.path}.ocr-v2.json').writeAsString(
        jsonEncode({
          'requestId': failed,
          'sha256': hash,
          'layout': 'auto',
          'gateway': origin,
          'jobId': failed,
          'accepted': true,
        }),
      );
      var grants = 0, uploads = 0, commits = 0;
      final listener = server.listen((r) async {
        final bytes = await r.fold<List<int>>(
          [],
          (all, next) => all..addAll(next),
        );
        dynamic value;
        switch (r.uri.path) {
          case '/api/v2/session':
            value = {'resultsOrigin': origin, 'account': {}};
          case '/api/v2/intents':
            final payload = jsonDecode(utf8.decode(bytes)) as Map;
            requests.add(payload['requestId'] as String);
            value = requests.last == failed
                ? {'id': failed, 'state': 'failed'}
                : {'id': id, 'state': 'awaiting_upload'};
          case '/api/v2/intents/$id/grant':
            grants++;
            if (grants < 3) {
              r.response.statusCode = grants == 1 ? 503 : 429;
              r.response.headers.set('Retry-After', '1');
              value = {
                'error': grants == 1 ? 'server_not_ready' : 'minute_quota',
              };
            } else {
              value = {'generation': 1, 'offset': 0};
            }
          case '/api/v2/intents/$id/content':
            uploads++;
            expect(bytes, expected);
            value = {'offset': bytes.length};
          case '/api/v2/intents/$id/complete':
            commits++;
            value = {'accepted': true};
          case '/api/v2/intents/$id/result-ticket':
            value = {
              'resultUrl': '$origin/api/v2/results/$id',
              'ticket': 'fixture-ticket',
              'expiresIn': 300,
            };
          case '/api/v2/results/$id':
            value = {'state': 'succeeded', 'text': 'fixture text'};
          default:
            throw StateError('Unexpected route');
        }
        r.response.headers.contentType = ContentType.json;
        r.response.write(jsonEncode(value));
        await r.response.close();
      });
      final client = VietOcrRemote(origin, 'fixture-session');
      try {
        expect(await client.recognize(image), 'fixture text');
        expect(requests, hasLength(2));
        expect(requests.first, failed);
        expect(requests.last, isNot(failed));
        expect(grants, 3);
        expect(uploads, 1);
        expect(commits, 1);
      } finally {
        client.close();
        await listener.cancel();
        await server.close(force: true);
        await root.delete(recursive: true);
      }
    },
  );
  test(
    'a valid result ticket reads compute while Pi is offline and is not reused after account change',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final origin = 'http://127.0.0.1:${server.port}';
      const id = '10000000-0000-4000-8000-000000000001';
      var offline = false, mints = 0, reads = 0, token = 'account-a';
      final listener = server.listen((r) async {
        await r.drain<void>();
        r.response.headers.contentType = ContentType.json;
        dynamic value;
        if (r.uri.path == '/api/v2/results/$id') {
          reads++;
          expect(r.headers.value('authorization'), 'Bearer ticket-a');
          value = {'state': 'succeeded', 'text': 'fixture'};
        } else if (offline) {
          r.response.statusCode = 503;
          value = {'error': 'pi_offline'};
        } else if (r.uri.path == '/api/v2/session') {
          value = {'resultsOrigin': origin, 'account': {}};
        } else if (r.uri.path.endsWith('/result-ticket')) {
          mints++;
          value = {
            'resultUrl': '$origin/api/v2/results/$id',
            'ticket': 'ticket-a',
            'expiresIn': 300,
          };
        } else {
          r.response.statusCode = 404;
          value = {'error': 'unexpected_route'};
        }
        r.response.write(jsonEncode(value));
        await r.response.close();
      });
      final client = VietOcrRemote(
        origin,
        '',
        tokenProvider: () async => token,
      );
      try {
        expect((await client.get(id))['text'], 'fixture');
        offline = true;
        expect((await client.get(id))['state'], 'succeeded');
        expect(mints, 1);
        expect(reads, 2);
        token = 'account-b';
        await expectLater(client.get(id), throwsA(isA<RemoteOcrException>()));
        expect(reads, 2);
      } finally {
        client.close();
        await listener.cancel();
        await server.close(force: true);
      }
    },
  );
  test(
    'restart recovers an accepted job read-only, including a lost acceptance acknowledgement',
    () async {
      final root = await Directory.systemTemp.createTemp('vietocr-recovery-');
      final image = File('${root.path}/image.jpg');
      await image.writeAsBytes([255, 216, ...List.filled(30, 0)]);
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final origin = 'http://127.0.0.1:${server.port}';
      const id = '10000000-0000-4000-8000-000000000001';
      final methods = <String>[];
      final listener = server.listen((r) async {
        await r.drain<void>();
        methods.add('${r.method} ${r.uri.path}');
        r.response.headers.contentType = ContentType.json;
        final value = switch (r.uri.path) {
          '/api/v2/intents/$id' => {'id': id, 'state': 'queued'},
          '/api/v2/session' => {'resultsOrigin': origin, 'account': {}},
          '/api/v2/intents/$id/result-ticket' => {
            'resultUrl': '$origin/api/v2/results/$id',
            'ticket': 'fixture',
            'expiresIn': 300,
          },
          '/api/v2/results/$id' => {
            'state': 'succeeded',
            'text': 'Recovered text',
          },
          _ => throw StateError('Unexpected upload: ${r.method} ${r.uri.path}'),
        };
        r.response.write(jsonEncode(value));
        await r.response.close();
      });
      final engine = RemoteEngine(origin, 'fixture');
      try {
        // No accepted flag: the app died immediately after server commit.
        await File('${image.path}.ocr-v2.json').writeAsString(
          jsonEncode({
            'gateway': origin,
            'jobId': id,
            'sha256': sha256.convert(await image.readAsBytes()).toString(),
          }),
        );
        final result = await engine.recoverAccepted(image.path, rotation: 0);
        expect(result?.text, 'Recovered text');
        expect(
          methods.where(
            (m) =>
                m.startsWith('PUT') ||
                m == 'POST /api/v2/intents' ||
                m.endsWith('/grant') ||
                m.endsWith('/complete'),
          ),
          isEmpty,
        );
      } finally {
        await engine.close();
        await listener.cancel();
        await server.close(force: true);
        await root.delete(recursive: true);
      }
    },
  );
  test('queued session writes keep their original account directory', () async {
    final root = await Directory.systemTemp.createTemp('vietocr-save-owner-');
    final store = SessionStore(directory: root);
    try {
      store.setAccount('aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa');
      final folder = await store.directory;
      await folder.create(recursive: true);
      final file = File('${folder.path}/a.png');
      await file.writeAsBytes([1, 2, 3]);
      final pending = store.save([
        Document(id: 'a', path: file.path, name: 'a.png'),
      ]);
      store.setAccount('bbbbbbbb-2222-4444-8888-bbbbbbbbbbbb');
      await pending;
      expect(await store.load(), isEmpty);
      store.setAccount('aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa');
      expect((await store.load()).single.id, 'a');
    } finally {
      await root.delete(recursive: true);
    }
  });
  test(
    'opening a workspace restores accepted text without submitting new drafts',
    () async {
      SharedPreferences.setMockInitialValues({});
      final root = await Directory.systemTemp.createTemp(
        'vietocr-controller-recovery-',
      );
      final store = SessionStore(directory: root);
      final engine = RecoveringEngine();
      final folder = await store.directory;
      await folder.create(recursive: true);
      final accepted = File('${folder.path}/accepted.png'),
          draft = File('${folder.path}/draft.png');
      final bytes = img.encodePng(img.Image(width: 8, height: 8));
      await accepted.writeAsBytes(bytes);
      await draft.writeAsBytes(bytes);
      await store.save([
        Document(
          id: 'accepted',
          path: accepted.path,
          name: 'accepted.png',
          status: DocumentStatus.processing,
        ),
        Document(id: 'draft', path: draft.path, name: 'draft.png'),
      ]);
      final app = AppController(store: store, engine: engine);
      try {
        await app.initialize(recoverLost: false);
        await Future<void>.delayed(const Duration(milliseconds: 30));
        await app.recoverAcceptedResults();
        expect(app.documents.first.text, 'Recovered result');
        expect(app.documents.first.status, DocumentStatus.done);
        expect(app.documents.last.status, DocumentStatus.ready);
        expect(engine.sends, 0);
      } finally {
        app.dispose();
        await root.delete(recursive: true);
      }
    },
  );
}
