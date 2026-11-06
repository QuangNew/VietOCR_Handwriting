import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:image/image.dart' as img;
import 'engine.dart';
import 'decoder.dart';
import 'image_processing.dart';
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

class RemoteEngine implements OcrEngine {
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
    File? temporary;
    try {
      var image = File(path);
      if (rotation % 4 != 0) {
        progress('Đang xoay ảnh trước khi gửi…', null);
        final bytes = await compute(_rotateForServer, (path, rotation));
        cancel.check();
        temporary = File(
          '${(await getTemporaryDirectory()).path}/server-${DateTime.now().microsecondsSinceEpoch}.png',
        );
        await temporary.writeAsBytes(bytes, flush: true);
        image = temporary;
      }
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
              : 'Đã nhận kết quả.',
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
    } finally {
      if (temporary != null && await temporary.exists()) {
        await temporary.delete();
      }
    }
  }

  @override
  Future<void> close() async {
    _closed = true;
    _client.close();
  }
}
