import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

class LogEntry {
  LogEntry(this.level, this.source, this.message, this.detail, {DateTime? time})
    : time = time ?? DateTime.now();
  final DateTime time;
  final String level, source, message, detail;
  Map<String, Object> toJson() => {
    'time': time.toIso8601String(),
    'level': level,
    'source': source,
    'message': message,
    'detail': detail,
  };
  String get text =>
      '${time.toIso8601String()} [$level] $source: $message${detail.isEmpty ? '' : '\n$detail'}';
}

// Bounded local diagnostics. Never pass image bytes or recognized text here.
class AppLog extends ChangeNotifier {
  AppLog({this.persist = true, this.directory});
  static final instance = AppLog();
  static const _native = MethodChannel('vietocr/ocr');
  final bool persist;
  final Directory? directory;
  final List<LogEntry> _entries = [];
  final Set<String> _nativeIds = {};
  final List<String> _nativeOrder = [];
  List<LogEntry> get entries => List.unmodifiable(_entries);
  Future<void>? _initializing;
  Future<void> _writes = Future.value();
  File? _file;

  Future<void> initialize() => _initializing ??= _initialize();
  Future<void> _initialize() async {
    if (!persist) return;
    try {
      final folder =
          directory ??
          Directory(
            '${(await getApplicationSupportDirectory()).path}/diagnostics',
          );
      await folder.create(recursive: true);
      _file = File('${folder.path}/app-log.jsonl');
      if (await _file!.exists() && await _file!.length() <= 600 * 1024) {
        final previous = <LogEntry>[];
        for (final line in await _file!.readAsLines()) {
          try {
            final row = jsonDecode(line) as Map<String, dynamic>;
            previous.add(
              LogEntry(
                row['level'] as String,
                row['source'] as String,
                row['message'] as String,
                row['detail'] as String,
                time: DateTime.parse(row['time'] as String),
              ),
            );
          } catch (_) {
            /* Skip a partial line after a process was killed. */
          }
        }
        _entries.insertAll(0, previous);
        _trim();
        notifyListeners();
      }
    } catch (_) {
      /* Storage failures must never break the app. */
    }
  }

  void add(
    String source,
    String message, {
    String level = 'INFO',
    Object? error,
    StackTrace? stack,
    DateTime? time,
  }) {
    final detail = [
      if (error != null) error.toString(),
      if (stack != null) stack.toString(),
    ].join('\n');
    final entry = LogEntry(
      level,
      source,
      message,
      detail.length > 8000 ? detail.substring(0, 8000) : detail,
      time: time,
    );
    _entries.add(entry);
    _trim();
    notifyListeners();
    if (!persist) return;
    _writes = _writes
        .then((_) async {
          await initialize();
          if (_file == null) return;
          if (await _file!.exists() && await _file!.length() > 512 * 1024) {
            final previous = File('${_file!.path}.previous');
            if (await previous.exists()) await previous.delete();
            await _file!.rename(previous.path);
          }
          await _file!.writeAsString(
            '${jsonEncode(entry.toJson())}\n',
            mode: FileMode.append,
            flush: true,
          );
        })
        .catchError((Object _) {});
  }

  void _trim() {
    if (_entries.length > 300) _entries.removeRange(0, _entries.length - 300);
  }

  Future<void> flush() => _writes;
  String get text => _entries.map((entry) => entry.text).join('\n\n');

  Future<void> captureNative() async {
    try {
      final raw = await _native.invokeMethod<String>('nativeLogs');
      if (raw == null) return;
      // Read a bounded tail smaller than the deduplication window. Re-reading a
      // longer history would evict IDs while iterating and duplicate every poll.
      final tail = const LineSplitter()
          .convert(raw)
          .reversed
          .take(250)
          .toList()
          .reversed;
      for (final line in tail) {
        try {
          final row = jsonDecode(line) as Map<String, dynamic>;
          final id = '${row['time']}:${row['pid']}:${row['stage']}';
          if (!_nativeIds.add(id)) continue;
          _nativeOrder.add(id);
          if (_nativeOrder.length > 300) {
            _nativeIds.remove(_nativeOrder.removeAt(0));
          }
          add(
            'OCR native',
            row['stage'].toString(),
            level: row['level']?.toString() ?? 'INFO',
            error: row['detail'],
            time: DateTime.fromMillisecondsSinceEpoch(row['time'] as int),
          );
        } catch (_) {}
      }
    } catch (_) {
      /* A previous APK or a unit test may not expose this method. */
    }
  }

  Future<void> clear() async {
    await flush();
    _entries.clear();
    _nativeIds.clear();
    _nativeOrder.clear();
    try {
      await _native.invokeMethod<void>('clearNativeLogs');
    } catch (_) {}
    if (_file != null) {
      try {
        await _file!.writeAsString('');
        final previous = File('${_file!.path}.previous');
        if (await previous.exists()) await previous.delete();
      } catch (_) {}
    }
    notifyListeners();
  }
}
