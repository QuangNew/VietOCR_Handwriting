import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'decoder.dart';
import 'image_processing.dart';
import '../services/app_log.dart';

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

// Android's private :ocr process owns the ONNX sessions and the entire token loop.
// Only bounded tensor files and final text cross IPC, never model buffers.
class OfflineEngine implements OcrEngine {
  OfflineEngine({Future<Directory> Function()? temporaryDirectory})
    : _temporaryDirectory = temporaryDirectory ?? getTemporaryDirectory;
  final Future<Directory> Function() _temporaryDirectory;
  static const channel = MethodChannel('vietocr/ocr');
  bool _loaded = false, _disposed = false;
  Future<String>? _active;
  Future<void>? _loading;
  CancellationToken? _token;
  @override
  bool get loaded => _loaded;

  Future<T?> _request<T>(
    String method,
    Map<String, Object>? arguments,
    CancellationToken cancel,
  ) async {
    cancel.check();
    var finished = false;
    final operation = channel.invokeMethod<T>(method, arguments);
    final cancelled = cancel.whenCancelled.then<T?>((_) async {
      if (!finished) {
        _loaded = false;
        await channel.invokeMethod<void>('reset');
        throw OcrCancelled();
      }
      return null;
    });
    try {
      return await Future.any([operation, cancelled]);
    } catch (_) {
      _loaded = false;
      cancel.check();
      rethrow;
    } finally {
      finished = true;
    }
  }

  Future<void> load(
    void Function(String, double?) progress, {
    CancellationToken? cancel,
  }) async {
    if (_disposed) throw OcrCancelled();
    if (_loaded) return;
    final token = cancel ?? CancellationToken();
    _loading ??= () async {
      AppLog.instance.add('OCR', 'Bắt đầu nạp model');
      progress('Đang chuẩn bị bộ nhận diện…', null);
      await _request<String>('load', null, token);
      token.check();
      _loaded = true;
      AppLog.instance.add('OCR', 'Model sẵn sàng');
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
    if (_disposed) throw OcrCancelled();
    cancel.check();
    if (!loaded) await load((_, _) {}, cancel: cancel);
    final directory = Directory(
      '${(await _temporaryDirectory()).path}/ocr-input',
    );
    await directory.create(recursive: true);
    final file = File(
      '${directory.path}/line_${DateTime.now().microsecondsSinceEpoch}.f32',
    );
    try {
      final data = line.values;
      await file.writeAsBytes(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
        flush: true,
      );
      final result = await _request<String>('line', {
        'path': file.path,
        'width': line.width,
      }, cancel);
      cancel.check();
      return result ?? '';
    } finally {
      if (await file.exists()) await file.delete();
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
      progress('Đang chuẩn bị ảnh…', null);
      final watch = Stopwatch()..start();
      AppLog.instance.add(
        'OCR',
        'Chuẩn bị ảnh: split=$split, rotation=$rotation',
      );
      // File reading + decoding + per-line resize all stay off the Flutter isolate.
      final prepared = await compute(prepareDocument, (path, split, rotation));
      AppLog.instance.add(
        'OCR',
        'Tách được ${prepared.length} dòng sau ${watch.elapsedMilliseconds} ms',
        error: 'tensor widths=${prepared.map((line) => line.width).join(",")}',
      );
      cancel.check();
      await load(progress, cancel: cancel);
      final results = <String>[];
      for (var i = 0; i < prepared.length; i++) {
        cancel.check();
        progress(
          'Đang đọc dòng ${i + 1}/${prepared.length}',
          i / prepared.length,
        );
        final text = await recognizeTensor(prepared[i], cancel);
        AppLog.instance.add(
          'OCR',
          'Dòng ${i + 1}/${prepared.length}: ${text.length} ký tự',
        );
        if (text.isEmpty) {
          AppLog.instance.add(
            'OCR',
            'Dòng ${i + 1} không có kết quả, tiếp tục các dòng còn lại',
            level: 'WARN',
          );
        } else {
          results.add(text);
        }
        progress(
          'Đã đọc ${i + 1}/${prepared.length} dòng',
          (i + 1) / prepared.length,
        );
      }
      if (results.isEmpty) {
        throw StateError(
          'AI không đọc được chữ trong ảnh. Thử chế độ Một dòng hoặc cắt sát vùng chữ; xem tab Log để biết bước xử lý.',
        );
      }
      AppLog.instance.add(
        'OCR',
        'Hoàn tất ảnh sau ${watch.elapsedMilliseconds} ms',
      );
      return results.join('\n');
    }();
    _active = operation;
    return operation.whenComplete(() {
      _active = null;
      _token = null;
    });
  }

  Future<void> releaseMemory() async {
    if (_active != null) return;
    _loaded = false;
    await channel.invokeMethod<void>('reset');
  }

  static Future<String> diagnostics() async =>
      await channel.invokeMethod<String>('diagnostics') ?? '{}';

  @override
  Future<void> close() async {
    _disposed = true;
    _token?.cancel();
    try {
      await _active;
      await _loading;
    } catch (_) {
      /* failure already surfaced */
    }
    await releaseMemory();
  }
}
