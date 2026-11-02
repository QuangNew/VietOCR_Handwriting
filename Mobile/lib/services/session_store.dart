import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../domain/document.dart';
import '../ocr/image_processing.dart';
import 'camera_transfer.dart';

bool _validateNativeJpeg(Uint8List bytes) {
  final image = decodePhoto(bytes);
  return const [
    (2592, 1944),
    (1944, 2592),
    (2048, 1536),
    (1536, 2048),
  ].contains((image.width, image.height));
}

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
    for (final row in rows) {
      final item = Document.fromJson(Map<String, dynamic>.from(row as Map));
      if (File(item.path).parent.absolute.path == folder.absolute.path &&
          await File(item.path).exists()) {
        result.add(item);
      }
    }
    return result;
  }

  Future<Document> import(Uint8List bytes, String name, String id) async {
    final nativeCamera =
        bytes.length <= cameraMaxBytes &&
        const [(2592, 1944), (2048, 1536)].contains(cameraJpegSize(bytes));
    final Uint8List normalized;
    if (nativeCamera) {
      if (!await compute(_validateNativeJpeg, bytes)) {
        throw const FormatException('Ảnh camera sai độ phân giải.');
      }
      // Keep the received JPEG byte-for-byte; no PNG conversion/recompression.
      normalized = bytes;
    } else {
      normalized = await compute(normalizePhoto, bytes);
    }
    final folder = await directory;
    await folder.create(recursive: true);
    final file = File('${folder.path}/$id.${nativeCamera ? 'jpg' : 'png'}');
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
