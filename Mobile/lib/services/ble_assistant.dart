import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../domain/document.dart';
import 'ble_protocol.dart';

class BleAssistant extends ChangeNotifier {
  final _ble = FlutterReactiveBle();
  static final service = Uuid.parse('6e400001-b5a3-f393-e0a9-e50e24dcca9e');
  static final rx = Uuid.parse('6e400002-b5a3-f393-e0a9-e50e24dcca9e');
  static final tx = Uuid.parse('6e400003-b5a3-f393-e0a9-e50e24dcca9e');
  static const _device = MethodChannel('vietocr/device');
  final Map<String, DiscoveredDevice> devices = {};
  StreamSubscription<DiscoveredDevice>? _scan;
  StreamSubscription<ConnectionStateUpdate>? _connection;
  StreamSubscription<List<int>>? _notifications;
  StreamSubscription<BleStatus>? _status;
  Timer? _scanTimer, _heartbeat, _retry;
  CommandQueue? _commands;
  int _epoch = 0;
  int _connectAttempt = 0;
  bool _disposed = false, _foreground = true, _syncing = false;
  bool scanning = false, connecting = false, connected = false;
  String message = 'Chưa kết nối trợ lý', selectedId = '', selectedName = '';
  BleStatus radio = BleStatus.unknown;
  AssistantSnapshot _desired = const AssistantSnapshot(AssistantState.awake);
  AssistantSnapshot? _sent;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    final prefs = await SharedPreferences.getInstance();
    if (_disposed) return;
    selectedId = prefs.getString('bleId') ?? '';
    selectedName = prefs.getString('bleName') ?? '';
    _status = _ble.statusStream.listen(
      (value) {
        radio = value;
        if (value != BleStatus.ready && (connected || connecting)) {
          unawaited(disconnect());
        }
        _notify();
      },
      onError: (Object error) {
        message = 'Bluetooth: $error';
        _notify();
      },
    );
    _notify();
    // Reconnect only after permissions have been granted in a previous session.
    if (selectedId.isNotEmpty && await _permissions(request: false)) {
      unawaited(connect(selectedId, selectedName));
    }
  }

  Future<bool> _permissions({bool request = true}) async {
    final sdk = await _device.invokeMethod<int>('androidSdk') ?? 31;
    final permissions = sdk >= 31
        ? [Permission.bluetoothScan, Permission.bluetoothConnect]
        : [Permission.locationWhenInUse];
    for (final permission in permissions) {
      final status = request
          ? await permission.request()
          : await permission.status;
      if (!status.isGranted) {
        if (request) {
          message = 'Cần cấp quyền Bluetooth trong Cài đặt ứng dụng.';
          _notify();
        }
        return false;
      }
    }
    return true;
  }

  Future<void> enableBluetooth() async {
    try {
      if (!await _permissions()) return;
      final enabled =
          await _device.invokeMethod<bool>('enableBluetooth') ?? false;
      message = enabled
          ? 'Bluetooth đã bật. Nhấn Tìm trợ lý.'
          : 'Bạn chưa bật Bluetooth.';
    } catch (error) {
      message = 'Không bật được Bluetooth: $error';
    }
    _notify();
  }

  Future<void> scan() async {
    try {
      if (connecting || connected || !_foreground) return;
      if (!await _permissions()) return;
      await stopScan();
      devices.clear();
      scanning = true;
      message = 'Đang tìm VietOCR Assistant…';
      _notify();
      _scan = _ble
          .scanForDevices(
            withServices: [service],
            scanMode: ScanMode.lowLatency,
          )
          .listen(
            (device) {
              devices[device.id] = device;
              _notify();
            },
            onError: (Object error) {
              message =
                  'Không quét được. Kiểm tra Bluetooth và quyền truy cập.\n$error';
              unawaited(stopScan());
            },
          );
      _scanTimer = Timer(const Duration(seconds: 12), () {
        message = devices.isEmpty
            ? 'Chưa thấy trợ lý. Kiểm tra nguồn ESP32 và firmware BLE.'
            : 'Chọn trợ lý để kết nối.';
        unawaited(stopScan());
      });
    } catch (error) {
      message = 'Không tìm được trợ lý: $error';
      scanning = false;
      _notify();
    }
  }

  Future<void> stopScan() async {
    _scanTimer?.cancel();
    await _cancelSubscription(_scan);
    _scan = null;
    scanning = false;
    _notify();
  }

  Future<void> connect(String id, String name) async {
    if (_disposed || !_foreground || connecting || connected) return;
    final attempt = ++_connectAttempt;
    connecting = true;
    _notify();
    try {
      if (!await _permissions()) {
        if (attempt == _connectAttempt) connecting = false;
        _notify();
        return;
      }
      if (_disposed || !_foreground || attempt != _connectAttempt) return;
      await stopScan();
      if (_disposed || !_foreground || attempt != _connectAttempt) return;
      await disconnect(cancelAttempt: false);
      if (_disposed || !_foreground || attempt != _connectAttempt) return;
      selectedId = id;
      selectedName = name.isEmpty ? 'VietOCR Assistant' : name;
      connecting = true;
      message = 'Đang kết nối $selectedName…';
      _notify();
      final epoch = ++_epoch;
      _connection = _ble
          .connectToDevice(
            id: id,
            servicesWithCharacteristicsToDiscover: {
              service: [rx, tx],
            },
            connectionTimeout: const Duration(seconds: 12),
          )
          .listen(
            (update) {
              if (epoch != _epoch) return;
              if (update.connectionState == DeviceConnectionState.connected) {
                unawaited(_setup(epoch));
              }
              if (update.connectionState ==
                  DeviceConnectionState.disconnected) {
                _lost(epoch, 'Trợ lý đã ngắt kết nối.');
              }
            },
            onError: (Object error) => _lost(epoch, 'Kết nối thất bại: $error'),
          );
    } catch (error) {
      connecting = false;
      message = 'Kết nối thất bại: $error';
      _notify();
    }
  }

  Future<void> _setup(int epoch) async {
    try {
      final framer = LineFramer();
      final queue = CommandQueue(
        (bytes) => _ble.writeCharacteristicWithResponse(
          QualifiedCharacteristic(
            characteristicId: rx,
            serviceId: service,
            deviceId: selectedId,
          ),
          value: bytes,
        ),
      );
      _commands = queue;
      _notifications = _ble
          .subscribeToCharacteristic(
            QualifiedCharacteristic(
              characteristicId: tx,
              serviceId: service,
              deviceId: selectedId,
            ),
          )
          .listen(
            (bytes) {
              if (epoch != _epoch) return;
              try {
                for (final line in framer.add(bytes)) {
                  queue.receive(line);
                }
              } catch (error) {
                _lost(epoch, 'Phản hồi Bluetooth không hợp lệ: $error');
              }
            },
            onError: (Object error) =>
                _lost(epoch, 'Mất thông báo Bluetooth: $error'),
          );
      // Give the platform time to enable TX notifications before the handshake.
      await Future<void>.delayed(const Duration(milliseconds: 250));
      if (epoch != _epoch) return;
      await queue.send('PING');
      if (epoch != _epoch) return;
      await queue.send('WAKE');
      if (epoch != _epoch) return;
      connecting = false;
      connected = true;
      _sent = const AssistantSnapshot(AssistantState.awake);
      message = 'Đã kết nối $selectedName';
      _notify();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('bleId', selectedId);
      await prefs.setString('bleName', selectedName);
      if (epoch != _epoch) return;
      _heartbeat = Timer.periodic(const Duration(seconds: 4), (_) {
        if (connected) unawaited(command('PING'));
      });
      unawaited(_sync());
    } catch (error) {
      _lost(epoch, 'Trợ lý chưa phản hồi: $error');
    }
  }

  void _lost(int epoch, String reason) {
    if (epoch != _epoch || _disposed) return;
    unawaited(
      disconnect().then((_) {
        if (_disposed) return;
        message = reason;
        _notify();
        if (_foreground && selectedId.isNotEmpty) {
          _retry = Timer(
            const Duration(seconds: 5),
            () => unawaited(connect(selectedId, selectedName)),
          );
        }
      }),
    );
  }

  Future<void> command(String command) async {
    final epoch = _epoch;
    if (!connected) return;
    try {
      await _commands!.send(command);
    } catch (error) {
      _lost(epoch, 'Mất kết nối trợ lý: $error');
    }
  }

  void update(AssistantState state, int count, int progress) {
    _desired = AssistantSnapshot(state, count: count, progress: progress);
    unawaited(_sync());
  }

  Future<void> _sync() async {
    if (!connected || _syncing) return;
    _syncing = true;
    final epoch = _epoch;
    try {
      while (connected && epoch == _epoch) {
        final target = _desired;
        for (final value in transitionCommands(_sent, target)) {
          await _commands!.send(value);
        }
        if (epoch != _epoch) break;
        _sent = target;
        if (identical(target, _desired)) break;
      }
    } catch (error) {
      _lost(epoch, 'Đồng bộ trợ lý thất bại: $error');
    } finally {
      _syncing = false;
      if (connected && !identical(_sent, _desired)) unawaited(_sync());
    }
  }

  Future<void> disconnect({
    bool sleep = false,
    bool cancelAttempt = true,
  }) async {
    if (cancelAttempt) ++_connectAttempt;
    _retry?.cancel();
    _heartbeat?.cancel();
    if (sleep && connected) {
      try {
        await _commands?.send('SLEEP');
      } catch (_) {}
    }
    ++_epoch;
    connected = connecting = false;
    _commands?.close();
    _commands = null;
    _sent = null;
    await _cancelSubscription(_notifications);
    _notifications = null;
    await _cancelSubscription(_connection);
    _connection = null;
    _notify();
  }

  Future<void> setForeground(bool foreground) async {
    _foreground = foreground;
    if (!foreground) {
      await stopScan();
      await disconnect(sleep: true);
    } else if (!_disposed &&
        selectedId.isNotEmpty &&
        await _permissions(request: false)) {
      await connect(selectedId, selectedName);
    }
  }

  Future<void> _cancelSubscription(StreamSubscription? subscription) async {
    try {
      await subscription?.cancel();
    } catch (error) {
      debugPrint('BLE shutdown: $error');
    }
  }

  Future<void> forget() async {
    selectedId = selectedName = '';
    await disconnect(sleep: true);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('bleId');
    await prefs.remove('bleName');
    message = 'Đã ngắt kết nối trợ lý';
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _foreground = false;
    _retry?.cancel();
    _heartbeat?.cancel();
    _scanTimer?.cancel();
    _commands?.close();
    unawaited(_cancelSubscription(_scan));
    unawaited(_cancelSubscription(_status));
    unawaited(_cancelSubscription(_notifications));
    unawaited(_cancelSubscription(_connection));
    super.dispose();
  }
}
