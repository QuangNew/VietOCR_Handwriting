import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'transfer_image.dart';

Future<void> _encoder = Future<void>.value();

/// The original and its OCR request cache remain stable across retries/restarts.
/// An old upload must resume its original bytes, never acquire a new derivative.
Future<File> automaticTransfer(File original, {bool create = true}) async {
  if (await File('${original.path}.ocr-v2.json').exists()) return original;
  final derived = File('${original.path}.transfer-v1');
  final unchanged = File('${original.path}.transfer-v1.original');
  if (await derived.exists()) return derived;
  if (!create || await unchanged.exists()) return original;
  final previous = _encoder, finished = Completer<void>();
  _encoder = finished.future;
  await previous;
  try {
    if (await derived.exists()) return derived;
    if (await unchanged.exists()) return original;
    final candidate = await compute(optimizeTransfer, (
      await original.readAsBytes(),
      0,
    ));
    if (candidate == null) {
      await unchanged.writeAsString('original', flush: true);
      return original;
    }
    final pending = File('${derived.path}.tmp');
    await pending.writeAsBytes(candidate.bytes, flush: true);
    await pending.rename(derived.path);
    return derived;
  } finally {
    finished.complete();
  }
}
