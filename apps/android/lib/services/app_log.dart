import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

String _redact(String value) => value
    .replaceAll(
      RegExp(r'Bearer\s+[^\s,;"\x27]+', caseSensitive: false),
      'Bearer [hidden]',
    )
    .replaceAll(
      RegExp(r'sb_(?:secret|publishable)_[A-Za-z0-9_-]+'),
      '[hidden key]',
    )
    .replaceAll(
      RegExp(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),
      '[hidden token]',
    )
    .replaceAll(
      RegExp(
        r'(access_token|refresh_token|id_token|client_secret|service_role_key|password|apikey|authorization)["\x27]?\s*[:=]\s*["\x27]?[^\s,;"\x27}&]+',
        caseSensitive: false,
      ),
      '[hidden credential]',
    );

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
  final bool persist;
  final Directory? directory;
  final List<LogEntry> _entries = [];
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
                _redact(row['source'] as String),
                _redact(row['message'] as String),
                _redact(row['detail'] as String),
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
      _redact(source),
      _redact(message),
      _redact(detail.length > 8000 ? detail.substring(0, 8000) : detail),
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

  // OCR runs on the server. There is no Android :ocr process to poll.
  Future<void> captureNative() async {}

  Future<void> clear() async {
    await flush();
    _entries.clear();
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
