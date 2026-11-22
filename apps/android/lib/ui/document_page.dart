import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../domain/app_controller.dart';
import '../domain/document.dart';
import 'image_detail_page.dart';

String documentStatus(Document item) => switch (item.status) {
  DocumentStatus.ready => item.included ? 'Chờ gửi' : 'Bản nháp · chưa chọn',
  DocumentStatus.processing => 'Đang xử lý',
  DocumentStatus.done => 'Đã có văn bản',
  DocumentStatus.error => 'Cần thử lại',
  DocumentStatus.cancelled => 'Đã tạm dừng',
};

void showNotice(BuildContext context, String message) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(SnackBar(content: Text(message)));
}

Future<void> shareText(String text) async {
  final folder = await getTemporaryDirectory();
  final file = File(
    '${folder.path}/VietOCR-${DateTime.now().millisecondsSinceEpoch}.txt',
  );
  await file.writeAsString(text, flush: true);
  await SharePlus.instance.share(
    ShareParams(files: [XFile(file.path)], title: 'Văn bản VietOCR'),
  );
}

class DocumentPage extends StatefulWidget {
  const DocumentPage({super.key, required this.app, required this.id});
  final AppController app;
  final String id;

  @override
  State<DocumentPage> createState() => _DocumentPageState();
}

class _DocumentPageState extends State<DocumentPage> {
  AppController get app => widget.app;
  late bool split = app.splitLines;
  late bool correct = app.correctText;
  late final String? owner = app.cloud.userId;

  Future<void> _remove(Document item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Xóa ảnh này?'),
        content: Text(item.name),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Giữ ảnh'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Xóa ảnh'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted || owner != app.cloud.userId) return;
    await app.remove(item.id);
    if (mounted) Navigator.pop(context);
  }

  Future<void> _openEditor(Document item) async {
    final derived = await Navigator.of(context).push<Document>(
      MaterialPageRoute(
        builder: (_) =>
            ImageDetailPage(app: app, item: item, finishOnSave: true),
      ),
    );
    if (derived != null && mounted && owner == app.cloud.userId) {
      Navigator.of(context).pushReplacement<void, void>(
        MaterialPageRoute(
          builder: (_) => DocumentPage(app: app, id: derived.id),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final item = owner == app.cloud.userId && app.canUseWorkspace
          ? app.documents.where((d) => d.id == widget.id).firstOrNull
          : null;
      if (item == null) {
        return Scaffold(
          appBar: AppBar(title: const Text('Tài liệu')),
          body: const Center(child: Text('Ảnh không còn trong phiên này.')),
        );
      }
      final colors = Theme.of(context).colorScheme;
      final processing = item.status == DocumentStatus.processing;
      return Scaffold(
        appBar: AppBar(
          title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
          actions: [
            IconButton(
              tooltip: 'Xóa ảnh',
              onPressed: app.busy || processing || app.importing
                  ? null
                  : () => _remove(item),
              icon: const Icon(Icons.delete_outline),
            ),
          ],
        ),
        body: SafeArea(
          top: false,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
            children: [
              Card(
                color: colors.surfaceContainerLow,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ClipRRect(
                      borderRadius: const BorderRadius.vertical(
                        top: Radius.circular(18),
                      ),
                      child: InkWell(
                        onTap: () => _openEditor(item),
                        child: ColoredBox(
                          color: colors.surfaceContainer,
                          child: SizedBox(
                            height: 200,
                            child: RotatedBox(
                              quarterTurns: item.rotation,
                              child: Image.file(
                                File(item.path),
                                fit: BoxFit.contain,
                                cacheWidth: 1080,
                                errorBuilder: (_, _, _) => const Center(
                                  child: Text('Không mở được ảnh này.'),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.all(10),
                      child: Wrap(
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text(
                            documentStatus(item),
                            style: Theme.of(context).textTheme.labelLarge,
                          ),
                          TextButton.icon(
                            onPressed: () => _openEditor(item),
                            icon: const Icon(Icons.crop),
                            label: const Text('Cắt và chỉnh ảnh'),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              if (item.error.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    item.error,
                    style: TextStyle(color: colors.error),
                  ),
                ),
              if (processing) ...[
                const SizedBox(height: 16),
                LinearProgressIndicator(value: app.busy ? app.progress : null),
                const SizedBox(height: 8),
                Text(
                  app.busy && app.progressLabel.isNotEmpty
                      ? app.progressLabel
                      : 'Đang chờ văn bản từ máy chủ…',
                ),
              ],
              const SizedBox(height: 22),
              Text('Văn bản', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 10),
              if (item.status == DocumentStatus.done ||
                  item.text.isNotEmpty) ...[
                TextFormField(
                  key: ValueKey('${item.id}-${item.status.name}'),
                  initialValue: item.text,
                  minLines: 4,
                  maxLines: null,
                  readOnly: app.busy || processing,
                  decoration: const InputDecoration(
                    hintText: 'Sửa kết quả tại đây',
                  ),
                  onChanged: (value) => app.edit(item.id, value),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    OutlinedButton.icon(
                      onPressed: item.text.isEmpty
                          ? null
                          : () async {
                              await Clipboard.setData(
                                ClipboardData(text: item.text),
                              );
                              if (context.mounted) {
                                showNotice(context, 'Đã sao chép văn bản.');
                              }
                            },
                      icon: const Icon(Icons.copy_outlined),
                      label: const Text('Sao chép'),
                    ),
                    OutlinedButton.icon(
                      onPressed: item.text.isEmpty
                          ? null
                          : () async {
                              try {
                                await shareText(item.text);
                              } catch (error) {
                                if (context.mounted) {
                                  showNotice(
                                    context,
                                    AppController.readableError(error),
                                  );
                                }
                              }
                            },
                      icon: const Icon(Icons.ios_share),
                      label: const Text('Xuất .txt'),
                    ),
                  ],
                ),
              ] else
                Text(
                  processing
                      ? 'Kết quả sẽ tự cập nhật tại đây.'
                      : 'Gửi ảnh để nhận văn bản.',
                ),
            ],
          ),
        ),
        bottomNavigationBar: item.canSend
            ? Material(
                color: colors.surfaceContainer,
                child: SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                    child: Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 10,
                      children: [
                        DropdownButton<bool>(
                          value: split,
                          onChanged: app.busy
                              ? null
                              : (value) =>
                                    setState(() => split = value ?? true),
                          items: const [
                            DropdownMenuItem(
                              value: true,
                              child: Text('Tự tách dòng'),
                            ),
                            DropdownMenuItem(
                              value: false,
                              child: Text('Một dòng'),
                            ),
                          ],
                        ),
                        FilterChip(
                          selected: correct,
                          onSelected: app.busy
                              ? null
                              : (value) => setState(() => correct = value),
                          label: const Text('Nội suy BARTpho'),
                        ),
                        FilledButton.icon(
                          onPressed: app.busy || !app.canSend || app.importing
                              ? null
                              : () => app.recognize(
                                  only: item.id,
                                  split: split,
                                  correct: correct,
                                ),
                          icon: const Icon(Icons.send_outlined),
                          label: Text(
                            item.status == DocumentStatus.error ||
                                    item.status == DocumentStatus.cancelled
                                ? 'Gửi lại ảnh'
                                : 'Gửi ảnh này',
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              )
            : processing && app.busy
            ? SafeArea(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: TextButton(
                    onPressed: app.cancel,
                    child: const Text('Tạm dừng lượt gửi'),
                  ),
                ),
              )
            : null,
      );
    },
  );
}
