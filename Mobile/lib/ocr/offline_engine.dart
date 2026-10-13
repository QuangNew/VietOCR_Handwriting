import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_onnxruntime/flutter_onnxruntime.dart';
import 'package:path_provider/path_provider.dart';
import 'decoder.dart';
import 'image_processing.dart';

abstract class OcrEngine {
  bool get loaded;
  Future<String> recognize(
    String path, {
    required bool split,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  });
  Future<void> close();
}

class OfflineEngine implements OcrEngine {
  final OnnxRuntime _runtime = OnnxRuntime();
  OrtSession? _encoder, _decoder;
  Map<String, dynamic>? _manifest;
  Future<void>? _loading;
  Future<String>? _active;
  bool _disposed = false;
  CancellationToken? _token;
  @override
  bool get loaded => _encoder != null && _decoder != null;

  Future<String> _modelPath(String role) async {
    final model = _manifest!['models'][role] as Map<String, dynamic>;
    final name = model['file'] as String, hash = model['sha256'] as String;
    final support = await getApplicationSupportDirectory();
    final file = File('${support.path}/models/${hash.substring(0, 16)}_$name');
    Future<bool> valid() async =>
        await file.exists() &&
        await file.length() == model['bytes'] &&
        (await sha256.bind(file.openRead()).first).toString() == hash;
    if (!await valid()) {
      await file.parent.create(recursive: true);
      final data = await rootBundle.load('assets/models/$name');
      final temporary = File('${file.path}.tmp');
      await temporary.writeAsBytes(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
        flush: true,
      );
      if (await file.exists()) await file.delete();
      await temporary.rename(file.path);
      if (!await valid()) {
        throw StateError('File model không toàn vẹn. Hãy cài lại ứng dụng.');
      }
    }
    return file.path;
  }

  Future<void> load(void Function(String, double?) progress) async {
    if (loaded) return;
    if (_disposed) throw OcrCancelled();
    _loading ??= () async {
      try {
        progress('Đang chuẩn bị model trên máy…', null);
        _manifest =
            jsonDecode(
                  await rootBundle.loadString('assets/models/manifest.json'),
                )
                as Map<String, dynamic>;
        final options = OrtSessionOptions(
          intraOpNumThreads: 2,
          interOpNumThreads: 1,
          providers: [OrtProvider.CPU],
        );
        _encoder = await _runtime.createSession(
          await _modelPath('encoder'),
          options: options,
        );
        _decoder = await _runtime.createSession(
          await _modelPath('decoder'),
          options: options,
        );
      } catch (_) {
        await _encoder?.close();
        await _decoder?.close();
        _encoder = _decoder = null;
        rethrow;
      }
    }();
    try {
      await _loading;
    } finally {
      _loading = null;
    }
  }

  Future<String> recognizeTensor(
    LineTensor line,
    CancellationToken cancel,
  ) async {
    cancel.check();
    final input = await OrtValue.fromList(line.values, [1, 3, 32, line.width]);
    Map<String, OrtValue> memory = {};
    try {
      memory = await _encoder!.run({'image': input});
      return await decodeTokens(
        vocabulary: List<String>.from(_manifest!['vocabulary']),
        maxTokens: _manifest!['max_tokens'] as int,
        cancel: cancel,
        next: (tokens) async {
          final ids = await OrtValue.fromList(Int64List.fromList(tokens), [
            tokens.length,
            1,
          ]);
          Map<String, OrtValue> output = {};
          try {
            output = await _decoder!.run({
              'tokens': ids,
              'memory': memory['memory']!,
            });
            final values = await output['next_token']!.asFlattenedList();
            return (values.single as num).toInt();
          } finally {
            await ids.dispose();
            for (final value in output.values) {
              await value.dispose();
            }
          }
        },
      );
    } finally {
      await input.dispose();
      for (final value in memory.values) {
        await value.dispose();
      }
    }
  }

  @override
  Future<String> recognize(
    String path, {
    required bool split,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) {
    if (_active != null) throw StateError('Một lượt nhận diện đang chạy.');
    if (_disposed) throw OcrCancelled();
    _token = cancel;
    final operation = () async {
      cancel.check();
      progress('Đang chuẩn bị ảnh…', null);
      final lines = await compute(prepareLines, (
        await File(path).readAsBytes(),
        split,
        rotation,
      ));
      cancel.check();
      await load(progress);
      cancel.check();
      final results = <String>[];
      for (var i = 0; i < lines.length; i++) {
        cancel.check();
        progress('Đang đọc dòng ${i + 1}/${lines.length}', i / lines.length);
        final tensor = await compute(makeTensor, lines[i]);
        cancel.check();
        final text = await recognizeTensor(tensor, cancel);
        if (text.isEmpty) {
          throw StateError('Không đọc được dòng ${i + 1}. Thử chụp rõ hơn.');
        }
        results.add(text);
        progress(
          'Đã đọc ${i + 1}/${lines.length} dòng',
          (i + 1) / lines.length,
        );
      }
      return results.join('\n');
    }();
    _active = operation;
    return operation.whenComplete(() {
      _active = null;
      _token = null;
    });
  }

  @override
  Future<void> close() async {
    _disposed = true;
    _token?.cancel();
    try {
      await _active;
    } catch (_) {
      /* An interrupted image is discarded. */
    }
    try {
      await _loading;
    } catch (_) {
      /* Failed initialization was already cleaned up. */
    }
    await _encoder?.close();
    await _decoder?.close();
    _encoder = _decoder = null;
  }
}
