import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/camera_transfer.dart';
import 'package:vietocr_mobile/services/udp_camera.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';

List<Uint8List> packets(Uint8List jpeg, {int sequence = 10, int stream = 42}) =>
    [
      for (var at = 0; at < jpeg.length; at += 1168)
        packet(jpeg, at, sequence, stream),
    ];
Uint8List packet(Uint8List jpeg, int at, int sequence, int stream) {
  final count = (jpeg.length - at).clamp(0, 1168),
      bytes = Uint8List(32 + count);
  bytes.setRange(0, 4, ascii.encode('VOJ1'));
  final header = ByteData.sublistView(bytes);
  header.setUint32(4, stream, Endian.little);
  header.setUint32(8, sequence, Endian.little);
  header.setUint32(12, jpeg.length, Endian.little);
  header.setUint32(16, at, Endian.little);
  header.setUint32(20, cameraCrc32(jpeg), Endian.little);
  header.setUint16(24, 640, Endian.little);
  header.setUint16(26, 480, Endian.little);
  header.setUint16(28, count, Endian.little);
  bytes.setRange(32, bytes.length, jpeg, at);
  return bytes;
}

void main() {
  final jpeg = Uint8List.fromList([
    255,
    216,
    ...List<int>.filled(10007, 65),
    255,
    217,
  ]);
  test(
    'reordered, duplicate, stale, corrupt and oversized UDP packets stay bounded',
    () {
      final parts = packets(jpeg), decoder = UdpJpegAssembler(42);
      expect(decoder.add(parts.last), isNull);
      expect(decoder.add(parts.last), isNull);
      for (final part in parts.skip(1).take(parts.length - 2)) {
        expect(decoder.add(part), isNull);
      }
      expect(decoder.add(parts.first), jpeg);
      for (final part in parts) {
        expect(decoder.add(part), isNull);
      }
      for (var seq = 11; seq < 100; seq++) {
        decoder.add(packets(jpeg, sequence: seq).first);
        expect(decoder.pendingFrames, lessThanOrEqualTo(2));
      }
      expect(decoder.add(Uint8List(1201)), isNull);
      expect(
        decoder.add(packets(jpeg, sequence: 501, stream: 99).first),
        isNull,
      );
      final bad = packets(jpeg, sequence: 500);
      bad.last[bad.last.length - 1] ^= 1;
      for (final part in bad) {
        expect(decoder.add(part), isNull);
      }
      expect(decoder.corrupt, 1);
      expect(
        cameraCrc32(Uint8List.fromList(ascii.encode('123456789'))),
        0xcbf43926,
      );
    },
  );
  test(
    'real UDP/HTTP renews, stops and reopens without a late stop request',
    () async {
      final udp = await RawDatagramSocket.bind(InternetAddress.loopbackIPv4, 0);
      final datagrams = udp.listen((event) {
        if (event == RawSocketEvent.read) {
          while (udp.receive() != null) {}
        }
      });
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      var stream = 0, sequence = 0;
      InternetAddress? peer;
      int? port;
      final calls = <int>[];
      final pending = <Uint8List>[];
      final requests = server.listen((request) async {
        expect(request.uri.path, '/stream/udp');
        expect(request.headers.value('Authorization'), 'Bearer ${'a' * 32}');
        final body = jsonDecode(await utf8.decoder.bind(request).join()) as Map;
        port = body['port'] as int;
        peer = request.connectionInfo!.remoteAddress;
        calls.add(port!);
        pending.clear();
        expect(port, isNot(0));
        request.response.write(
          jsonEncode({
            'active': true,
            'stream': ++stream,
            'header_bytes': 32,
            'datagram_bytes': 1200,
            'lease_seconds': 60,
          }),
        );
        await request.response.close();
      });
      // Dart's nonblocking Windows UDP sender can return 0 during a burst.
      // Pace fragments and retry unsent packets, like the firmware's sender.
      final timer = Timer.periodic(const Duration(milliseconds: 2), (_) {
        if (peer != null && port != null) {
          if (pending.isEmpty) {
            pending.addAll(
              packets(jpeg, sequence: ++sequence, stream: stream).reversed,
            );
          }
          if (udp.send(pending.first, peer!, port!) == pending.first.length) {
            pending.removeAt(0);
          }
        }
      });
      final endpoint = WifiEndpoint('127.0.0.1:${server.port}', 'a' * 32);
      final connection = UdpCameraConnection(
        endpoint,
        sourcePort: udp.port,
        renewAfter: const Duration(milliseconds: 150),
      );
      StreamSubscription<Uint8List>? subscription;
      final first = Completer<void>();
      var received = 0;
      try {
        subscription = connection.frames().listen(
          (frame) {
            expect(frame, jpeg);
            received++;
            if (!first.isCompleted) first.complete();
          },
          onError: (Object error, StackTrace stack) {
            if (!first.isCompleted) first.completeError(error, stack);
          },
        );
        await first.future.timeout(
          const Duration(seconds: 3),
          onTimeout: () => throw TimeoutException(
            'No first UDP JPEG: HTTP calls=${calls.length}, sent=$sequence',
          ),
        );
        await Future<void>.delayed(const Duration(milliseconds: 400));
        expect(calls.length, greaterThan(1));
        expect(received, greaterThan(2));
        connection.close();
        await subscription.cancel();
        subscription = null;
        final next = UdpCameraConnection(endpoint, sourcePort: udp.port);
        try {
          final frame = await next.frames().first.timeout(
            const Duration(seconds: 3),
          );
          expect(frame, jpeg);
          connection.close();
        } finally {
          next.close();
        }
        expect(calls.every((port) => port != 0), isTrue);
      } finally {
        connection.close();
        await subscription?.cancel();
        timer.cancel();
        udp.close();
        await datagrams.cancel();
        await requests.cancel();
        await server.close(force: true);
      }
    },
  );
  test('closing before subscription never opens network resources', () async {
    final connection = UdpCameraConnection(WifiEndpoint('127.0.0.1', 'a' * 32))
      ..close();
    expect(await connection.frames().toList(), isEmpty);
  });
}
