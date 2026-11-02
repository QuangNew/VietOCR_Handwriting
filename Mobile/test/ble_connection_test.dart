import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/services/ble_assistant.dart';
import 'package:vietocr_mobile/services/mjpeg_stream.dart';

class FakeRadio implements FlutterReactiveBle {
  FakeRadio({this.themeSupported = true, this.wifiSupported = true});
  final bool themeSupported;
  final bool wifiSupported;
  bool wifiReady = true;
  final statuses = StreamController<BleStatus>.broadcast();
  final notifications = StreamController<List<int>>.broadcast();
  final connections = StreamController<ConnectionStateUpdate>.broadcast();
  final commands = <String>[];
  int attempts = 0;
  BleStatus current = BleStatus.unknown;
  @override
  BleStatus get status => current;
  @override
  Stream<BleStatus> get statusStream => statuses.stream;
  void ready() {
    current = BleStatus.ready;
    statuses.add(current);
  }

  @override
  Stream<ConnectionStateUpdate> connectToAdvertisingDevice({
    required String id,
    required List<Uuid> withServices,
    required Duration prescanDuration,
    Map<Uuid, List<Uuid>>? servicesWithCharacteristicsToDiscover,
    Duration? connectionTimeout,
  }) {
    attempts++;
    Timer.run(
      () => connections.add(
        ConnectionStateUpdate(
          deviceId: id,
          connectionState: DeviceConnectionState.connected,
          failure: null,
        ),
      ),
    );
    return connections.stream;
  }

