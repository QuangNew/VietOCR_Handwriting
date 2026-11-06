import 'decoder.dart';

/// The client has one engine: remote OCR. No model/tensors/native OCR service.
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
