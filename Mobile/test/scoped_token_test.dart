import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/scoped_token.dart';

void main() {
  test(
    'account change during refresh cannot return a different account token',
    () async {
      String? account = 'a';
      final refresh = Completer<String>();
      final token = scopedToken(
        owner: account,
        currentOwner: () => account,
        fetch: () => refresh.future,
      );
      final pending = token();
      final rejected = expectLater(pending, throwsStateError);
      account = 'b';
      refresh.complete('new-account-token');
      await rejected;
    },
  );
  test(
    'logout rejects before calling refresh or issuing another request',
    () async {
      String? account = 'a';
      var fetched = 0;
      final token = scopedToken(
        owner: account,
        currentOwner: () => account,
        fetch: () async {
          fetched++;
          return 'token';
        },
      );
      account = null;
      await expectLater(token(), throwsStateError);
      expect(fetched, 0);
    },
  );
  test('refresh for the same account remains usable', () async {
    final token = scopedToken(
      owner: 'a',
      currentOwner: () => 'a',
      fetch: () async => 'refreshed-token',
    );
    expect(await token(), 'refreshed-token');
  });
}
