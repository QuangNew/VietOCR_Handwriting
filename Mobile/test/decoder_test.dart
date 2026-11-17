import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/ocr/decoder.dart';

void main() {
  const vocabulary = ['<pad>', '<sos>', '<eos>', 'T', 'ế', 't'];
  test('greedy decoder preserves Vietnamese and stops at EOS', () async {
    final sequence = [3, 4, 5, 2];
    final prefixes = <List<int>>[];
    final text = await decodeTokens(
      vocabulary: vocabulary,
      maxTokens: 10,
      cancel: CancellationToken(),
      next: (tokens) async {
        prefixes.add(List.of(tokens));
        return sequence.removeAt(0);
      },
    );
    expect(text, 'Tết');
    expect(prefixes.last, [1, 3, 4, 5]);
  });
  test('cancellation after a native step discards its result', () async {
    final cancel = CancellationToken();
    await expectLater(
      decodeTokens(
        vocabulary: vocabulary,
        maxTokens: 10,
        cancel: cancel,
        next: (_) async {
          cancel.cancel();
          return 3;
        },
      ),
      throwsA(isA<OcrCancelled>()),
    );
  });
  test('out of vocabulary and missing EOS fail explicitly', () async {
    await expectLater(
      decodeTokens(
        vocabulary: vocabulary,
        maxTokens: 2,
        cancel: CancellationToken(),
        next: (_) async => 100,
      ),
      throwsStateError,
    );
    await expectLater(
      decodeTokens(
        vocabulary: vocabulary,
        maxTokens: 2,
        cancel: CancellationToken(),
        next: (_) async => 3,
      ),
      throwsStateError,
    );
  });
}
