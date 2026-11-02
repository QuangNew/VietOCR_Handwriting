import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../domain/document.dart';
import 'ble_protocol.dart';
import 'app_log.dart';
import 'camera_transfer.dart';
import 'wifi_camera.dart';
import 'mjpeg_stream.dart';
import 'udp_camera.dart';
import 'camera_settings.dart';

class BleAssistant extends ChangeNotifier {
  BleAssistant({
    FlutterReactiveBle? radioClient,
    this.permissionCheck,
    this.cameraStreamFactory,
    this.cameraHealthCheck,
    this.cameraSettingsRequest,
  }) : _ble = radioClient ?? FlutterReactiveBle();
  final FlutterReactiveBle _ble;
  final Future<bool> Function(bool request)? permissionCheck;
  final MjpegConnection Function(WifiEndpoint endpoint)? cameraStreamFactory;
  final Future<void> Function(WifiEndpoint endpoint)? cameraHealthCheck;
  final Future<CameraConfig> Function(
    WifiEndpoint endpoint,
    Map<String, int>? settings,
    bool persist,
  )?
  cameraSettingsRequest;
  CameraConfig? cameraConfiguration;
  bool cameraConfigBusy = false;
  static final service = Uuid.parse('6e400001-b5a3-f393-e0a9-e50e24dcca9e');
  static final rx = Uuid.parse('6e400002-b5a3-f393-e0a9-e50e24dcca9e');
  static final tx = Uuid.parse('6e400003-b5a3-f393-e0a9-e50e24dcca9e');
  static final image = Uuid.parse('6e400004-b5a3-f393-e0a9-e50e24dcca9e');
  int _mtu = 23;
  bool cameraBusy = false;
  double? cameraProgress;
  String cameraMessage = 'Xem và nhận ảnh gốc qua Wi-Fi camera.';
  Uint8List? previewBytes;
  bool previewing = false;
  int _previewGeneration = 0, _setupEpoch = -1;
  MjpegConnection? _previewConnection;
  StreamSubscription<Uint8List>? _previewSubscription;
  static const _device = MethodChannel('vietocr/device');
  final Map<String, DiscoveredDevice> devices = {};
  StreamSubscription<DiscoveredDevice>? _scan;
  StreamSubscription<ConnectionStateUpdate>? _connection;
  StreamSubscription<List<int>>? _notifications;
  StreamSubscription<BleStatus>? _status;
  Timer? _scanTimer, _heartbeat, _retry, _wifiPoll;
  WifiState? wifiState;
  String wifiError = '';
  Future<void>? _wifiRefresh;
  String get wifiMessage => !connected
      ? 'Wi-Fi · Kết nối Bluetooth để xem trạng thái'
      : wifiError.isNotEmpty
      ? 'Wi-Fi · Chưa đọc được trạng thái: $wifiError'
      : (wifiState ?? const WifiState()).summary;
  CommandQueue? _commands;
  int _epoch = 0;
  int _connectAttempt = 0;
  bool _disposed = false, _foreground = true, _syncing = false;
  bool _themeSupported = true;
  String _lastLogMessage = '';
  bool scanning = false, connecting = false, connected = false;
  String message = 'Chưa kết nối trợ lý', selectedId = '', selectedName = '';
  BleStatus radio = BleStatus.unknown;
  AssistantSnapshot _desired = const AssistantSnapshot(AssistantState.awake);
  AssistantSnapshot? _sent;

