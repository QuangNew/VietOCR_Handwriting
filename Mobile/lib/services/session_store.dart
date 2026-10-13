import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../domain/document.dart';
import '../ocr/image_processing.dart';

class SessionStore {
  SessionStore({Directory? directory}) : _directory = directory;
  Directory? _directory;
  Future<void> _saving = Future.value();
  Future<Directory> get directory async => _directory ??= Directory(
    '${(await getApplicationSupportDirectory()).path}/documents',
  );

  Future<List<Document>> load() async {
    final folder = await directory;
    await folder.create(recursive: true);
    final file = File('${folder.path}/session.json');
    if (!await file.exists()) return [];
    final rows = jsonDecode(await file.readAsString()) as List;
    final result = <Document>[];
    for (final row in rows.take(10)) {
      final item = Document.fromJson(Map<String, dynamic>.from(row as Map));
      if (File(item.path).parent.absolute.path == folder.absolute.path &&
          await File(item.path).exists()) {
        result.add(item);
      }
    }
    return result;
  }

  Future<Document> import(Uint8List bytes, String name, String id) async {
    final normalized = await compute(normalizePhoto, bytes);
    final folder = await directory;
    await folder.create(recursive: true);
    final file = File('${folder.path}/$id.png');
    await file.writeAsBytes(normalized, flush: true);
    return Document(id: id, path: file.path, name: name);
  }

  Future<void> save(List<Document> documents) {
    final snapshot = jsonEncode(
      documents.map((document) => document.toJson()).toList(),
    );
    final operation = _saving.then((_) async {
      final folder = await directory;
      await folder.create(recursive: true);
      final pending = File('${folder.path}/session.tmp');
      await pending.writeAsString(snapshot, flush: true);
      await pending.rename('${folder.path}/session.json');
    });
    _saving = operation.catchError((_) {});
    return operation;
  }

  Future<void> remove(Document document) async {
    final folder = await directory;
    final file = File(document.path);
    if (file.parent.absolute.path == folder.absolute.path &&
        await file.exists()) {
      await file.delete();
    }
  }
}
