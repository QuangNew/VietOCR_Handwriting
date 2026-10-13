// Run with `dart run tools/prepare_fixtures.dart [image paths...]`.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:vietocr_mobile/ocr/image_processing.dart';

void main(List<String> args) {
  final paths = args.isEmpty
      ? ['assets/samples/test.jpg', 'assets/samples/test2.jpg']
      : args;
  final output = Directory('build/verification')..createSync(recursive: true);
  final rows = <Map<String, Object>>[];
  for (var index = 0; index < paths.length; index++) {
    final path = paths[index];
    for (final split in [false, true]) {
      final lines = prepareLines((File(path).readAsBytesSync(), split, 0));
      final tensors = <Map<String, Object>>[];
      for (var line = 0; line < lines.length; line++) {
        final tensor = makeTensor(lines[line]);
        final name = '$index-${split ? 'lines' : 'whole'}-$line.f32';
        final bytes = ByteData(tensor.values.length * 4);
        for (var i = 0; i < tensor.values.length; i++) {
          bytes.setFloat32(i * 4, tensor.values[i], Endian.little);
        }
        File(
          '${output.path}/$name',
        ).writeAsBytesSync(bytes.buffer.asUint8List());
        tensors.add({'file': name, 'width': tensor.width});
      }
      rows.add({'source': path, 'split': split, 'tensors': tensors});
    }
  }
  File('${output.path}/fixtures.json').writeAsStringSync(jsonEncode(rows));
  stdout.writeln('Prepared ${rows.length} mobile preprocessing cases.');
}
