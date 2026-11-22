import 'cancellation.dart';

/// The client has one engine: remote OCR. No model/tensors/native OCR service.
abstract class OcrEngine {
  bool get loaded;
  Future<String> recognize(
    String path, {
    required bool split,
    bool correct = false,
    required int rotation,
    required CancellationToken cancel,
    required void Function(String, double?) progress,
  });
  Future<void> close();
}

/// Optional read-only recovery, separate from the explicit-send engine method.
abstract interface class AcceptedResultRecovery {
  Future<({String state, String text, String error})?> recoverAccepted(
    String path, {
    required int rotation,
  });
}

abstract interface class ConcurrentOcrEngine {
  int get parallelRequests;
}
