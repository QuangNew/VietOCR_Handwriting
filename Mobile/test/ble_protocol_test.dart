import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/domain/document.dart';
import 'package:vietocr_mobile/services/ble_protocol.dart';

void main() {
  test(
    'an explicit command rejection leaves the acknowledged queue usable',
    () async {
      late CommandQueue queue;
      queue = CommandQueue((bytes) async {
        final command = ascii.decode(bytes).trim();
        Timer.run(
          () => queue.receive(
            command.startsWith('THEME ')
                ? 'ERR INVALID_COMMAND: send HELP'
                : 'PONG',
          ),
        );
      });
      await expectLater(
        queue.send('THEME DARK'),
        throwsA(
          isA<CommandRejected>().having(
            (error) => error.code,
            'error code',
            'INVALID_COMMAND',
          ),
        ),
      );
      await queue.send('PING');
      queue.close();
    },
  );
  test(
    'theme sync does not restart OCR; indeterminate progress sends no fake percent',
    () {
      const before = AssistantSnapshot(
        AssistantState.processing,
        count: 3,
        dark: true,
      );
      const after = AssistantSnapshot(
        AssistantState.processing,
        count: 3,
        dark: false,
      );
      expect(transitionCommands(before, after), ['THEME LIGHT']);
      expect(transitionCommands(after, after), isEmpty);
      expect(transitionCommands(null, before), [
        'THEME DARK',
        'RECEIVED 3',
        'PROCESS',
      ]);
    },
  );
  test(
    'a stuck platform write times out and releases the command queue',
    () async {
      final queue = CommandQueue(
        (_) => Completer<void>().future,
        timeout: const Duration(milliseconds: 10),
      );
      await expectLater(queue.send('WAKE'), throwsA(isA<TimeoutException>()));
      await expectLater(queue.send('PING'), throwsStateError);
    },
  );
  test('notification fragments and CRLF yield complete lines only', () {
    final framer = LineFramer();
    expect(framer.add(ascii.encode('OK REC')), isEmpty);
    expect(framer.add(ascii.encode('EIVED 10\r\nPO')), ['OK RECEIVED 10']);
    expect(framer.add(ascii.encode('NG\n')), ['PONG']);
    expect(() => framer.add(List.filled(1025, 65)), throwsFormatException);
  });
  test(
    'acknowledgements serialize commands and ignore unrelated lines',
    () async {
      late CommandQueue queue;
      final written = <String>[];
      queue = CommandQueue((bytes) async {
        final line = ascii.decode(bytes).trim();
        written.add(line);
        queue.receive('OK OLD');
        Timer.run(() => queue.receive(line == 'PING' ? 'PONG' : 'OK $line'));
      });
      await Future.wait([
        queue.send('WAKE'),
        queue.send('RECEIVED 10'),
        queue.send('PING'),
      ]);
      expect(written, ['WAKE', 'RECEIVED 10', 'PING']);
      queue.close();
    },
  );
  test(
    'timeout invalidates the queue so a late ACK cannot acknowledge a new request',
    () async {
      final queue = CommandQueue(
        (_) async {},
        timeout: const Duration(milliseconds: 10),
      );
      await expectLater(queue.send('WAKE'), throwsA(isA<TimeoutException>()));
      queue.receive('OK WAKE');
      await expectLater(queue.send('WAKE'), throwsStateError);
    },
  );
  test('disconnect or error during a slow write is handled', () async {
    late CommandQueue queue;
    queue = CommandQueue((_) async {
      queue.close();
      await Future<void>.delayed(const Duration(milliseconds: 10));
    });
    await expectLater(queue.send('WAKE'), throwsStateError);
  });
  test(
    'processing is established before progress and is not restarted by updates',
    () {
      const processing = AssistantSnapshot(
        AssistantState.processing,
        count: 10,
        progress: 50,
      );
      expect(transitionCommands(null, processing), [
        'RECEIVED 10',
        'PROCESS',
        'PROGRESS 50',
      ]);
      expect(
        transitionCommands(
          processing,
          const AssistantSnapshot(
            AssistantState.processing,
            count: 10,
            progress: 70,
          ),
        ),
        ['PROGRESS 70'],
      );
      expect(
        transitionCommands(
          processing,
          const AssistantSnapshot(AssistantState.done),
        ),
        ['DONE'],
      );
      expect(
        transitionCommands(
          processing,
          const AssistantSnapshot(AssistantState.sleeping),
        ),
        ['SLEEP'],
      );
    },
  );
}
