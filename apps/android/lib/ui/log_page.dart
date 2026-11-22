import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../services/app_log.dart';

class LogPage extends StatefulWidget {
  const LogPage({super.key, this.log});
  final AppLog? log;
  @override
  State<LogPage> createState() => _LogPageState();
}

class _LogPageState extends State<LogPage> {
  AppLog get log => widget.log ?? AppLog.instance;
  Timer? timer;
  bool errorsOnly = false;
  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
    timer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => unawaited(log.captureNative()),
    );
  }

  Future<void> _refresh() async {
    await log.initialize();
    await log.captureNative();
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _share(BuildContext buttonContext) async {
    final box = buttonContext.findRenderObject() as RenderBox;
    final origin = box.localToGlobal(Offset.zero) & box.size;
    try {
      await log.captureNative();
      await log.flush();
      final folder = await getTemporaryDirectory();
      final file = File('${folder.path}/VietHandOCR-log.txt');
      await file.writeAsString(log.text);
      if (!mounted) return;
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile(file.path, mimeType: 'text/plain')],
          sharePositionOrigin: origin,
        ),
      );
    } catch (error, stack) {
      log.add(
        'Log',
        'Không xuất được log',
        level: 'ERROR',
        error: error,
        stack: stack,
      );
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: log,
    builder: (context, _) {
      final entries =
          log.entries.reversed
              .where((entry) => !errorsOnly || entry.level == 'ERROR')
              .toList()
            ..sort((a, b) => b.time.compareTo(a.time));
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                FilterChip(
                  label: const Text('Chỉ lỗi'),
                  selected: errorsOnly,
                  onSelected: (value) => setState(() => errorsOnly = value),
                ),
                IconButton(
                  tooltip: 'Làm mới log',
                  onPressed: _refresh,
                  icon: const Icon(Icons.refresh),
                ),
                IconButton(
                  tooltip: 'Sao chép log',
                  onPressed: () =>
                      Clipboard.setData(ClipboardData(text: log.text)),
                  icon: const Icon(Icons.copy),
                ),
                Builder(
                  builder: (buttonContext) => IconButton(
                    tooltip: 'Xuất log',
                    onPressed: () => _share(buttonContext),
                    icon: const Icon(Icons.share_outlined),
                  ),
                ),
                IconButton(
                  tooltip: 'Xóa log',
                  onPressed: log.clear,
                  icon: const Icon(Icons.delete_outline),
                ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text(
              'Log lưu trên máy, gồm bước OCR, lỗi gốc và kết nối BLE. Không ghi ảnh hoặc văn bản nhận diện.',
            ),
          ),
          Expanded(
            child: entries.isEmpty
                ? const Center(child: Text('Chưa có log phù hợp.'))
                : ListView.builder(
                    key: const PageStorageKey('logs'),
                    itemCount: entries.length,
                    itemBuilder: (context, index) {
                      final entry = entries[index];
                      final time = entry.time
                          .toLocal()
                          .toIso8601String()
                          .split('T')
                          .last;
                      return ExpansionTile(
                        key: PageStorageKey(entry),
                        leading: Icon(
                          entry.level == 'ERROR'
                              ? Icons.error_outline
                              : Icons.info_outline,
                          color: entry.level == 'ERROR'
                              ? Theme.of(context).colorScheme.error
                              : null,
                        ),
                        title: Text('${entry.source} · ${entry.message}'),
                        subtitle: Text('$time · ${entry.level}'),
                        children: [
                          Padding(
                            padding: const EdgeInsets.all(16),
                            child: SelectableText(
                              key: const PageStorageKey('detail'),
                              entry.text,
                            ),
                          ),
                        ],
                      );
                    },
                  ),
          ),
        ],
      );
    },
  );
}
