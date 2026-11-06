import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'camera_transfer.dart';
import 'mjpeg_stream.dart';
import 'wifi_camera.dart' show CameraNetworkException;

class _Parts {
  _Parts(int size, this.crc, this.width, this.height)
    : bytes = Uint8List(size),
      seen = Uint8List((size + 1167) ~/ 1168);
  final Uint8List bytes, seen;
  final int crc, width, height;
  int received = 0;
}

/// At most two incomplete frames; stale, duplicate and corrupt packets are dropped.
class UdpJpegAssembler {
  UdpJpegAssembler(this.stream);
  final int stream;
  final _pending = <int, _Parts>{};
  int completed = 0, corrupt = 0;
  int get pendingFrames => _pending.length;

  Uint8List? add(Uint8List packet) {
    if (packet.length < 32 || packet.length > 1200) return null;
    if (packet[0] != 86 ||
        packet[1] != 79 ||
        packet[2] != 74 ||
        packet[3] != 49) {
      return null;
    }
    final header = ByteData.sublistView(packet);
    final session = header.getUint32(4, Endian.little),
        sequence = header.getUint32(8, Endian.little),
        total = header.getUint32(12, Endian.little),
        offset = header.getUint32(16, Endian.little),
        crc = header.getUint32(20, Endian.little),
        width = header.getUint16(24, Endian.little),
        height = header.getUint16(26, Endian.little),
        count = header.getUint16(28, Endian.little);
    if (session != stream ||
        sequence == 0 ||
        sequence <= completed ||
        total < 4 ||
        total > cameraMaxBytes ||
        offset >= total ||
        offset % 1168 != 0 ||
        count != (total - offset).clamp(0, 1168) ||
        packet.length != 32 + count ||
        width < 160 ||
        width > 2592 ||
        width * 3 != height * 4 ||
        header.getUint16(30, Endian.little) != 0) {
      return null;
    }
    if (!_pending.containsKey(sequence)) {
      if (_pending.length >= 2) {
        final oldest = _pending.keys.reduce((a, b) => a < b ? a : b);
        if (sequence < oldest) return null;
        _pending.remove(oldest);
      }
      _pending[sequence] = _Parts(total, crc, width, height);
    }
    final part = _pending[sequence]!;
    if (part.bytes.length != total ||
        part.crc != crc ||
        part.width != width ||
        part.height != height) {
      return null;
    }
    final index = offset ~/ 1168;
    if (part.seen[index] != 0) return null;
    part.bytes.setRange(offset, offset + count, packet, 32);
    part.seen[index] = 1;
    part.received += count;
    if (part.received != total) return null;
    _pending.remove(sequence);
    final bytes = part.bytes;
    if (cameraCrc32(bytes) != crc ||
        bytes[0] != 255 ||
        bytes[1] != 216 ||
        bytes[total - 2] != 255 ||
        bytes[total - 1] != 217) {
      corrupt++;
      return null;
    }
    completed = sequence;
    _pending.removeWhere((key, _) => key <= sequence);
    return bytes;
  }
}

/// Same stream interface as MJPEG for lifecycle/testing; wire transport is VOJ1 UDP.
class UdpCameraConnection extends MjpegConnection {
  UdpCameraConnection(
    super.endpoint, {
    this.sourcePort = 82,
    this.renewAfter = const Duration(seconds: 20),
    this.firstTimeout = const Duration(seconds: 16),
    this.idleTimeout = const Duration(seconds: 6),
  });
  final int sourcePort;
  final Duration renewAfter, firstTimeout, idleTimeout;
  RawDatagramSocket? _socket;
  HttpClient? _http;
  bool _closed = false;
  Timer? _renew, _watchdog;
  static Future<void> _controlTail = Future<void>.value();

  @override
  void close() {
    _closed = true;
    _renew?.cancel();
    _watchdog?.cancel();
    _socket?.close();
    _http?.close(force: true);
    // Firmware is closed by CAM CLOSE/SHOT/disconnect. A late port=0 request
    // from this old reader must never cancel the next reader's lease.
  }

