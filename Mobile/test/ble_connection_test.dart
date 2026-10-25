import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/services/ble_assistant.dart';

class FakeRadio implements FlutterReactiveBle {
  FakeRadio({this.themeSupported = true});
  final bool themeSupported;
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
        command.startsWith('THEME ') && !themeSupported
            ? 'ERR INVALID_COMMAND\n'
            : command == 'PING'
            ? 'PONG\n'
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
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
