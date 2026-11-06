import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';

void main() {
  test(
    'interrupted TCP photo resumes the same ID with monotonic progress',
    () async {
      final jpeg = Uint8List.fromList([
        255,
        216,
        ...List.generate(500000, (i) => i % 256),
        255,
        217,
      ]);
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final offsets = <int>[], paths = <String>[], progress = <double>[];
      server.listen((request) async {
        final bounds = request.headers
            .value(HttpHeaders.rangeHeader)!
            .substring(6)
            .split('-')
            .map(int.parse)
            .toList();
        final first = bounds[0], last = bounds[1].clamp(0, jpeg.length - 1);
        offsets.add(first);
        paths.add(request.uri.toString());
        expect(
          request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer ${'a' * 32}',
        );
        final response = request.response;
        response.statusCode = 206;
        response.headers.contentType = ContentType('image', 'jpeg');
        response.headers.set(
          HttpHeaders.contentRangeHeader,
          'bytes $first-$last/${jpeg.length}',
        );
        response.headers.set(HttpHeaders.etagHeader, '"photo-42-crc"');
        response.contentLength = last - first + 1;
        if (offsets.length == 1) {
          final socket = await response.detachSocket();
          socket.add(jpeg.sublist(0, 30000));
          await socket.flush();
          socket.destroy();
        } else {
          response.add(jpeg.sublist(first, last + 1));
          await response.close();
        }
      });
      try {
        final actual = await fetchCameraJpeg(
          WifiEndpoint('127.0.0.1:${server.port}', 'a' * 32),
          '/image?id=42',
          progress: progress.add,
        );
        expect(actual, jpeg);
        expect(offsets[1], 30000);
        expect(paths.every((path) => path == '/image?id=42'), true);
        expect(progress.last, 1);
        expect(progress, [...progress]..sort());
      } finally {
        await server.close(force: true);
      }
    },
  );
}
