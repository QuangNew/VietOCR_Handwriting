import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/services/camera_settings.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';
import 'package:vietocr_mobile/services/ble_assistant.dart';
import 'ble_connection_test.dart' as fixture;

Map<String, Object?> response({
  Map<String, int>? settings,
  int revision = 1,
  int applied = 1,
  bool saved = true,
  String error = '',
}) => {
  'schema': 2,
  'sensor': 'OV5640',
  'firmware': '3.0.0-ov5640',
  'settings': settings ?? cameraDefaults,
  'defaults': cameraDefaults,
  'revision': revision,
  'applied_revision': applied,
  'saved': saved,
  'error': error,
};
Future<void> until(bool Function() predicate) async {
  final deadline = DateTime.now().add(const Duration(seconds: 3));
  while (!predicate()) {
    if (DateTime.now().isAfter(deadline)) fail('Condition timed out');
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  test(
    'lost config response is read back without replaying the POST',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = fixture.FakeRadio()..ready();
      final settings = {...cameraDefaults, 'focus_x': 35};
      var posts = 0, reads = 0;
      final ble = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
        cameraSettingsRequest: (endpoint, values, persist) async {
          if (values != null) {
            posts++;
            throw const CameraNetworkException('response lost');
          }
          reads++;
          return CameraConfig.parse(
            response(settings: settings, revision: 2, applied: 2),
          );
        },
      );
      try {
        await ble.initialize();
        await ble.connect('camera', 'VietOCR');
        await until(() => ble.connected);
        final result = await ble.configureCamera(settings);
        expect(result.settings, settings);
        expect(posts, 1);
        expect(reads, 1);
        expect(ble.connected, true);
        await ble.disconnect();
      } finally {
        ble.dispose();
        await radio.close();
      }
    },
  );
  test(
    'OV3660 rejects unsupported quality, crop ratios, types and missing fields',
    () {
      expect(validateCameraSettings(cameraDefaults), cameraDefaults);
      for (final entry in cameraFields.entries) {
        for (final value in [
          entry.value.min - 1,
          entry.value.max + 1,
          true,
          1.5,
        ]) {
          expect(
            () => validateCameraSettings({...cameraDefaults, entry.key: value}),
            throwsFormatException,
          );
        }
      }
      expect(
        () =>
            validateCameraSettings({...cameraDefaults, 'preview_width': 1920}),
        throwsFormatException,
      );
      expect(
        () => validateCameraSettings({...cameraDefaults, 'still_quality': 0}),
        throwsFormatException,
      );
      expect(
        () => CameraConfig.parse({...response(), 'schema': 1}),
        throwsFormatException,
      );
    },
  );
  test(
    'real HTTP sends authorization and the whole validated profile once',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final records = <Map<String, dynamic>>[];
      server.listen((request) async {
        expect(
          request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer ${'a' * 32}',
        );
        expect(request.uri.path, '/camera/config');
        final body =
            jsonDecode(await utf8.decoder.bind(request).join())
                as Map<String, dynamic>;
        records.add(body);
        request.response.statusCode = 202;
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode(
            response(
              settings: Map<String, int>.from(body['settings'] as Map),
              revision: 2,
              applied: 1,
              saved: false,
            ),
          ),
        );
        await request.response.close();
      });
      try {
        final settings = {...cameraDefaults, 'vflip': 1, 'brightness': 2};
        final result = await requestCameraConfig(
          WifiEndpoint('127.0.0.1:${server.port}', 'a' * 32),
          settings: settings,
          persist: true,
        );
        expect(result.settings, settings);
        expect(result.appliedRevision, 1);
        expect(result.saved, isFalse);
        expect(records, [
          {'settings': settings, 'persist': true},
        ]);
      } finally {
        await server.close(force: true);
      }
    },
  );
  test(
    'settings wait for NVS confirmation, keep BLE and reopen preview',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = fixture.FakeRadio()..ready();
      final streams = <fixture.ControlledCamera>[];
      var reads = 0;
      final settings = {...cameraDefaults, 'hmirror': 1};
      final ble = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
        cameraHealthCheck: (_) async {},
        cameraStreamFactory: (endpoint) {
          final stream = fixture.ControlledCamera(endpoint);
          streams.add(stream);
          return stream;
        },
        cameraSettingsRequest: (endpoint, values, persist) async {
          if (values != null) {
            expect(values, settings);
            expect(persist, isTrue);
            return CameraConfig.parse(
              response(
                settings: settings,
                revision: 2,
                applied: 1,
                saved: false,
              ),
            );
          }
          ++reads;
          return CameraConfig.parse(
            response(
              settings: settings,
              revision: 2,
              applied: 2,
              saved: reads >= 2,
            ),
          );
        },
      );
      await ble.initialize();
      await ble.connect('camera', 'VietOCR');
      await until(() => ble.connected);
      try {
        await ble.cameraPreview(true);
        final result = await ble.configureCamera(settings);
        expect(result.saved, isTrue);
        expect(reads, 2);
        expect(streams, hasLength(2));
        expect(streams.first.closed, isTrue);
        expect(ble.connected, isTrue);
        expect(ble.cameraConfigBusy, isFalse);
        expect(radio.commands.where((s) => s == 'CAM CLOSE'), isNotEmpty);
        await ble.command('PING');
        await ble.disconnect();
      } finally {
        ble.dispose();
        for (final stream in streams) {
          await stream.controller.close();
        }
        await radio.close();
      }
    },
  );
  test(
    'closing preview during apply does not reopen a departed camera page',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = fixture.FakeRadio()..ready();
      final streams = <fixture.ControlledCamera>[];
      final reply = Completer<CameraConfig>();
      final ble = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
        cameraHealthCheck: (_) async {},
        cameraStreamFactory: (endpoint) {
          final stream = fixture.ControlledCamera(endpoint);
          streams.add(stream);
          return stream;
        },
        cameraSettingsRequest: (_, _, _) => reply.future,
      );
      await ble.initialize();
      await ble.connect('camera', 'VietOCR');
      await until(() => ble.connected);
      try {
        await ble.cameraPreview(true);
        final apply = ble.configureCamera(cameraDefaults);
        await until(() => ble.cameraConfigBusy);
        await expectLater(ble.captureCamera(), throwsStateError);
        await ble.cameraPreview(false);
        reply.complete(CameraConfig.parse(response()));
        expect((await apply).saved, isTrue);
        expect(ble.previewing, isFalse);
        expect(ble.cameraConfigBusy, isFalse);
        expect(streams, hasLength(1));
        expect(streams.single.closed, isTrue);
        expect(ble.connected, isTrue);
        await ble.disconnect();
      } finally {
        ble.dispose();
        for (final stream in streams) {
          await stream.controller.close();
        }
        await radio.close();
      }
    },
  );
}
