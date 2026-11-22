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