  void _notify() {
    if (_lastLogMessage != message) {
      _lastLogMessage = message;
      AppLog.instance.add('BLE', message);
    }
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
        if ((value == BleStatus.poweredOff || value == BleStatus.unsupported) &&
            (connected || connecting)) {
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
    if (permissionCheck != null) return permissionCheck!(request);
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

  Future<bool> _ready() async {
    var value = _ble.status;
    if (value == BleStatus.unknown) {
      value = await _ble.statusStream
          .firstWhere((status) => status != BleStatus.unknown)
          .timeout(const Duration(seconds: 6));
    }
    if (value == BleStatus.ready) return true;
    message = value == BleStatus.poweredOff
        ? 'Bật Bluetooth trước khi tìm trợ lý.'
        : value == BleStatus.locationServicesDisabled
        ? 'Bật dịch vụ vị trí để quét Bluetooth trên Android này.'
        : 'Bluetooth chưa sẵn sàng. Kiểm tra quyền Thiết bị ở gần.';
    _notify();
    return false;
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
      if (scanning || connecting || connected || !_foreground) return;
      if (!await _permissions() || !await _ready()) return;
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
      if (!await _permissions() || !await _ready()) {
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
          .connectToAdvertisingDevice(
            id: id,
            withServices: [service],
            prescanDuration: const Duration(seconds: 2),
            servicesWithCharacteristicsToDiscover: {
              service: [rx, tx, image],
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
    if (_setupEpoch == epoch) return;
    _setupEpoch = epoch;
    try {
      final deviceId = selectedId;
      final framer = LineFramer();
      final queue = CommandQueue((bytes) {
        return _ble.writeCharacteristicWithResponse(
          QualifiedCharacteristic(
            characteristicId: rx,
            serviceId: service,
            deviceId: deviceId,
          ),
          value: bytes,
        );
      });
      _commands = queue;
      _notifications = _ble
          .subscribeToCharacteristic(
            QualifiedCharacteristic(
              characteristicId: tx,
              serviceId: service,
              deviceId: deviceId,
            ),
          )
          .listen(
            (bytes) {
              if (epoch != _epoch) return;
              try {
                for (final line in framer.add(bytes)) {
                  AppLog.instance.add(
                    'BLE RX',
                    line.startsWith('WIFI STATUS READY ')
                        ? 'WIFI STATUS READY [session hidden]'
                        : line,
                    level: 'DEBUG',
                  );
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
      try {
        _mtu = await _ble.requestMtu(deviceId: deviceId, mtu: 247);
      } catch (_) {
        _mtu = 23;
      }
      if (epoch != _epoch) return;
      connecting = false;
      connected = true;
      _themeSupported = true;
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
      unawaited(refreshWifiState());
      _wifiPoll?.cancel();
      _wifiPoll = Timer.periodic(const Duration(seconds: 5), (_) {
        if (connected && !cameraBusy) unawaited(refreshWifiState());
      });
    } catch (error) {
      _lost(epoch, 'Trợ lý chưa phản hồi: $error');
    }
  }

  void _lost(int epoch, String reason) {
    if (epoch != _epoch || _disposed) return;
    AppLog.instance.add('BLE', reason, level: 'ERROR');
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

  Future<void> cameraPreview(bool show) async {
    if (!connected) throw StateError('Kết nối trợ lý trước khi mở OV5640.');
    if (show && previewing) return;
    _stopPreview();
    final generation = _previewGeneration, epoch = _epoch;
    cameraMessage = show
        ? 'Đang mở stream camera qua Wi-Fi…'
        : 'Đã trở về trợ lý.';
    _notify();
    try {
      final endpoint = show
          ? WifiEndpoint.parse(
              await _wifiSend(
                _commands!,
                'WIFI STATUS',
                expectedPrefix: 'WIFI STATUS ',
              ),
            )
          : null;
      if (generation != _previewGeneration || epoch != _epoch || _disposed) {
        return;
      }
      if (show) {
        await (cameraHealthCheck ?? checkCameraHttp)(endpoint!);
        if (generation != _previewGeneration || epoch != _epoch || _disposed) {
          return;
        }
      }
      await _commands!.send(show ? 'CAM OPEN' : 'CAM CLOSE');
      if (!show ||
          generation != _previewGeneration ||
          epoch != _epoch ||
          _disposed) {
        return;
      }
      previewing = true;
      final connection =
          cameraStreamFactory?.call(endpoint!) ??
          UdpCameraConnection(endpoint!);
      _previewConnection = connection;
      final watch = Stopwatch()..start();
      var first = true;
      bool current() =>
          !_disposed &&
          generation == _previewGeneration &&
          epoch == _epoch &&
          connected;
      void failed(Object error) {
        if (!current()) return;
        _stopPreview();
        cameraMessage = 'Không xem được camera: $error';
        AppLog.instance.add('CAMERA', cameraMessage, level: 'ERROR');
        _notify();
      }

      _previewSubscription = connection.frames().listen(
        (bytes) {
          if (!current()) return;
          final size = cameraJpegSize(bytes);
          if (size == null ||
              size.$1 < 160 ||
              size.$1 > 2592 ||
              size.$1 * 3 != size.$2 * 4) {
            failed(
              StateError('Preview cần cùng tỷ lệ 4:3 với ảnh chụp OV5640.'),
            );
            return;
          }
          previewBytes = bytes;
          cameraMessage =
              'Preview ${size.$1} × ${size.$2} · Ảnh chụp gốc 2592 × 1944.';
          if (first) {
            AppLog.instance.add(
              'CAMERA',
              'Đã nhận khung hình stream đầu tiên',
              error: 'ms=${watch.elapsedMilliseconds}, bytes=${bytes.length}',
            );
            first = false;
          }
          _notify();
        },
        onError: (Object error) => failed(error),
        onDone: () {
          if (current()) {
            failed(
              StateError('Camera đã dừng stream. Nhấn Xem camera để mở lại.'),
            );
          }
        },
      );
    } catch (error) {
      if (generation != _previewGeneration || epoch != _epoch || _disposed) {
        return;
      }
      _stopPreview();
      cameraMessage = 'Không mở được camera: $error';
      AppLog.instance.add('CAMERA', cameraMessage, level: 'ERROR');
      rethrow;
    } finally {
      _notify();
    }
  }

  Future<CameraConfig> readCameraConfig() async {
    if (!connected) throw StateError('Kết nối ESP32 trước khi chỉnh camera.');
    final epoch = _epoch, queue = _commands!;
    final endpoint = WifiEndpoint.parse(
      await _wifiSend(queue, 'WIFI STATUS', expectedPrefix: 'WIFI STATUS '),
    );
    final config =
        await (cameraSettingsRequest?.call(endpoint, null, false) ??
            requestCameraConfig(endpoint));
    if (epoch != _epoch || !connected || _disposed) {
      throw StateError('Phiên camera đã thay đổi.');
    }
    cameraConfiguration = config;
    return config;
  }

  Future<CameraConfig> configureCamera(
    Map<String, int> settings, {
    bool persist = true,
  }) async {
    validateCameraSettings(settings);
    if (!connected || cameraBusy || cameraConfigBusy) {
      throw StateError('Camera đang bận hoặc Bluetooth đã ngắt.');
    }
    final epoch = _epoch, queue = _commands!, resume = previewing;
    void check() {
      if (epoch != _epoch || !connected || _disposed) {
        throw StateError('Phiên camera đã thay đổi.');
      }
    }

    _stopPreview();
    final previewGeneration = _previewGeneration;
    cameraConfigBusy = true;
    _notify();
    try {
      final endpoint = WifiEndpoint.parse(
        await _wifiSend(queue, 'WIFI STATUS', expectedPrefix: 'WIFI STATUS '),
      );
      check();
      await queue.send('CAM CLOSE');
      check();
      Future<CameraConfig> request(Map<String, int>? values) =>
          cameraSettingsRequest?.call(endpoint, values, persist) ??
          requestCameraConfig(endpoint, settings: values, persist: persist);
      var config = await request(settings);
      check();
      final revision = config.revision, watch = Stopwatch()..start();
      while (true) {
        if (config.error.isNotEmpty) throw StateError(config.error);
        if (config.revision != revision) {
          throw StateError('Cấu hình đã đổi. Hãy tải lại.');
        }
        if (config.appliedRevision == revision && (!persist || config.saved)) {
          break;
        }
        if (watch.elapsed > const Duration(seconds: 20)) {
          throw StateError(
            'Chưa xác nhận áp dụng cấu hình. Tải lại trước khi thử tiếp.',
          );
        }
        await Future<void>.delayed(const Duration(milliseconds: 150));
        check();
        config = await request(null);
        check();
      }
      cameraConfiguration = config;
      AppLog.instance.add(
        'CAMERA',
        'Đã áp dụng cấu hình${config.saved ? ' và lưu trên ESP32' : ''}',
      );
      // Closing the camera page while HTTP/NVS is pending revokes this resume.
      if (resume && previewGeneration == _previewGeneration) {
        check();
        await cameraPreview(true);
      }
      return config;
    } finally {
      cameraConfigBusy = false;
      _notify();
    }
  }

  void _stopPreview() {
    previewing = false;
    ++_previewGeneration;
    _previewConnection?.close();
    _previewConnection = null;
    final subscription = _previewSubscription;
    _previewSubscription = null;
    unawaited(_cancelSubscription(subscription));
    previewBytes = null;
  }

  Future<String> _wifiSend(
    CommandQueue queue,
    String command, {
    String? expectedPrefix,
  }) async {
    try {
      return await queue.send(command, expectedPrefix: expectedPrefix);
    } on CommandRejected catch (error) {
      if (error.code == 'INVALID_COMMAND') {
        throw StateError(
          'ESP32 chưa hỗ trợ Wi-Fi camera. Nạp profile esp32-s3-cam-ov5640, firmware 3.0.0-ov5640 rồi kết nối BLE lại.',
        );
      }
      if (error.code == 'WIFI_BUSY') {
        throw StateError('ESP32 đang kết nối Wi-Fi. Đợi rồi kiểm tra lại.');
      }
      if (error.code == 'WIFI_SCAN_FAILED') {
        throw StateError(
          'ESP32 quét Wi-Fi chưa thành công. Nhấn Quét mạng để thử lại.',
        );
      }
      rethrow;
    }
  }

  Future<List<String>> scanWifi() async {
    if (!connected) throw StateError('Kết nối trợ lý Bluetooth trước.');
    final queue = _commands!;
    await _wifiSend(queue, 'WIFI SCAN');
    final deadline = DateTime.now().add(const Duration(seconds: 20));
    late int count;
    while (true) {
      final line = await _wifiSend(
        queue,
        'WIFI COUNT',
        expectedPrefix: 'WIFI COUNT ',
      );
      if (line != 'WIFI COUNT BUSY') {
        count = int.parse(line.split(' ').last);
        break;
      }
      if (DateTime.now().isAfter(deadline)) {
        throw StateError('Quét Wi-Fi quá hạn.');
      }
      await Future<void>.delayed(const Duration(milliseconds: 350));
    }
    if (count < 0 || count > 30) {
      throw const FormatException('Sai số mạng Wi-Fi.');
    }
    final names = <String>{};
    for (var i = 0; i < count; i++) {
      final parts = (await _wifiSend(
        queue,
        'WIFI NET $i',
        expectedPrefix: 'WIFI NET $i ',
      )).split(' ');
      if (parts.length != 6) {
        throw const FormatException('Sai thông tin Wi-Fi.');
      }
      final name = wifiName(parts[5]);
      if (name.isNotEmpty) names.add(name);
    }
    return names.toList();
  }

  Future<String> configureWifi(String ssid, String password) async {
    if (!connected) throw StateError('Kết nối trợ lý Bluetooth trước.');
    if (wifiState?.ready == true &&
        wifiState?.ssid == ssid &&
        password.isEmpty) {
      return 'Mạng này đã kết nối. Không cần nhập lại mật khẩu hoặc kết nối lại.';
    }
    final commands = wifiCommands(ssid, password);
    final queue = _commands!;
    for (final line in commands) {
      await _wifiSend(
        queue,
        line,
        expectedPrefix: line.startsWith('WIFI SSID ')
            ? 'OK WIFI SSID'
            : line.startsWith('WIFI PASS ')
            ? 'OK WIFI PASS'
            : null,
      );
    }
    unawaited(refreshWifiState());
    return 'Đã gửi cấu hình. Trạng thái kết nối sẽ tự cập nhật.';
  }

  Future<void> refreshWifiState() {
    if (!connected || _disposed) return Future<void>.value();
    if (_wifiRefresh != null) return _wifiRefresh!;
    late final Future<void> pending;
    pending = _readWifiState().whenComplete(() {
      if (identical(_wifiRefresh, pending)) _wifiRefresh = null;
    });
    return _wifiRefresh = pending;
  }

  Future<void> _readWifiState() async {
    final epoch = _epoch, queue = _commands!;
    try {
      final response = await _wifiSend(
        queue,
        'WIFI STATUS',
        expectedPrefix: 'WIFI STATUS ',
      );
      String saved;
      try {
        saved = await queue.send('WIFI SAVED', expectedPrefix: 'WIFI SAVED ');
      } on CommandRejected catch (error) {
        if (!['INVALID_COMMAND', 'WIFI_COMMAND'].contains(error.code)) rethrow;
        saved = 'WIFI SAVED 0 -';
      }
      final state = WifiState.parse(response, saved);
      if (epoch != _epoch || !connected || _disposed) return;
      wifiState = state;
      wifiError = '';
    } catch (error) {
      if (epoch != _epoch || !connected || _disposed) return;
      wifiState = null;
      wifiError = '$error';
    }
    _notify();
  }

  Future<String> wifiStatus() async {
    if (!connected) throw StateError('Kết nối trợ lý Bluetooth trước.');
    await refreshWifiState();
    final line = await _wifiSend(
      _commands!,
      'WIFI STATUS',
      expectedPrefix: 'WIFI STATUS ',
    );
    if (line.startsWith('WIFI STATUS READY ')) {
      await checkCameraHttp(WifiEndpoint.parse(line));
      return 'Đã kiểm tra LAN tới ${WifiEndpoint.parse(line).ip}:80. HTTP hoạt động; trạng thái cảm biến hiện ở trang camera.';
    }
    return wifiUnavailableMessage(line);
  }

  Future<CameraPhoto> captureCamera() async {
    if (!connected || cameraBusy || cameraConfigBusy) {
      throw StateError('Kết nối trợ lý và đợi ảnh trước nhận xong.');
    }
    cameraBusy = true;
    _stopPreview();
    cameraProgress = 0;
    final epoch = _epoch;
    final queue = _commands!;
    cameraMessage = 'Đang chụp ảnh gốc qua Wi-Fi…';
    _notify();
    try {
      final endpoint = WifiEndpoint.parse(
        await _wifiSend(queue, 'WIFI STATUS', expectedPrefix: 'WIFI STATUS '),
      );
      final photo = await captureWifiPhoto(
        id: DateTime.now().microsecondsSinceEpoch % 0xffffffff + 1,
        endpoint: endpoint,
        request: (command, prefix) =>
            queue.send(command, expectedPrefix: prefix),
        checkConnected: () {
          if (epoch != _epoch || !connected || !_foreground) {
            throw StateError('Đã hủy nhận ảnh.');
          }
        },
        checksum: (bytes) => compute(cameraCrc32, bytes),
        progress: (value) {
          if (epoch != _epoch) return;
          cameraProgress = value;
          _notify();
        },
      );
      cameraMessage =
          'Đã nhận ${photo.metadata.width} × ${photo.metadata.height}, CRC32 hợp lệ.';
      AppLog.instance.add(
        'CAMERA',
        cameraMessage,
        error: 'bytes=${photo.bytes.length}, route=Wi-Fi, mtu=$_mtu',
      );
      return photo;
    } catch (error, stack) {
      cameraMessage = 'Không nhận được ảnh: $error';
      AppLog.instance.add(
        'CAMERA',
        cameraMessage,
        level: 'ERROR',
        stack: stack,
      );
      rethrow;
    } finally {
      cameraBusy = false;
      cameraProgress = null;
      _notify();
    }
  }

  void update(AssistantState state, int count, int? progress, {bool? dark}) {
    final snapshot = AssistantSnapshot(
      state,
      count: count,
      progress: progress,
      dark: dark,
    );
    if (_desired == snapshot) return;
    _desired = snapshot;
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
          if (!connected || epoch != _epoch) return;
          if (value.startsWith('THEME ') && !_themeSupported) continue;
          try {
            await _commands!.send(value);
          } on CommandRejected catch (error) {
            if (!value.startsWith('THEME ') ||
                error.code != 'INVALID_COMMAND') {
              rethrow;
            }
            _themeSupported = false;
            message = 'Đã kết nối. Nạp firmware mới để đồng bộ giao diện.';
            _notify();
          }
        }
        if (epoch != _epoch) break;
        _sent = target;
        if (target == _desired) break;
      }
    } catch (error) {
      _lost(epoch, 'Đồng bộ trợ lý thất bại: $error');
    } finally {
      _syncing = false;
      if (connected && _sent != _desired) unawaited(_sync());
    }
  }

  Future<void> disconnect({
    bool sleep = false,
    bool cancelAttempt = true,
  }) async {
    if (cancelAttempt) ++_connectAttempt;
    _retry?.cancel();
    _heartbeat?.cancel();
    _wifiPoll?.cancel();
    _wifiRefresh = null;
    wifiState = null;
    wifiError = '';
    final wasConnected = connected;
    _stopPreview();
    connected = connecting = false;
    if (sleep && wasConnected) {
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
    _stopPreview();
    _disposed = true;
    _foreground = false;
    _retry?.cancel();
    _heartbeat?.cancel();
    _scanTimer?.cancel();
    _wifiPoll?.cancel();
    _commands?.close();
    unawaited(_cancelSubscription(_scan));
    unawaited(_cancelSubscription(_status));
    unawaited(_cancelSubscription(_notifications));
    unawaited(_cancelSubscription(_connection));
    super.dispose();
  }
}
