import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../domain/app_controller.dart';
import '../domain/document.dart';
import '../ocr/paper_detector.dart';
import 'image_detail_page.dart';
import 'lens_stage.dart';
import 'pipeline_sheet.dart';

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

String _exportTimestamp() {
  final now = DateTime.now();
  String p(int v) => v.toString().padLeft(2, '0');
  return '${now.year}${p(now.month)}${p(now.day)}-${p(now.hour)}${p(now.minute)}${p(now.second)}';
}

String _cleanStem(String? name) {
  final raw = (name ?? '').trim();
  if (raw.isEmpty) return 'TatCa';
  final noExt = raw.replaceFirst(RegExp(r'\.[^./\\]+$'), '');
  final safe = noExt
      .replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1f]'), '_')
      .replaceAll(RegExp(r'^\.+|\.+$'), '')
      .trim();
  return safe.isEmpty ? 'VietHandOCR' : safe;
}

Future<void> shareText(String text, {String? name}) async {
  final folder = await getTemporaryDirectory();
  final filename = '${_exportTimestamp()}_${_cleanStem(name)}_Script.txt';
  final file = File('${folder.path}/$filename');
  await file.writeAsString(text, flush: true);
  await SharePlus.instance.share(
    ShareParams(files: [XFile(file.path)], title: 'Văn bản VietHandOCR'),
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
  late bool correct = app.correctText;
  late final String? owner = app.cloud.userId;
  DocumentViewMode _viewMode = DocumentViewMode.original;
  bool _lensEnabled = true;

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

  Future<void> _cropFromLens(
    Document item,
    List<Point2D> quad, {
    required bool autoSend,
  }) async {
    try {
      final rawBytes = await File(item.path).readAsBytes();
      final croppedBytes = await compute(
        cropPhotoToLensQuad,
        (bytes: rawBytes, rotation: item.rotation, quad: quad),
      );
      if (!mounted || owner != app.cloud.userId) return;
      final name = 'LensCrop_${DateTime.now().millisecondsSinceEpoch}.png';
      await app.importImages([(croppedBytes, name)]);
      final derived = app.documents.where((d) => d.name == name).firstOrNull;
      if (derived == null) return;
      app.setIncluded(item.id, false);
      if (autoSend && app.canSend) {
        app.enqueueAutoSend(derived.id, correct: correct);
        if (mounted) {
          showNotice(context, 'Đã cắt theo khung Lens và tự động gửi OCR.');
        }
      } else if (mounted) {
        showNotice(context, 'Đã lưu ảnh cắt theo khung Lens.');
      }
      if (mounted && owner == app.cloud.userId) {
        await Navigator.of(context).pushReplacement<void, void>(
          MaterialPageRoute(
            builder: (_) => DocumentPage(app: app, id: derived.id),
          ),
        );
      }
    } catch (e) {
      if (mounted) showNotice(context, AppController.readableError(e));
    }
  }

  void _openFullscreen(Document item) {
    Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => FullscreenDocumentStagePage(
          item: item,
          initialMode: _viewMode,
          lensEnabled: _lensEnabled,
          canSend: app.canSend,
          onQuadChanged: (q) => app.setCustomQuad(item.id, q),
          onCropAndSend: (q, {required bool autoSend}) =>
              _cropFromLens(item, q, autoSend: autoSend),
        ),
      ),
    );
  }

  void _openPipeline(Document item) {
    Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => PipelineDemoPage(app: app, item: item),
      ),
    );
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
      final hasText = item.text.trim().isNotEmpty;
      final activeMode =
          hasText ? _viewMode : DocumentViewMode.original;
      final stageHeight = (MediaQuery.sizeOf(context).height * 0.44).clamp(
        260.0,
        420.0,
      );

      return Scaffold(
        appBar: AppBar(
          title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
          actions: [
            IconButton(
              tooltip: 'Cắt & chỉnh ảnh',
              onPressed: () => _openEditor(item),
              icon: const Icon(Icons.crop_rotate_outlined),
            ),
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
            padding: const EdgeInsets.fromLTRB(14, 10, 14, 24),
            children: [
              // 1) Compact mobile 3-way view mode switcher ("Ảnh gốc" | "Ảnh văn bản" | "Đối chiếu")
              Card(
                color: colors.surfaceContainerLow,
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      ViewModeSegmentedBar(
                        mode: activeMode,
                        canDigital: hasText,
                        onChanged: (next) => setState(() => _viewMode = next),
                      ),
                      const SizedBox(height: 10),
                      // 2) Generous visual stage tailored for touch-dragging Lens corners or ⇄ compare slider
                      SizedBox(
                        height: stageHeight,
                        child: LensStage(
                          item: item,
                          mode: activeMode,
                          lensEnabled: _lensEnabled,
                          canSend: app.canSend,
                          onQuadChanged: (q) => app.setCustomQuad(item.id, q),
                          onCropAndSend: (q, {required bool autoSend}) =>
                              _cropFromLens(item, q, autoSend: autoSend),
                          onCopyText: (t) async {
                            await Clipboard.setData(ClipboardData(text: t));
                            if (context.mounted) {
                              showNotice(context, 'Đã sao chép văn bản đã chọn.');
                            }
                          },
                          onTapBackground: () => _openEditor(item),
                          onOpenFullscreen: () => _openFullscreen(item),
                        ),
                      ),
                      const SizedBox(height: 10),
                      // 3) Compact mobile tool strip below preview (wraps cleanly on 360dp phones)
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 9,
                              vertical: 5,
                            ),
                            decoration: BoxDecoration(
                              color: colors.surfaceContainer,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              documentStatus(item),
                              style: Theme.of(context).textTheme.labelMedium,
                            ),
                          ),
                          if (activeMode == DocumentViewMode.original)
                            FilterChip(
                              visualDensity: VisualDensity.compact,
                              selected: _lensEnabled,
                              label: const Text('✦ Lens'),
                              onSelected: (v) =>
                                  setState(() => _lensEnabled = v),
                            ),
                          ActionChip(
                            visualDensity: VisualDensity.compact,
                            avatar: const Icon(Icons.open_in_full, size: 15),
                            label: const Text('Phóng to'),
                            onPressed: () => _openFullscreen(item),
                          ),
                          if (item.status == DocumentStatus.done ||
                              item.hasPipeline)
                            ActionChip(
                              visualDensity: VisualDensity.compact,
                              avatar: const Icon(
                                Icons.auto_graph_rounded,
                                size: 15,
                              ),
                              label: const Text('Pipeline'),
                              onPressed: () => _openPipeline(item),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              if (item.error.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    item.error,
                    style: TextStyle(color: colors.error),
                  ),
                ),
              if (processing) ...[
                const SizedBox(height: 12),
                LinearProgressIndicator(value: app.busy ? app.progress : null),
                const SizedBox(height: 6),
                Text(
                  app.busy && app.progressLabel.isNotEmpty
                      ? app.progressLabel
                      : 'Đang tự động gửi & nhận dạng từ máy chủ…',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
              const SizedBox(height: 16),
              // 4) Spacious Văn bản section with header actions (saves vertical phone space!)
              Card(
                color: colors.surfaceContainerLow,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Wrap(
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                'Văn bản',
                                style: Theme.of(context).textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w700),
                              ),
                              const SizedBox(width: 8),
                              Text(
                                '${item.text.length} ký tự',
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(color: colors.onSurfaceVariant),
                              ),
                            ],
                          ),
                          if (hasText)
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton.filledTonal(
                                  tooltip: 'Sao chép văn bản',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () async {
                                    await Clipboard.setData(
                                      ClipboardData(text: item.text),
                                    );
                                    if (context.mounted) {
                                      showNotice(
                                        context,
                                        'Đã sao chép văn bản.',
                                      );
                                    }
                                  },
                                  icon: const Icon(
                                    Icons.copy_outlined,
                                    size: 18,
                                  ),
                                ),
                                const SizedBox(width: 6),
                                IconButton.filledTonal(
                                  tooltip: 'Xuất file .txt',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () async {
                                    try {
                                      await shareText(
                                        item.text,
                                        name: item.name,
                                      );
                                    } catch (error) {
                                      if (context.mounted) {
                                        showNotice(
                                          context,
                                          AppController.readableError(error),
                                        );
                                      }
                                    }
                                  },
                                  icon: const Icon(Icons.ios_share, size: 18),
                                ),
                              ],
                            ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      if (item.status == DocumentStatus.done ||
                          item.text.isNotEmpty)
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
                        )
                      else
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          child: Text(
                            processing
                                ? 'Kết quả sẽ tự cập nhật tại đây.'
                                : 'Gửi ảnh để nhận văn bản và mở khóa chế độ Ảnh văn bản / Đối chiếu.',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: colors.onSurfaceVariant),
                          ),
                        ),
                    ],
                  ),
                ),
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
                    padding: const EdgeInsets.fromLTRB(14, 8, 14, 8),
                    child: Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 10,
                      runSpacing: 8,
                      children: [
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
                                  split: true,
                                  correct: correct,
                                ),
                          icon: const Icon(Icons.send_outlined),
                          label: Text(
                            item.status == DocumentStatus.done ||
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
            : processing
            ? Material(
                color: colors.surfaceContainer,
                child: SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 6,
                    ),
                    child: TextButton(
                      onPressed: app.cancel,
                      child: const Text('Tạm dừng lượt gửi'),
                    ),
                  ),
                ),
              )
            : null,
      );
    },
  );
}