  @override
  Stream<List<int>> subscribeToCharacteristic(
    QualifiedCharacteristic characteristic,
  ) => notifications.stream;
  @override
  Future<void> writeCharacteristicWithResponse(
    QualifiedCharacteristic characteristic, {
    required List<int> value,
  }) async {
    final command = ascii.decode(value).trim();
    commands.add(command);
    Timer.run(() {
      final answer = ascii.encode(
        (command.startsWith('THEME ') && !themeSupported) ||
                (command.startsWith('WIFI ') && !wifiSupported)
            ? 'ERR INVALID_COMMAND\n'
            : command == 'PING'
            ? 'PONG\n'
            : command == 'WIFI STATUS'
            ? wifiReady
                  ? 'WIFI STATUS READY 127.0.0.1 ${'a' * 32} 61\n'
                  : 'WIFI STATUS OFFLINE 6\n'
            : command == 'WIFI SAVED'
            ? 'WIFI SAVED 1 61\n'
            : 'OK $command\n',
      );
      notifications.add(answer.sublist(0, 3));
      notifications.add(answer.sublist(3));
    });
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
  Future<void> close() async {
    await statuses.close();
    await notifications.close();
    await connections.close();
  }
}

Future<void> until(bool Function() condition) async {
  final deadline = DateTime.now().add(const Duration(seconds: 3));
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('Bluetooth operation did not complete');
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

class ControlledCamera extends MjpegConnection {
  ControlledCamera(super.endpoint);
  final controller = StreamController<Uint8List>.broadcast();
  bool closed = false;
  @override
  Stream<Uint8List> frames() => controller.stream;
  @override
  void close() {
    closed = true;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'connection immediately reads saved Wi-Fi without scan or camera HTTP',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = FakeRadio()..ready();
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
      );
      try {
        await assistant.connect('test', 'VietOCR');
        await until(() => assistant.wifiState?.ready == true);
        expect(assistant.wifiMessage, contains('127.0.0.1'));
        expect(assistant.wifiState?.savedSsid, 'a');
        expect(radio.commands, contains('WIFI SAVED'));
        expect(radio.commands, isNot(contains('WIFI SCAN')));
        expect(radio.commands, isNot(contains('WIFI JOIN')));
        await assistant.configureWifi('a', '');
        expect(
          radio.commands,
          isNot(contains('WIFI SSID 61')),
          reason:
              'Blank password must not replace the saved credentials of the active network',
        );
        radio.wifiReady = false;
        await assistant.refreshWifiState();
        expect(assistant.wifiState?.state, 'offline');
        expect(assistant.connected, isTrue);
        await assistant.disconnect();
        expect(assistant.wifiState, isNull);
        expect(assistant.wifiMessage, isNot(contains('đã kết nối')));
      } finally {
        assistant.dispose();
        await radio.close();
      }
    },
  );
  test('failed LAN preflight never starts the sensor or drops BLE', () async {
    SharedPreferences.setMockInitialValues({});
    final radio = FakeRadio()..ready();
    final assistant = BleAssistant(
      radioClient: radio,
      permissionCheck: (_) async => true,
      cameraHealthCheck: (_) async =>
          throw StateError('Camera HTTP unreachable'),
    );
    await assistant.initialize();
    await assistant.connect('camera', 'VietOCR');
    await until(() => assistant.connected);
    try {
      await expectLater(assistant.cameraPreview(true), throwsStateError);
      expect(radio.commands.where((line) => line == 'CAM OPEN'), isEmpty);
      expect(assistant.connected, isTrue);
      expect(assistant.previewing, isFalse);
      await assistant.command('PING');
      await assistant.disconnect();
    } finally {
      assistant.dispose();
      await radio.close();
    }
  });
  test(
    'camera keeps one stream, leaves BLE theme responsive, and closes on capture/disconnect',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = FakeRadio()..ready();
      final streams = <ControlledCamera>[];
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
        cameraStreamFactory: (endpoint) {
          final stream = ControlledCamera(endpoint);
          streams.add(stream);
          return stream;
        },
        cameraHealthCheck: (_) async {},
      );
      await assistant.initialize();
      await assistant.connect('camera', 'VietOCR');
      await until(() => assistant.connected);
      await assistant.refreshWifiState();
      final checksBeforePreview = radio.commands
          .where((s) => s == 'WIFI STATUS')
          .length;
      try {
        await assistant.cameraPreview(true);
        expect(streams, hasLength(1));
        expect(assistant.previewBytes, isNull);
        streams.first.controller.add(
          Uint8List.fromList([
            255,
            216,
            255,
            192,
            0,
            8,
            8,
            1,
            224,
            2,
            128,
            0,
            255,
            217,
          ]),
        );
        await until(() => assistant.previewBytes != null);
        expect(assistant.cameraMessage, contains('640 × 480'));
        assistant.update(AssistantState.awake, 0, null, dark: false);
        await until(() => radio.commands.contains('THEME LIGHT'));
        await assistant.command('PING');
        expect(radio.commands.where((s) => s == 'CAM STATUS'), isEmpty);
        expect(
          radio.commands.where((s) => s == 'WIFI STATUS'),
          hasLength(checksBeforePreview + 1),
        );
        await assistant.cameraPreview(false);
        expect(streams.first.closed, isTrue);
        expect(assistant.previewBytes, isNull);
        streams.first.controller.add(Uint8List.fromList([1, 2, 3]));
        await Future<void>.delayed(Duration.zero);
        expect(assistant.previewBytes, isNull);
        await assistant.cameraPreview(true);
        expect(streams, hasLength(2));
        await assistant.disconnect();
        expect(streams.last.closed, isTrue);
        expect(assistant.previewing, isFalse);
      } finally {
        assistant.dispose();
        for (final stream in streams) {
          await stream.controller.close();
        }
        await radio.close();
      }
    },
  );
  test('stream errors preserve BLE and permit reopening', () async {
    SharedPreferences.setMockInitialValues({});
    final radio = FakeRadio()..ready();
    final streams = <ControlledCamera>[];
    final assistant = BleAssistant(
      radioClient: radio,
      permissionCheck: (_) async => true,
      cameraStreamFactory: (endpoint) {
        final stream = ControlledCamera(endpoint);
        streams.add(stream);
        return stream;
      },
      cameraHealthCheck: (_) async {},
    );
    await assistant.initialize();
    await assistant.connect('camera', 'VietOCR');
    await until(() => assistant.connected);
    try {
      await assistant.cameraPreview(true);
      streams.first.controller.addError(StateError('2.2.0-stream required'));
      await until(() => !assistant.previewing);
      expect(assistant.cameraMessage, contains('2.2.0-stream'));
      expect(assistant.connected, isTrue);
      await assistant.command('PING');
      await assistant.cameraPreview(true);
      expect(streams, hasLength(2));
      radio.wifiReady = false;
      await expectLater(assistant.captureCamera(), throwsStateError);
      expect(streams.last.closed, isTrue);
      expect(radio.commands.where((s) => s.startsWith('CAM SHOT')), isEmpty);
      expect(assistant.connected, isTrue);
      radio.wifiReady = true;
      await assistant.cameraPreview(true);
      expect(streams, hasLength(3));
      await assistant.disconnect();
    } finally {
      assistant.dispose();
      for (final stream in streams) {
        await stream.controller.close();
      }
      await radio.close();
    }
  });
  test(
    'Wi-Fi missing firmware is explained while BLE theme and ping still work',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = FakeRadio(wifiSupported: false)..ready();
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
      );
      await assistant.initialize();
      await assistant.connect('old-camera', 'VietOCR');
      await until(() => assistant.connected);
      for (final operation in [assistant.scanWifi, assistant.wifiStatus]) {
        await expectLater(
          operation(),
          throwsA(
            isA<StateError>().having(
              (error) => error.message,
              'message',
              contains('esp32-s3-cam-ov5640'),
            ),
          ),
        );
      }
      await expectLater(
        assistant.configureWifi('Test', '12345678'),
        throwsStateError,
      );
      assistant.update(AssistantState.awake, 0, null, dark: false);
      await until(() => radio.commands.contains('THEME LIGHT'));
      await assistant.command('PING');
      expect(assistant.connected, isTrue);
      expect(radio.attempts, 1);
      await assistant.disconnect(sleep: true);
      assistant.dispose();
      await radio.close();
    },
  );
  test(
    'older firmware keeps its connection and OCR events after rejecting theme',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = FakeRadio(themeSupported: false)..ready();
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
      );
      await assistant.initialize();
      assistant.update(AssistantState.received, 2, null, dark: true);
      await assistant.connect('legacy-device', 'VietOCR');
      await until(() => radio.commands.contains('RECEIVED 2'));
      assistant.update(AssistantState.processing, 2, null, dark: false);
      await until(() => radio.commands.contains('PROCESS'));
      expect(assistant.connected, isTrue);
      expect(radio.attempts, 1);
      expect(
        radio.commands.where((command) => command.startsWith('THEME ')),
        hasLength(1),
      );
      expect(assistant.message, contains('firmware'));
      await assistant.disconnect(sleep: true);
      assistant.dispose();
      await radio.close();
    },
  );
  test(
    'unknown radio waits for readiness, connects on first attempt, and syncs theme without restarting OCR',
    () async {
      SharedPreferences.setMockInitialValues({});
      final radio = FakeRadio();
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) async => true,
      );
      await assistant.initialize();
      final connecting = assistant.connect('device-1', 'VietOCR');
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(radio.attempts, 0);
      radio.ready();
      await connecting;
      await until(() => assistant.connected);
      expect(radio.attempts, 1);
      assistant.update(AssistantState.processing, 3, null, dark: false);
      await until(() => radio.commands.contains('PROCESS'));
      assistant.update(AssistantState.processing, 3, null, dark: true);
      await until(() => radio.commands.contains('THEME DARK'));
      expect(
        radio.commands.where((command) => command == 'PROCESS'),
        hasLength(1),
      );
      expect(
        radio.commands.where((command) => command.startsWith('PROGRESS')),
        isEmpty,
      );
      await assistant.disconnect(sleep: true);
      expect(radio.commands.last, 'SLEEP');
      assistant.dispose();
      await radio.close();
    },
  );
  test(
    'forget during permission wait prevents a late unwanted connection',
    () async {
      SharedPreferences.setMockInitialValues({});
      final permission = Completer<bool>();
      final radio = FakeRadio()..ready();
      final assistant = BleAssistant(
        radioClient: radio,
        permissionCheck: (_) => permission.future,
      );
      final connecting = assistant.connect('device-1', 'VietOCR');
      await assistant.forget();
      permission.complete(true);
      await connecting;
      expect(radio.attempts, 0);
      expect(assistant.connected, isFalse);
      assistant.dispose();
      await radio.close();
    },
  );
}
