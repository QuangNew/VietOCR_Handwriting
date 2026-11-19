import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;
import 'engine.dart';
import 'cancellation.dart';
import 'image_processing.dart';
import 'transfer_file.dart';
import '../services/vietocr_remote.dart';

class UnavailableServerEngine implements OcrEngine {
  @override
  bool get loaded => false;
  @override
  Future<void> close() async {}
  @override
  Future<String> recognize(
    String path, {
    required bool split,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async {
    cancel.check();
    throw StateError(
      'Mở OCR Server, nhập địa chỉ máy host và đăng nhập Google.',
    );
  }
}

List<int> _rotateForServer((String, int) input) {
  final (path, rotation) = input;
  final image = decodePhoto(File(path).readAsBytesSync());
  return img.encodePng(
    img.copyRotate(image, angle: (rotation % 4) * 90),
    level: 3,
  );
}

class RemoteEngine
    implements OcrEngine, AcceptedResultRecovery, ConcurrentOcrEngine {
  RemoteEngine(
    String origin,
    String key, {
    bool allowInsecureLan = false,
    Future<String> Function()? tokenProvider,
  }) : _client = VietOcrRemote(
         origin,
         key,
         allowInsecureLan: allowInsecureLan,
         tokenProvider: tokenProvider,
       );
  final VietOcrRemote _client;
  bool _closed = false;
  @override
  int get parallelRequests => 2;
  Future<File> _image(String path, int rotation, {bool create = true}) async {
    final original = File(path);
    if (rotation % 4 == 0) return original;
    final derived = File('$path.rotate-${rotation % 4}.png');
    if (!await derived.exists() && create) {
      final bytes = await compute(_rotateForServer, (path, rotation));
      final temporary = File('${derived.path}.tmp');
      await temporary.writeAsBytes(bytes, flush: true);
      await temporary.rename(derived.path);
    }
    return derived;
  }

  @override
  Future<({String state, String text, String error})?> recoverAccepted(
    String path, {
    required int rotation,
  }) async {
    if (_closed) return null;
    final image = await automaticTransfer(
      await _image(path, rotation, create: false),
      create: false,
    );
    if (!await image.exists()) return null;
    final result = await _client.recoverAccepted(image);
    if (result == null) return null;
    return (
      state: result['state'] as String,
      text: result['text'] as String? ?? '',
      error: result['error'] as String? ?? '',
    );
  }

  @override
  bool get loaded => !_closed;
  @override
  Future<String> recognize(
    String path, {
    required bool split,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  }) async {
    if (_closed) throw OcrCancelled();
    cancel.check();
    try {
      if (rotation % 4 != 0) {
        progress('Đang xoay ảnh trước khi gửi…', null);
      }
      progress('Đang tự tối ưu ảnh · giữ bản gốc…', null);
      final image = await automaticTransfer(await _image(path, rotation));
      cancel.check();
      progress('Đang gửi ảnh đến OCR Server…', null);
      final text = await _client.recognize(
        image,
        layout: split ? 'auto' : 'line',
        cancelled: () => cancel.isCancelled || _closed,
        onState: (state) => progress(
          state == 'queued'
              ? 'Đang chờ worker trên server…'
              : state == 'running'
              ? 'Server đang nhận diện…'
              : state.startsWith('uploading')
              ? 'Đang gửi ảnh qua Raspberry… $state'
              : state == 'awaiting_upload'
              ? 'Đang chờ lượt gửi…'
              : 'Đang nhận kết quả.',
          null,
        ),
      );
      cancel.check();
      return text;
    } catch (error) {
      cancel.check();
      if (_closed) throw OcrCancelled();
      if (error is RemoteOcrException) rethrow;
      throw StateError(error.toString());
    }
  }

  @override
  Future<void> close() async {
    _closed = true;
    _client.close();
  }
}
