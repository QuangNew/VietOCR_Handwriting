import 'dart:async';
import 'package:flutter/foundation.dart';
import 'camera_transfer.dart';

/// Keeps the received original until it has actually been saved to the queue.
/// Timeout, Skip and Close all share one commit, including overlapping taps.
class CaptureReview extends ChangeNotifier {
  CaptureReview({required this.enqueue, required this.resume});
  final Future<void> Function(CameraPhoto) enqueue;
  final Future<void> Function() resume;
  CameraPhoto? photo;
  bool saving = false;
  Object? error;
  Timer? _timer;
  Future<void>? _commit;
  bool _closed = false, _disposed = false;

  void show(CameraPhoto value) {
    if (photo != null || saving || _closed) {
      throw StateError('Ảnh trước chưa vào hàng đợi.');
    }
    photo = value;
    error = null;
    _notify();
    _timer = Timer(const Duration(seconds: 3), () => unawaited(finish()));
  }

  Future<void> finish({bool reopen = true}) {
    _timer?.cancel();
    _timer = null;
    if (_commit != null) return _commit!;
    final current = photo;
    if (current == null) return Future.value();
    saving = true;
    _notify();
    final operation = _save(current, reopen);
    _commit = operation;
    return operation.whenComplete(() => _commit = null);
  }

  Future<void> _save(CameraPhoto current, bool reopen) async {
    try {
      await enqueue(current);
      photo = null;
      error = null;
    } catch (failure) {
      error = failure;
    } finally {
      saving = false;
      _notify();
    }
    if (photo == null && reopen && !_closed && !_disposed) {
      try {
        await resume();
      } catch (failure) {
        error = failure;
        _notify();
      }
    }
  }

  Future<void> close() async {
    _closed = true;
    await finish(reopen: false);
    if (photo != null) {
      _closed = false; // Saving failed; allow retry in this view.
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = _closed = true;
    _timer?.cancel();
    super.dispose();
  }
}
