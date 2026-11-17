import 'dart:async';

class OcrCancelled implements Exception {}

class CancellationToken {
  bool _cancelled = false;
  final _event = Completer<void>();
  bool get isCancelled => _cancelled;
  Future<void> get whenCancelled => _event.future;
  void cancel() {
    if (_cancelled) return;
    _cancelled = true;
    _event.complete();
  }

  void check() {
    if (_cancelled) throw OcrCancelled();
  }
}

Future<String> decodeTokens({
  required List<String> vocabulary,
  required int maxTokens,
  required CancellationToken cancel,
  required Future<int> Function(List<int>) next,
}) async {
  final tokens = <int>[1];
  for (var step = 0; step < maxTokens; step++) {
    cancel.check();
    final token = await next(tokens);
    cancel.check();
    if (token < 0 || token >= vocabulary.length) {
      throw StateError('Model trả mã ký tự không hợp lệ.');
    }
    if (token == 2) {
      return tokens.skip(1).map((value) => vocabulary[value]).join().trim();
    }
    tokens.add(token);
  }
  throw StateError('Dòng chữ quá dài. Hãy cắt ảnh thành các dòng ngắn hơn.');
}
