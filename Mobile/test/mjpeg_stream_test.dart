import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/mjpeg_stream.dart';

const mime = 'multipart/x-mixed-replace; boundary="vietocr-frame"';
final jpeg = Uint8List.fromList([
  255,
  216,
  ...ascii.encode('sample--vietocr-frame\r\n\r\n'),
  255,
  217,
]);
List<int> part(List<int> frame) => [
  ...ascii.encode(
    '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n',
  ),
  ...frame,
  13,
  10,
];

void main() {
  test(
    'separate flushed preamble and multipart CRLF do not create empty headers',
    () {
      final parser = MjpegParser(mime);
      expect(parser.add([13, 10]), isEmpty);
      expect(parser.add([13, 10, ...part(jpeg)]), [jpeg]);
    },
  );
  test(
    'native high quality frames larger than 128 KiB remain supported and bounded',
    () {
      final large = Uint8List.fromList([
        255,
        216,
        ...List.filled(900 * 1024, 120),
        255,
        217,
      ]);
      final wire = part(large), parser = MjpegParser(mime);
      final frames = <Uint8List>[];
      for (var at = 0; at < wire.length; at += 16384) {
        frames.addAll(
          parser.add(wire.sublist(at, (at + 16384).clamp(0, wire.length))),
        );
      }
      expect(frames, [large]);
    },
  );
  test(
    'multipart frames survive every split point and embedded boundaries',
    () {
      final wire = [13, 10, ...part(jpeg), ...part(jpeg)];
      for (var split = 1; split < wire.length; ++split) {
        final parser = MjpegParser(mime);
        expect(
          [
            ...parser.add(wire.sublist(0, split)),
            ...parser.add(wire.sublist(split)),
          ],
          [jpeg, jpeg],
        );
      }
      final parser = MjpegParser(mime);
      expect(
        [
          for (final byte in wire) ...parser.add([byte]),
        ],
        [jpeg, jpeg],
      );
    },
  );

  test('coalesced frames are parsed incrementally without growing a queue', () {
    final parser = MjpegParser(mime);
    expect(
      parser.add([for (var i = 0; i < 2000; ++i) ...part(jpeg)]).length,
      2000,
    );
  });

  test('invalid content types, huge headers and invalid JPEGs are bounded', () {
    for (final type in [
      'image/jpeg',
      'multipart/x-mixed-replace',
      'multipart/x-mixed-replace; boundary=${'a' * 71}',
    ]) {
      expect(() => MjpegParser(type), throwsFormatException);
    }
    for (final wire in [
      List.filled(MjpegParser.maxHeader + 1, 65),
      part(ascii.encode('not jpeg')),
      ascii.encode(
        '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${MjpegParser.maxFrame + 1}\r\n\r\n',
      ),
      ascii.encode('--vietocr-frame\r\nContent-Type: image/jpeg\r\n\r\n'),
      ascii.encode(
        '--vietocr-frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\nContent-Length: 4\r\n\r\n',
      ),
    ]) {
      expect(() => MjpegParser(mime).add(wire).toList(), throwsFormatException);
    }
  });
}
