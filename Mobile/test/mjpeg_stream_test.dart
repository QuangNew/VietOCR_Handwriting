import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/mjpeg_stream.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';

const mime = 'multipart/x-mixed-replace; boundary="vietocr-frame"';
final jpeg = Uint8List.fromList([
  255,
  216,
  ...ascii.encode('sample--vietocr-frame\r\n\r\n'),
  255,
  217,
]);
List<int> part(List<int> frame) => [
  ...ascii.encode(
    '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n',
  ),
  ...frame,
  13,
  10,
];

void main() {
  test(
    'separate flushed preamble and multipart CRLF do not create empty headers',
    () {
      final parser = MjpegParser(mime);
      expect(parser.add([13, 10]), isEmpty);
      expect(parser.add([13, 10, ...part(jpeg)]), [jpeg]);
    },
  );
  test(
    'native high quality frames larger than 128 KiB remain supported and bounded',
    () {
      final large = Uint8List.fromList([
        255,
        216,
        ...List.filled(900 * 1024, 120),
        255,
        217,
      ]);
      final wire = part(large), parser = MjpegParser(mime);
      final frames = <Uint8List>[];
      for (var at = 0; at < wire.length; at += 16384) {
        frames.addAll(
          parser.add(wire.sublist(at, (at + 16384).clamp(0, wire.length))),
        );
      }
      expect(frames, [large]);
    },
  );
  test(
    'multipart frames survive every split point and embedded boundaries',
    () {
      final wire = [13, 10, ...part(jpeg), ...part(jpeg)];
      for (var split = 1; split < wire.length; ++split) {
        final parser = MjpegParser(mime);
        expect(
          [
            ...parser.add(wire.sublist(0, split)),
            ...parser.add(wire.sublist(split)),
          ],
          [jpeg, jpeg],
        );
      }
      final parser = MjpegParser(mime);
      expect(
        [
          for (final byte in wire) ...parser.add([byte]),
        ],
        [jpeg, jpeg],
      );
    },
  );

  test('coalesced frames are parsed incrementally without growing a queue', () {
    final parser = MjpegParser(mime);
    expect(
      parser.add([for (var i = 0; i < 2000; ++i) ...part(jpeg)]).length,
      2000,
    );
  });

  test('invalid content types, huge headers and invalid JPEGs are bounded', () {
    for (final type in [
      'image/jpeg',
      'multipart/x-mixed-replace',
      'multipart/x-mixed-replace; boundary=${'a' * 71}',
    ]) {
      expect(() => MjpegParser(type), throwsFormatException);
    }
    for (final wire in [
      List.filled(MjpegParser.maxHeader + 1, 65),
      part(ascii.encode('not jpeg')),
      ascii.encode(
        '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${MjpegParser.maxFrame + 1}\r\n\r\n',
      ),
      ascii.encode('--vietocr-frame\r\nContent-Type: image/jpeg\r\n\r\n'),
      ascii.encode(
        '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\nContent-Length: 4\r\n\r\n',
      ),
    ]) {
      expect(() => MjpegParser(mime).add(wire).toList(), throwsFormatException);
    }
  });

  test(
    'live chunked HTTP delivers frames before response end and permits cancel/reopen',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final release = Completer<void>();
      var requests = 0;
      server.listen((request) async {
        requests++;
        expect(request.uri.path, '/stream');
        expect(
          request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer ${'a' * 32}',
        );
        request.response.headers.set(HttpHeaders.contentTypeHeader, mime);
        request.response.bufferOutput = false;
        try {
          final wire = [13, 10, ...part(jpeg), ...part(jpeg)];
          for (var at = 0; at < wire.length; at += 7) {
            request.response.add(
              wire.sublist(at, (at + 7).clamp(0, wire.length)),
            );
          }
          await request.response.flush();
          await release.future;
          await request.response.close();
        } on IOException {
          // Closing the viewer deliberately aborts the unfinished HTTP response.
        }
      });
      final endpoint = WifiEndpoint('127.0.0.1', 'a' * 32);
      final first = MjpegConnection(endpoint, port: server.port);
      final second = MjpegConnection(endpoint, port: server.port);
      try {
        expect(
          await first
              .frames()
              .take(2)
              .toList()
              .timeout(const Duration(seconds: 2)),
          [jpeg, jpeg],
        );
        expect(release.isCompleted, isFalse);
        expect(
          await second.frames().first.timeout(const Duration(seconds: 2)),
          jpeg,
        );
        expect(requests, 2);
      } finally {
        first.close();
        second.close();
        release.complete();
        await server.close(force: true);
      }
    },
  );

  test(
    'stop interrupts an idle stream without waiting for its HTTP timeout',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final release = Completer<void>(), started = Completer<void>();
      server.listen((request) async {
        request.response.headers.set(HttpHeaders.contentTypeHeader, mime);
        request.response.bufferOutput = false;
        request.response.add(part(jpeg));
        await request.response.flush();
        await release.future;
        try {
          await request.response.close();
        } on IOException {
          /* cancelled */
        }
      });
      final connection = MjpegConnection(
        WifiEndpoint('127.0.0.1', 'a' * 32),
        port: server.port,
      );
      final done = Completer<void>();
      final subscription = connection.frames().listen(
        (_) {
          if (!started.isCompleted) started.complete();
        },
        onDone: done.complete,
        onError: (Object error) {
          if (!done.isCompleted) done.completeError(error);
        },
      );
      try {
        await started.future.timeout(const Duration(seconds: 2));
        final watch = Stopwatch()..start();
        connection.close();
        await done.future.timeout(const Duration(seconds: 1));
        expect(watch.elapsedMilliseconds, lessThan(1000));
      } finally {
        connection.close();
        await subscription.cancel();
        release.complete();
        await server.close(force: true);
      }
    },
  );

  test(
    'old firmware reports an upgrade instead of repeatedly retrying',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      var requests = 0;
      server.listen((request) async {
        requests++;
        request.response.statusCode = 404;
        await request.response.close();
      });
      final connection = MjpegConnection(
        WifiEndpoint('127.0.0.1', 'a' * 32),
        port: server.port,
      );
      try {
        await expectLater(
          connection.frames().toList(),
          throwsA(
            isA<StateError>().having(
              (e) => e.message,
              'message',
              contains('2.4.1-native'),
            ),
          ),
        );
        expect(requests, 1);
      } finally {
        connection.close();
        await server.close(force: true);
      }
    },
  );
}
