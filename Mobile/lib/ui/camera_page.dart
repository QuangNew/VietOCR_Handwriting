import 'dart:async';
import 'package:flutter/material.dart';
import '../domain/app_controller.dart';
import '../domain/document.dart';
import '../services/ble_assistant.dart';
import '../services/capture_review.dart';
import 'camera_settings_sheet.dart';

class CameraPage extends StatefulWidget {
  const CameraPage({super.key, required this.app, required this.ble});
  final AppController app;
  final BleAssistant ble;
  @override
  State<CameraPage> createState() => _CameraPageState();
}

class _CameraPageState extends State<CameraPage> {
  late final CaptureReview review;
  final transform = TransformationController();
  Future<void>? _capture;
  bool closing = false, canPop = false, expanded = false, queueHidden = false;

  @override
  void initState() {
    super.initState();
    review = CaptureReview(
      enqueue: (photo) async {
        if (widget.app.importing) {
          throw StateError('Đang thêm ảnh khác. Bấm Bỏ qua để thử lại.');
        }
        final name = 'OV5640_${photo.metadata.id}.jpg';
        if (mounted) setState(() => queueHidden = false);
        await widget.app.importImages([(photo.bytes, name)], enqueue: true);
        if (!widget.app.documents.any((item) => item.name == name)) {
          throw StateError(widget.app.message);
        }
      },
      resume: _preview,
    );
    WidgetsBinding.instance.addPostFrameCallback((_) => _preview());
  }

