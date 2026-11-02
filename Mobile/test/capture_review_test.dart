import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/camera_transfer.dart';
import 'package:vietocr_mobile/services/capture_review.dart';

final photo = CameraPhoto(
  const CameraMetadata(42, 4, 0, 2048, 1536),
  Uint8List.fromList([255, 216, 255, 217]),
);

void main() {
  testWidgets(
    'photo stays out of queue for 3 seconds then commits and resumes exactly once',
    (tester) async {
      var queued = 0, resumed = 0;
      Uint8List? queuedBytes;
      final review = CaptureReview(
        enqueue: (value) async {
          queuedBytes = value.bytes;
          queued++;
        },
        resume: () async {
          resumed++;
        },
      );
      review.show(photo);
      await tester.pump(const Duration(milliseconds: 2999));
      expect(queued, 0);
      await tester.pump(const Duration(milliseconds: 10));
      await tester.pump();
      expect(queued, 1);
      expect(queuedBytes, same(photo.bytes));
      expect(resumed, 1);
      await review.finish();
      expect(queued, 1);
      review.dispose();
    },
  );

  testWidgets(
    'overlapping Skip, timeout and Close save once and Close prevents reopening',
    (tester) async {
      var queued = 0, resumed = 0;
      final gate = Completer<void>();
      final review = CaptureReview(
        enqueue: (_) async {
          queued++;
          await gate.future;
        },
        resume: () async {
          resumed++;
        },
      );
      review.show(photo);
      final skip = review.finish();
      final close = review.close();
      await tester.pump(const Duration(seconds: 3));
      expect(queued, 1);
      gate.complete();
      await skip;
      await close;
      expect(review.photo, isNull);
      expect(resumed, 0);
      review.dispose();
    },
  );

  testWidgets(
    'failed save retains original for retry instead of discarding it',
    (tester) async {
      var attempts = 0, resumed = 0;
      final review = CaptureReview(
        enqueue: (_) async {
          if (++attempts == 1) throw StateError('disk full');
        },
        resume: () async {
          resumed++;
        },
      );
      review.show(photo);
      await review.finish();
      expect(review.photo, same(photo));
      expect(review.error, isNotNull);
      expect(resumed, 0);
      await review.finish();
      expect(review.photo, isNull);
      expect(resumed, 1);
      review.dispose();
    },
  );

  test('SOF native resolution and malformed/truncated headers', () {
    final jpeg = Uint8List.fromList([
      255,
      216,
      255,
      192,
      0,
      8,
      8,
      6,
      0,
      8,
      0,
      0,
      255,
      217,
    ]);
    expect(cameraJpegSize(jpeg), (2048, 1536));
    for (var at = 0; at < 12; ++at) {
      expect(cameraJpegSize(Uint8List.sublistView(jpeg, 0, at)), isNull);
    }
    jpeg[4] = 255;
    expect(cameraJpegSize(jpeg), isNull);
  });
}