  Future<int> _activate(int port) {
    final next = _controlTail.then((_) async {
      if (_closed) throw StateError('Preview đã đóng.');
      final client = _http!;
      final request = await client
          .postUrl(Uri.parse('http://${endpoint.ip}/stream/udp'))
          .timeout(const Duration(seconds: 4));
      request.followRedirects = false;
      request.persistentConnection = false;
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer ${endpoint.token}',
      );
      request.headers.contentType = ContentType.json;
      final body = utf8.encode(jsonEncode({'port': port}));
      request.contentLength = body.length;
      request.add(body);
      final response = await request.close().timeout(
        const Duration(seconds: 4),
      );
      final data = <int>[];
      await for (final chunk in response.timeout(const Duration(seconds: 4))) {
        if (data.length + chunk.length > 1024) {
          throw const FormatException('Phản hồi UDP quá lớn.');
        }
        data.addAll(chunk);
      }
      if (response.statusCode != 200) {
        throw StateError(
          'Preview UDP HTTP ${response.statusCode}. Cần firmware OV5640 3.0.0.',
        );
      }
      final value = jsonDecode(utf8.decode(data));
      if (value is! Map ||
          value['active'] != true ||
          value['stream'] is! int ||
          (value['stream'] as int) < 1 ||
          (value['stream'] as int) > 0xffffffff ||
          value['header_bytes'] != 32 ||
          value['datagram_bytes'] != 1200 ||
          value['lease_seconds'] != 60) {
        throw const FormatException(
          'Sai phản hồi UDP. Cập nhật firmware OV5640.',
        );
      }
      return value['stream'] as int;
    });
    _controlTail = next.then<void>(
      (_) {},
      onError: (Object _, StackTrace _) {},
    );
    return next;
  }

  @override
  Stream<Uint8List> frames() async* {
    if (_closed) return;
    RawDatagramSocket? socket;
    Object? failure;
    try {
      _http = HttpClient()
        ..connectionTimeout = const Duration(seconds: 3)
        ..findProxy = (_) => 'DIRECT';
      socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      _socket = socket;
      socket.writeEventsEnabled = false;
      // One JPEG arrives as a burst of datagrams. The small Windows default
      // receive buffer can lose a fragment before Dart drains the socket.
      // Android/Linux SO_RCVBUF=8; Winsock/BSD SO_RCVBUF=0x1002.
      socket.setRawOption(
        RawSocketOption.fromInt(
          RawSocketOption.levelSocket,
          Platform.isAndroid || Platform.isLinux ? 8 : 0x1002,
          1024 * 1024,
        ),
      );
      if (_closed) return;
      final peer = InternetAddress(Uri.parse('http://${endpoint.ip}').host);
      var decoder = UdpJpegAssembler(await _activate(socket.port));
      if (_closed) return;
      socket.send(utf8.encode('VOJ1'), peer, sourcePort);
      final watch = Stopwatch()..start();
      var lastFrame = Duration.zero,
          lastRenew = Duration.zero,
          received = false,
          renewing = false;
      _watchdog = Timer.periodic(const Duration(seconds: 1), (_) {
        if (watch.elapsed - lastFrame >
            (received ? idleTimeout : firstTimeout)) {
          failure = TimeoutException(
            'Không nhận được JPEG UDP hợp lệ. Kiểm tra cùng Wi-Fi và UDP 82.',
          );
          socket?.close();
        }
      });
      _renew = Timer.periodic(renewAfter, (_) async {
        if (_closed || renewing) return;
        renewing = true;
        try {
          final id = await _activate(socket!.port);
          if (!_closed) {
            if (id != decoder.stream) decoder = UdpJpegAssembler(id);
            lastRenew = watch.elapsed;
            socket.send(utf8.encode('VOJ1'), peer, sourcePort);
          }
        } catch (error) {
          if (!_closed) {
            final transient =
                error is SocketException ||
                error is TimeoutException ||
                error is HttpException ||
                error is CameraNetworkException;
            if (!transient ||
                watch.elapsed - lastRenew >= const Duration(seconds: 50)) {
              failure = error;
              socket?.close();
            }
          }
        } finally {
          renewing = false;
        }
      });
      await for (final event in socket) {
        if (_closed) return;
        if (event != RawSocketEvent.read) continue;
        for (var count = 0; count < 64; count++) {
          final packet = socket.receive();
          if (packet == null) break;
          if (packet.address.address != peer.address ||
              packet.port != sourcePort) {
            continue;
          }
          final frame = decoder.add(packet.data);
          if (frame != null) {
            lastFrame = watch.elapsed;
            received = true;
            yield frame;
          }
        }
      }
      if (!_closed && failure != null) throw failure!;
    } on SocketException {
      if (!_closed) {
        throw StateError(
          'Không nhận được preview UDP. Điện thoại và ESP32 cần cùng Wi-Fi.',
        );
      }
    } catch (_) {
      if (!_closed) rethrow;
    } finally {
      _renew?.cancel();
      _watchdog?.cancel();
      socket?.close();
      _http?.close(force: true);
      _socket = null;
      _http = null;
    }
  }
}