  void _notice(Object error) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(AppController.readableError(error))),
      );
    }
  }

  Future<void> _preview() async {
    if (!mounted || closing) return;
    transform.value = Matrix4.identity();
    try {
      await widget.ble.cameraPreview(true);
    } catch (error) {
      _notice(error);
    }
  }

  void _shoot() {
    if (_capture != null || review.photo != null || closing) return;
    _capture = _takePhoto().whenComplete(() {
      _capture = null;
      if (mounted) setState(() {});
    });
    setState(() {});
  }

  Future<void> _takePhoto() async {
    try {
      final photo = await widget.ble.captureCamera();
      if (!mounted) return;
      transform.value = Matrix4.identity();
      review.show(photo);
      if (closing) await review.close();
    } catch (error) {
      _notice(error);
    }
  }

  Future<void> _close() async {
    if (closing) return;
    setState(() => closing = true);
    await _capture;
    await review.close();
    if (review.photo != null) {
      if (mounted) setState(() => closing = false);
      _notice(review.error ?? StateError('Chưa lưu được ảnh. Hãy thử lại.'));
      return;
    }
    try {
      if (widget.ble.connected) await widget.ble.cameraPreview(false);
    } catch (error) {
      _notice(error);
    }
    if (!mounted) return;
    setState(() => canPop = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.pop(context);
    });
  }

  @override
  void dispose() {
    review.dispose();
    transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: canPop,
    onPopInvokedWithResult: (didPop, _) {
      if (!didPop) unawaited(_close());
    },
    child: ListenableBuilder(
      listenable: Listenable.merge([widget.ble, widget.app, review]),
      builder: (context, _) {
        final bytes = review.photo?.bytes ?? widget.ble.previewBytes;
        final reviewing = review.photo != null;
        final documents = widget.app.documents
            .where(
              (item) =>
                  item.name.startsWith('OV5640_') ||
                  item.name.startsWith('OV3660_'),
            )
            .toList();
        return Scaffold(
          appBar: AppBar(
            title: const Text('Camera OV5640 · 5 MP'),
            actions: [
              IconButton(
                tooltip: 'Cấu hình camera',
                icon: const Icon(Icons.tune),
                onPressed:
                    !closing &&
                        !reviewing &&
                        _capture == null &&
                        !widget.ble.cameraBusy &&
                        !widget.ble.cameraConfigBusy
                    ? () => showModalBottomSheet<void>(
                        context: context,
                        isScrollControlled: true,
                        useSafeArea: true,
                        builder: (_) => CameraSettingsSheet(ble: widget.ble),
                      )
                    : null,
              ),
            ],
            leading: IconButton(
              onPressed: _close,
              icon: const Icon(Icons.close),
            ),
          ),
          body: SafeArea(
            child: Stack(
              children: [
                Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
                      child: Text(widget.ble.wifiMessage),
                    ),
                    Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(
                        closing
                            ? 'Đang lưu ảnh và đóng camera…'
                            : reviewing
                            ? review.error != null
                                  ? '${review.error} · Bấm Bỏ qua để lưu lại.'
                                  : 'Ảnh vừa chụp · Xem 3 giây hoặc Bỏ qua để chụp tiếp'
                            : widget.ble.cameraMessage,
                      ),
                    ),
                    Expanded(
                      child: ColoredBox(
                        color: Colors.black,
                        child: SizedBox.expand(
                          child: bytes == null
                              ? Center(
                                  child: widget.ble.previewing
                                      ? const CircularProgressIndicator()
                                      : const Text(
                                          'Chưa có hình từ camera.\nXem trạng thái phía trên hoặc bấm Mở lại preview.',
                                          textAlign: TextAlign.center,
                                          style: TextStyle(color: Colors.white),
                                        ),
                                )
                              : InteractiveViewer(
                                  transformationController: transform,
                                  minScale: 1,
                                  maxScale: 8,
                                  child: Center(
                                    child: Image.memory(
                                      bytes,
                                      fit: BoxFit.contain,
                                      gaplessPlayback: true,
                                      errorBuilder: (_, _, _) => const Center(
                                        child: Text(
                                          'Không giải mã được ảnh.',
                                          style: TextStyle(color: Colors.white),
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                        ),
                      ),
                    ),
                    if (widget.ble.cameraBusy || review.saving)
                      LinearProgressIndicator(
                        value: review.saving ? null : widget.ble.cameraProgress,
                      ),
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Wrap(
                        spacing: 12,
                        runSpacing: 8,
                        children: [
                          FilledButton.icon(
                            onPressed:
                                !closing &&
                                    !reviewing &&
                                    _capture == null &&
                                    !widget.ble.cameraConfigBusy &&
                                    widget.ble.connected &&
                                    widget.ble.previewBytes != null
                                ? _shoot
                                : null,
                            icon: const Icon(Icons.camera_alt),
                            label: const Text('Chụp OV5640'),
                          ),
                          OutlinedButton(
                            onPressed: reviewing && !review.saving && !closing
                                ? review.finish
                                : null,
                            child: const Text('Bỏ qua · Chụp tiếp'),
                          ),
                          TextButton(
                            onPressed:
                                !closing &&
                                    !reviewing &&
                                    !widget.ble.cameraBusy &&
                                    !widget.ble.cameraConfigBusy
                                ? _preview
                                : null,
                            child: const Text('Mở lại preview'),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                if (documents.isNotEmpty && !queueHidden)
                  Positioned(
                    right: 12,
                    bottom: 92,
                    child: SizedBox(
                      width:
                          MediaQuery.sizeOf(
                            context,
                          ).width.clamp(200, 330).toDouble() -
                          24,
                      child: Card(
                        child: Padding(
                          padding: const EdgeInsets.all(10),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              InkWell(
                                onTap: () =>
                                    setState(() => expanded = !expanded),
                                child: Padding(
                                  padding: const EdgeInsets.all(8),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Flexible(
                                        child: Text(
                                          'Ảnh camera · ${documents.where((item) => item.status == DocumentStatus.done).length}/${documents.length} hoàn tất  ${expanded ? '▾' : '▴'}',
                                        ),
                                      ),
                                      IconButton(
                                        tooltip: 'Ẩn tiến trình',
                                        onPressed: () =>
                                            setState(() => queueHidden = true),
                                        icon: const Icon(Icons.close, size: 18),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                              if (expanded)
                                for (final item in documents.reversed.take(
                                  4,
                                )) ...[
                                  Text(
                                    item.name,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  Text(switch (item.status) {
                                    DocumentStatus.ready => 'Chờ nhận diện',
                                    DocumentStatus.processing =>
                                      'Đang nhận diện',
                                    DocumentStatus.done => 'Hoàn tất',
                                    DocumentStatus.error => 'Có lỗi',
                                    DocumentStatus.cancelled => 'Đã dừng',
                                  }),
                                  LinearProgressIndicator(
                                    value: item.status == DocumentStatus.done
                                        ? 1
                                        : item.status ==
                                              DocumentStatus.processing
                                        ? widget.app.progress
                                        : 0,
                                  ),
                                  const SizedBox(height: 8),
                                ],
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    ),
  );
}
