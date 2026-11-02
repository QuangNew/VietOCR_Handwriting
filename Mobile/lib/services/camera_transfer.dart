import 'dart:async';
import 'dart:typed_data';
import 'ble_protocol.dart';

const cameraMaxBytes = 2 * 1024 * 1024;

/// SOF dimensions, not the resized widget or metadata from a previous mode.
(int, int)? cameraJpegSize(Uint8List data) {
  if (data.length < 4 || data[0] != 255 || data[1] != 216) return null;
  var at = 2;
  while (at + 3 < data.length) {
    if (data[at++] != 255) return null;
    while (at < data.length && data[at] == 255) {
      ++at;
    }
    if (at >= data.length) return null;
    final marker = data[at++];
    if (marker == 218 || marker == 217) return null;
    if (marker == 1 || (marker >= 208 && marker <= 215)) continue;
    if (at + 2 > data.length) return null;
    final length = (data[at] << 8) | data[at + 1];
    if (length < 2 || at + length > data.length) return null;
    if (marker >= 192 &&
        marker <= 207 &&
        marker != 196 &&
        marker != 200 &&
        marker != 204) {
      if (length < 8) return null;
      final height = (data[at + 3] << 8) | data[at + 4],
          width = (data[at + 5] << 8) | data[at + 6];
      return width > 0 && height > 0 ? (width, height) : null;
    }
    at += length;
  }
  return null;
}

class CameraMetadata {
  const CameraMetadata(this.id, this.size, this.crc, this.width, this.height);
  final int id, size, crc, width, height;
  factory CameraMetadata.parse(String line, int expectedId) {
    final parts = line.split(' ');
    if (parts.length != 6 || parts[0] != 'CAM') {
      throw const FormatException('Sai metadata camera.');
    }
    final result = CameraMetadata(
      int.parse(parts[1]),
      int.parse(parts[2]),
      int.parse(parts[3], radix: 16),
      int.parse(parts[4]),
      int.parse(parts[5]),
    );
    if (result.id != expectedId ||
        result.size < 4 ||
        result.size > cameraMaxBytes ||
        result.crc < 0 ||
        result.crc > 0xffffffff ||
        result.width < 1 ||
        result.width > 4096 ||
        result.height < 1 ||
        result.height > 4096 ||
        result.width * result.height > 8000000) {
      throw const FormatException(
        'Metadata camera vượt giới hạn hoặc sai ID ảnh.',
      );
    }
    return result;
  }
}

class CameraPhoto {
  const CameraPhoto(this.metadata, this.bytes);
  final CameraMetadata metadata;
  final Uint8List bytes;
}

final _crcTable = List<int>.generate(256, (byte) {
  var value = byte;
  for (var bit = 0; bit < 8; bit++) {
    value = (value >>> 1) ^ ((value & 1) == 0 ? 0 : 0xedb88320);
  }
  return value & 0xffffffff;
});
int cameraCrc32(Uint8List data) {
  var value = 0xffffffff;
  for (final byte in data) {
    value = (value >>> 8) ^ _crcTable[(value ^ byte) & 255];
  }
  return (value ^ 0xffffffff) & 0xffffffff;
}

Future<CameraPhoto> receiveCameraPhoto({
  required int id,
  required int mtu,
  required Future<String> Function(String command, String? prefix) request,
  required Future<List<int>> Function(Uint8List selector) readChunk,
  required void Function(double fraction) progress,
  required void Function() checkConnected,
  Future<int> Function(Uint8List bytes)? checksum,
  Duration captureTimeout = const Duration(seconds: 25),
}) async {
  await request('CAM SHOT $id', null);
  try {
    final captureWatch = Stopwatch()..start();
    late CameraMetadata metadata;
    while (true) {
      checkConnected();
      try {
        metadata = CameraMetadata.parse(
          await request('CAM META $id', 'CAM $id '),
          id,
        );
        break;
      } on CommandRejected catch (error) {
        if (error.code != 'CAMERA_BUSY' ||
            captureWatch.elapsed > captureTimeout) {
          rethrow;
        }
        await Future<void>.delayed(const Duration(milliseconds: 150));
      }
    }
    final bytes = Uint8List(metadata.size);
    final count = (mtu - 9).clamp(14, 480);
    final heartbeat = Stopwatch()..start();
    final transferWatch = Stopwatch()..start();
    for (var offset = 0; offset < bytes.length;) {
      checkConnected();
      if (transferWatch.elapsed > const Duration(minutes: 4)) {
        throw TimeoutException(
          'Truyền ảnh BLE quá 4 phút. Hãy đưa thiết bị lại gần.',
        );
      }
      final wanted = (bytes.length - offset).clamp(1, count);
      final selector = ByteData(12)
        ..setUint32(0, id, Endian.little)
        ..setUint32(4, offset, Endian.little)
        ..setUint32(8, wanted, Endian.little);
      for (var attempt = 0; attempt < 3; attempt++) {
        final packet = Uint8List.fromList(
          await readChunk(
            selector.buffer.asUint8List(),
          ).timeout(const Duration(seconds: 8)),
        );
        final header = ByteData.sublistView(packet);
        if (packet.length == wanted + 8 &&
            header.getUint32(0, Endian.little) == id &&
            header.getUint32(4, Endian.little) == offset) {
          bytes.setRange(offset, offset + wanted, packet, 8);
          offset += wanted;
          break;
        }
        if (attempt == 2) {
          throw const FormatException(
            'Ảnh BLE sai offset/độ dài sau 3 lần đọc.',
          );
        }
      }
      progress(offset / bytes.length);
      if (heartbeat.elapsed > const Duration(seconds: 4)) {
        await request('PING', null);
        heartbeat.reset();
      }
    }
    final crc = checksum == null ? cameraCrc32(bytes) : await checksum(bytes);
    if (crc != metadata.crc ||
        bytes[0] != 0xff ||
        bytes[1] != 0xd8 ||
        bytes[bytes.length - 2] != 0xff ||
        bytes.last != 0xd9) {
      throw const FormatException(
        'Ảnh BLE hỏng hoặc sai CRC32; chưa đưa ảnh vào OCR.',
      );
    }
    return CameraPhoto(metadata, bytes);
  } finally {
    try {
      await request('CAM RELEASE $id', null);
    } catch (_) {
      /* disconnect/TTL releases it */
    }
  }
}
