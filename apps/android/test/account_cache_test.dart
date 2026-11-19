import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/services/session_store.dart';

void main() {
  test(
    'local photo/result caches are isolated across logout and account changes',
    () async {
      final root = await Directory.systemTemp.createTemp('vietocr-accounts');
      try {
        final store = SessionStore(directory: root);
        store.setAccount('aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa');
        final one = await store.directory;
        await one.create(recursive: true);
        final photo = File('${one.path}/photo.png');
        await photo.writeAsBytes([1, 2, 3]);
        await store.save([
          Document(id: 'one', path: photo.path, name: 'one.png')
            ..text = 'Account A result',
        ]);
        store.setAccount('bbbbbbbb-2222-4444-8888-bbbbbbbbbbbb');
        expect(await store.load(), isEmpty);
        expect((await store.directory).path, isNot(one.path));
        store.setAccount(null);
        expect(await store.load(), isEmpty);
        store.setAccount('aaaaaaaa-1111-4444-8888-aaaaaaaaaaaa');
        expect((await store.load()).single.text, 'Account A result');
        expect((await store.directory).path, one.path);
      } finally {
        await root.delete(recursive: true);
      }
    },
  );
}
