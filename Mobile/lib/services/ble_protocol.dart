import 'dart:async';
import 'dart:convert';
import '../domain/document.dart';

class LineFramer {
  String _buffer = '';
  List<String> add(List<int> bytes) {
    _buffer += ascii.decode(bytes);
    if (_buffer.length > 1024) {
      _buffer = '';
      throw const FormatException('BLE response too long');
    }
    final lines = _buffer.split('\n');
    _buffer = lines.removeLast();
    return lines
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();
  }
}

// One command in flight: the ESP32 acknowledges ASCII lines, not BLE writes.
class CommandRejected implements Exception {
  const CommandRejected(this.response);
  final String response;
  String get code =>
      RegExp(r'^ERR\s+([^:\s]+)').firstMatch(response)?.group(1) ?? response;
  @override
  String toString() => response;
}

class CommandQueue {
  CommandQueue(this.write, {this.timeout = const Duration(seconds: 3)});
  final Future<void> Function(List<int>) write;
  final Duration timeout;
  Future<void> _tail = Future.value();
  Completer<String>? _reply;
  String? _expected;
  bool _closed = false;

  void receive(String line) {
    if (_reply == null || _reply!.isCompleted) return;
    if (line == _expected) {
      _reply!.complete(line);
    } else if (line.startsWith('ERR ')) {
      _reply!.completeError(CommandRejected(line));
    }
  }

  Future<void> send(String command) {
    final bytes = ascii.encode('$command\n');
    if (bytes.length > 80 || command.contains('\n') || command.contains('\r')) {
      return Future.error(ArgumentError('Invalid BLE command'));
    }
    final operation = _tail.then((_) async {
      if (_closed) throw StateError('Bluetooth đã ngắt kết nối.');
      _expected = command == 'PING' ? 'PONG' : 'OK $command';
      final reply = Completer<String>();
      _reply = reply;
      // Install the error handler before a transport callback can fail the reply.
      final response = reply.future.timeout(timeout);
      unawaited(
        response.then<void>((_) {}, onError: (Object _, StackTrace _) {}),
      );
      try {
        for (var offset = 0; offset < bytes.length; offset += 20) {
          if (_closed) throw StateError('Bluetooth đã ngắt kết nối.');
          await write(
            bytes.sublist(offset, (offset + 20).clamp(0, bytes.length)),
          ).timeout(timeout);
        }
        await response;
      } catch (error) {
        // A late acknowledgement must never satisfy a subsequent command.
        // An explicit ERR is a complete response, so the channel remains usable.
        if (error is! CommandRejected) _closed = true;
        if (!reply.isCompleted) reply.complete('');
        await response.catchError((_) => '');
        rethrow;
      } finally {
        _reply = null;
      }
    });
    _tail = operation.catchError((_) {});
    return operation;
  }

  void close() {
    _closed = true;
    if (_reply != null && !_reply!.isCompleted) {
      _reply!.completeError(StateError('Bluetooth đã ngắt kết nối.'));
    }
  }
}

class AssistantSnapshot {
  const AssistantSnapshot(
    this.state, {
    this.count = 0,
    this.progress,
    this.dark,
  });
  final AssistantState state;
  final int count;
  final int? progress;
  final bool? dark;
  @override
  bool operator ==(Object other) =>
      other is AssistantSnapshot &&
      state == other.state &&
      count == other.count &&
      progress == other.progress &&
      dark == other.dark;
  @override
  int get hashCode => Object.hash(state, count, progress, dark);
}

List<String> transitionCommands(
  AssistantSnapshot? previous,
  AssistantSnapshot next,
) {
  final result = <String>[];
  if (next.dark != null && previous?.dark != next.dark) {
    result.add('THEME ${next.dark! ? 'DARK' : 'LIGHT'}');
  }
  final changed = previous?.state != next.state;
  final count = next.count.clamp(1, 10);
  if (next.state == AssistantState.awake) {
    if (changed) result.add('WAKE');
  }
  if (next.state == AssistantState.received) {
    if (changed || previous?.count != count) result.add('RECEIVED $count');
  }
  if (next.state == AssistantState.processing) {
    if (changed) {
      if (previous?.state != AssistantState.received) {
        result.add('RECEIVED $count');
      }
      result.add('PROCESS');
    }
    if (next.progress != null &&
        (changed || previous?.progress != next.progress)) {
      result.add('PROGRESS ${next.progress!.clamp(0, 100)}');
    }
  }
  if (changed && next.state == AssistantState.done) result.add('DONE');
  if (changed && next.state == AssistantState.error) result.add('ERROR');
  if (changed && next.state == AssistantState.sleeping) result.add('SLEEP');
  return result;
}
