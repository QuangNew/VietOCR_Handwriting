import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import '../domain/document.dart';
import '../ocr/image_processing.dart';

bool _validateNativeJpeg(Uint8List bytes) {
  final image = decodePhoto(bytes);
  return image.width >= 2 && image.height >= 2;
}

class SessionStore {
  SessionStore({Directory? directory})
    : _directory = directory == null ? null : Future.value(directory),
      _baseDirectory = directory;
  Future<Directory>? _directory;
  final Directory? _baseDirectory;
  void setAccount(String? id) {
    _directory = null;
    _accountId = id?.replaceAll(RegExp('[^a-fA-F0-9-]'), '');
  }

  String? _accountId;

  Future<void> _saving = Future.value();
  Future<Directory> get directory =>
      _directory ??= _accountDirectory(_accountId ?? 'guest');

  Future<Directory> _accountDirectory(String account) async {
    final base = _baseDirectory ?? await getApplicationSupportDirectory();
    return Directory('${base.path}/documents/$account');
  }

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
    final folderFuture = directory;
    final nativeCamera =
        bytes.length <= 40 * 1024 * 1024 &&
        bytes.length > 3 &&
        bytes[0] == 255 &&
        bytes[1] == 216;
    final nativePng =
        bytes.length <= 40 * 1024 * 1024 &&
        bytes.length > 8 &&
        bytes[0] == 137 &&
        bytes[1] == 80;
    final Uint8List normalized;
    if (nativeCamera || nativePng) {
      if (!await compute(_validateNativeJpeg, bytes)) {
        throw const FormatException('Ảnh không hợp lệ.');
      }
      // Keep the received JPEG byte-for-byte; no PNG conversion/recompression.
      normalized = bytes;
    } else {
      normalized = await compute(normalizeDerivative, bytes);
    }
    final folder = await folderFuture;
    await folder.create(recursive: true);
    final file = File('${folder.path}/$id.${nativeCamera ? 'jpg' : 'png'}');
    await file.writeAsBytes(normalized, flush: true);
    return Document(id: id, path: file.path, name: name);
  }

  Future<void> save(List<Document> documents) {
    final folderFuture = directory;
    final snapshot = jsonEncode(
      documents.map((document) => document.toJson()).toList(),
    );
    final operation = _saving.then((_) async {
      final folder = await folderFuture;
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
      for (final path in [
        file.path,
        '${file.path}.ocr-v2.json',
        '${file.path}.transfer-v1',
        '${file.path}.transfer-v1.tmp',
        '${file.path}.transfer-v1.original',
        '${file.path}.transfer-v1.ocr-v2.json',
        for (var rotation = 1; rotation < 4; rotation++) ...[
          '${file.path}.rotate-$rotation.png',
          '${file.path}.rotate-$rotation.png.ocr-v2.json',
          '${file.path}.rotate-$rotation.png.transfer-v1',
          '${file.path}.rotate-$rotation.png.transfer-v1.tmp',
          '${file.path}.rotate-$rotation.png.transfer-v1.original',
          '${file.path}.rotate-$rotation.png.transfer-v1.ocr-v2.json',
        ],
      ]) {
        final target = File(path);
        if (await target.exists()) await target.delete();
      }
    }
  }
}
