import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';
import 'package:vietocr_mobile/services/camera_transfer.dart';

void main() {
  test(
    'Wi-Fi state distinguishes saved, joining, ready and offline without secrets',
    () {
      final name = hexBytes([78, 104, 97]);
      final ready = WifiState.parse(
        'WIFI STATUS READY 192.168.100.173 ${'a' * 32} $name',
        'WIFI SAVED 1 $name',
      );
      expect(ready.summary, contains('192.168.100.173'));
      expect(ready.summary, contains('Nha'));
      expect(ready.detail, contains('Tự kết nối'));
      final joining = WifiState.parse(
        'WIFI STATUS JOINING 6 202',
        'WIFI SAVED 1 $name',
      );
      expect(joining.summary, contains('đang kết nối'));
      expect(joining.detail, isNot(contains('Xác thực')));
      final offline = WifiState.parse(
        'WIFI STATUS OFFLINE 4 202',
        'WIFI SAVED 1 $name',
      );
      expect(offline.detail, contains('tự thử lại'));
      expect(offline.detail, contains('Xác thực'));
      expect(
        WifiState.parse('WIFI STATUS OFFLINE 6', 'WIFI SAVED 0 -').summary,
        contains('chưa được cấu hình'),
      );
    },
  );
  test(
    'unreachable HTTP is reported before taking a photo and never starts BLE transfer',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final commands = <String>[];
      server.listen((request) async {
        expect(request.uri.path, '/health');
        request.response.statusCode = 503;
        await request.response.close();
      });
      try {
        await expectLater(
          captureWifiPhoto(
            id: 42,
            endpoint: WifiEndpoint('127.0.0.1:${server.port}', 'a' * 32),
            request: (command, _) async {
              commands.add(command);
              return 'OK $command';
            },
            checkConnected: () {},
            checksum: (bytes) async => cameraCrc32(bytes),
          ),
          throwsStateError,
        );
        expect(commands, isEmpty);
      } finally {
        await server.close(force: true);
      }
    },
  );
  test(
    'UTF8 credentials fit the 80 byte BLE line receiver including maximum password',
    () {
      final commands = wifiCommands('Wi-Fi Việt', 'a' * 63);
      expect(commands, hasLength(5));
      expect(commands.every((line) => line.length + 1 <= 80), isTrue);
      expect(wifiName(commands.first.split(' ').last), 'Wi-Fi Việt');
      expect(() => wifiCommands('', '12345678'), throwsArgumentError);
      expect(() => wifiCommands('Wi-Fi', 'short'), throwsArgumentError);
      expect(() => wifiCommands('x' * 33, ''), throwsArgumentError);
      expect(wifiCommands('Open', ''), hasLength(2));
      expect(
        () => WifiEndpoint.parse('WIFI STATUS READY 8.8.8.8 ${'a' * 32} 61'),
        throwsFormatException,
      );
    },
  );

  test(
    'Wi-Fi capture verifies CRC, sends auth outside URL, releases after invalid image',
    () async {
      final token = 'a' * 32;
      final bytes = Uint8List.fromList([
        255,
        216,
        ...List.filled(1000, 25),
        255,
        217,
      ]);
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      var corrupt = false, requests = 0;
      server.listen((request) async {
        expect(
          request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer $token',
        );
        if (request.uri.path == '/health') {
          request.response.headers.contentType = ContentType.json;
          request.response.write(
            '{"http":true,"ip":"127.0.0.1:${server.port}"}',
          );
          await request.response.close();
          return;
        }
        expect(request.uri.toString(), '/image?id=42');
        requests++;
        request.response.headers.contentType = ContentType('image', 'jpeg');
        request.response.contentLength = bytes.length;
        final data = Uint8List.fromList(bytes);
        if (corrupt) data[10] = 9;
        request.response.add(data);
        await request.response.close();
      });
      final commands = <String>[];
      Future<String> request(String line, String? prefix) async {
        commands.add(line);
        return line.startsWith('CAM META')
            ? 'CAM 42 ${bytes.length} ${cameraCrc32(bytes).toRadixString(16)} 2048 1536'
            : 'OK $line';
      }

      Future<CameraPhoto> capture() => captureWifiPhoto(
        id: 42,
        endpoint: WifiEndpoint('127.0.0.1:${server.port}', token),
        request: request,
        checkConnected: () {},
        checksum: (data) async => cameraCrc32(data),
      );
      try {
        final photo = await capture();
        expect(photo.metadata.width, 2048);
        expect(photo.metadata.height, 1536);
        expect(photo.bytes, bytes);
        corrupt = true;
        await expectLater(capture(), throwsFormatException);
        expect(commands.where((line) => line == 'CAM SHOT 42'), hasLength(2));
        expect(
          commands.where((line) => line == 'CAM RELEASE 42'),
          hasLength(2),
        );
        expect(requests, 2);
      } finally {
        await server.close(force: true);
      }
    },
  );
}
