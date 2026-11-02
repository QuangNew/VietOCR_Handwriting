import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/camera_transfer.dart';
import 'package:vietocr_mobile/services/ble_protocol.dart';

void main() {
  test('CRC32 matches firmware and Python golden vector', () {
    expect(cameraCrc32(Uint8List.fromList('123456789'.codeUnits)), 0xcbf43926);
  });
  Future<CameraPhoto> run({
    int mtu = 23,
    bool corrupt = false,
    bool wrongFirst = false,
  }) async {
    final jpeg = Uint8List.fromList([
      0xff,
      0xd8,
      ...List.generate(770, (i) => i % 256),
      0xff,
      0xd9,
    ]);
    final commands = <String>[];
    var busy = true;
    final result = await receiveCameraPhoto(
      id: 42,
      mtu: mtu,
      progress: (_) {},
      checkConnected: () {},
      request: (command, prefix) async {
        commands.add(command);
        if (command.startsWith('CAM META')) {
          if (busy) {
            busy = false;
            throw const CommandRejected('ERR CAMERA_BUSY');
          }
          return 'CAM 42 ${jpeg.length} ${cameraCrc32(jpeg).toRadixString(16)} 320 240';
        }
        return 'OK $command';
      },
      readChunk: (selector) async {
        final value = ByteData.sublistView(selector);
        final offset = value.getUint32(4, Endian.little),
            count = value.getUint32(8, Endian.little);
        expect(count + 8, lessThanOrEqualTo(mtu - 1));
        final header = ByteData(8)
          ..setUint32(0, 42, Endian.little)
          ..setUint32(4, wrongFirst ? offset + 1 : offset, Endian.little);
        wrongFirst = false;
        final chunk = jpeg.sublist(offset, offset + count);
        if (corrupt && offset == 0) chunk[0] = 0;
        return [...header.buffer.asUint8List(), ...chunk];
      },
    );
    expect(commands.last, 'CAM RELEASE 42');
    expect(result.bytes, jpeg);
    return result;
  }

  test('minimum MTU and negotiated MTU preserve the entire JPEG', () async {
    for (final mtu in [23, 247, 517]) {
      await run(mtu: mtu);
    }
  });
  test('wrong offset is retried before advancing', () async {
    await run(wrongFirst: true);
  });
  test('corrupt payload cannot be admitted to OCR', () async {
    await expectLater(run(corrupt: true), throwsFormatException);
  });
  test('metadata rejects excessive allocation and stale image ID', () {
    for (final line in ['CAM 42 2097153 0 320 240', 'CAM 41 100 0 320 240']) {
      expect(() => CameraMetadata.parse(line, 42), throwsFormatException);
    }
  });
}
