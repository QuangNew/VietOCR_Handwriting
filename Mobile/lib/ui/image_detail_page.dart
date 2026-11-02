import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image/image.dart' as img;
import '../domain/app_controller.dart';
import '../domain/document.dart';

typedef CropJob = (
  Uint8List bytes,
  int rotation,
  int x,
  int y,
  int width,
  int height,
);

Uint8List cropOriginal(CropJob job) {
  final (bytes, rotation, x, y, width, height) = job;
  final decoded = img.decodeImage(bytes);
  if (decoded == null) throw const FormatException('Không mở được ảnh gốc.');
  final oriented = img.bakeOrientation(decoded);
  final image = rotation % 4 == 0
      ? oriented
      : img.copyRotate(oriented, angle: (rotation % 4) * 90);
  if (x < 0 ||
      y < 0 ||
      width < 2 ||
      height < 2 ||
      x + width > image.width ||
      y + height > image.height) {
    throw const FormatException('Vùng crop nằm ngoài ảnh.');
  }
  return Uint8List.fromList(
    img.encodePng(
      img.copyCrop(image, x: x, y: y, width: width, height: height),
    ),
  );
}

class ImageDetailPage extends StatefulWidget {
  const ImageDetailPage({super.key, required this.app, required this.item});
  final AppController app;
  final Document item;
  @override
  State<ImageDetailPage> createState() => _ImageDetailPageState();
}

class _ImageDetailPageState extends State<ImageDetailPage> {
  final transform = TransformationController();
  ui.Size? size;
  Offset? start, end;
  bool cropping = false, saving = false;
  String? error;

  @override
  void initState() {
    super.initState();
    _loadSize();
  }

  Future<void> _loadSize() async {
    try {
      final codec = await ui.instantiateImageCodec(
        await File(widget.item.path).readAsBytes(),
      );
      final frame = await codec.getNextFrame();
      final rotated = widget.item.rotation.isOdd;
      final value = ui.Size(
        (rotated ? frame.image.height : frame.image.width).toDouble(),
        (rotated ? frame.image.width : frame.image.height).toDouble(),
      );
      frame.image.dispose();
      codec.dispose();
      if (mounted) setState(() => size = value);
    } catch (failure) {
      if (mounted) setState(() => error = '$failure');
    }
  }

  void _notice(String message) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _save() async {
    try {
      final saved = await const MethodChannel('vietocr/device')
          .invokeMethod<bool>('saveImage', {
            'path': widget.item.path,
            'name': widget.item.name,
          });
      if (saved == true) _notice('Đã lưu ảnh gốc.');
    } catch (failure) {
      _notice(AppController.readableError(failure));
    }
  }

  Rect? get selection {
    if (start == null || end == null || size == null) return null;
    final rect = Rect.fromPoints(start!, end!);
    final x = rect.left.floor().clamp(0, size!.width.toInt());
    final y = rect.top.floor().clamp(0, size!.height.toInt());
    final right = rect.right.ceil().clamp(0, size!.width.toInt());
    final bottom = rect.bottom.ceil().clamp(0, size!.height.toInt());
    return right - x < 2 || bottom - y < 2
        ? null
        : Rect.fromLTRB(
            x.toDouble(),
            y.toDouble(),
            right.toDouble(),
            bottom.toDouble(),
          );
  }

  Future<void> _crop() async {
    final rect = selection;
    if (rect == null || saving || widget.app.importing) return;
    setState(() => saving = true);
    try {
      final result = await compute(cropOriginal, (
        await File(widget.item.path).readAsBytes(),
        widget.item.rotation,
        rect.left.toInt(),
        rect.top.toInt(),
        rect.width.toInt(),
        rect.height.toInt(),
      ));
      await widget.app.importImages([
        (result, 'Crop_${DateTime.now().millisecondsSinceEpoch}.png'),
      ], enqueue: true);
      _notice('Đã thêm vùng crop vào hàng đợi. Ảnh gốc được giữ nguyên.');
    } catch (failure) {
      _notice(AppController.readableError(failure));
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  void dispose() {
    transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Ảnh gốc · Zoom / Crop'),
      actions: [
        IconButton(
          onPressed: _save,
          tooltip: 'Tải ảnh gốc',
          icon: const Icon(Icons.download_outlined),
        ),
      ],
    ),
    body: SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              size == null
                  ? error ?? 'Đang mở ảnh…'
                  : '${size!.width.toInt()} × ${size!.height.toInt()} px · Chụm tay để zoom, kéo để di chuyển',
            ),
          ),
          Expanded(
            child: size == null
                ? const Center(child: CircularProgressIndicator())
                : LayoutBuilder(
                    builder: (context, constraints) {
                      final fitted = applyBoxFit(
                        BoxFit.contain,
                        size!,
                        constraints.biggest,
                      ).destination;
                      final imageRect = Alignment.center.inscribe(
                        fitted,
                        Offset.zero & constraints.biggest,
                      );
                      Offset point(Offset position) {
                        final scene = transform.toScene(position);
                        return Offset(
                          ((scene.dx - imageRect.left) /
                                  imageRect.width *
                                  size!.width)
                              .clamp(0, size!.width),
                          ((scene.dy - imageRect.top) /
                                  imageRect.height *
                                  size!.height)
                              .clamp(0, size!.height),
                        );
                      }

                      return GestureDetector(
                        onPanStart: cropping
                            ? (details) => setState(() {
                                start = point(details.localPosition);
                                end = start;
                              })
                            : null,
                        onPanUpdate: cropping
                            ? (details) => setState(
                                () => end = point(details.localPosition),
                              )
                            : null,
                        child: InteractiveViewer(
                          transformationController: transform,
                          panEnabled: !cropping,
                          scaleEnabled: !cropping,
                          maxScale: 16,
                          child: SizedBox.expand(
                            child: Stack(
                              children: [
                                Positioned.fill(
                                  child: RotatedBox(
                                    quarterTurns: widget.item.rotation,
                                    child: Image.file(
                                      File(widget.item.path),
                                      fit: BoxFit.contain,
                                    ),
                                  ),
                                ),
                                if (selection != null)
                                  Positioned.fill(
                                    child: IgnorePointer(
                                      child: CustomPaint(
                                        painter: _CropPainter(
                                          selection!,
                                          imageRect,
                                          size!,
                                          Theme.of(context).colorScheme.primary,
                                        ),
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () => transform.value = Matrix4.identity(),
                  child: const Text('Vừa màn hình'),
                ),
                FilterChip(
                  label: const Text('Chọn vùng crop'),
                  selected: cropping,
                  onSelected: (value) => setState(() => cropping = value),
                ),
                FilledButton(
                  onPressed: selection != null && !saving ? _crop : null,
                  child: Text(
                    saving ? 'Đang lưu…' : 'Thêm vùng crop vào hàng đợi',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

class _CropPainter extends CustomPainter {
  _CropPainter(this.selection, this.imageRect, this.size, this.color);
  final Rect selection, imageRect;
  final Size size;
  final Color color;
  @override
  void paint(Canvas canvas, Size _) {
    final rect = Rect.fromLTRB(
      imageRect.left + selection.left / size.width * imageRect.width,
      imageRect.top + selection.top / size.height * imageRect.height,
      imageRect.left + selection.right / size.width * imageRect.width,
      imageRect.top + selection.bottom / size.height * imageRect.height,
    );
    canvas.drawRect(
      rect,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant _CropPainter old) =>
      old.selection != selection ||
      old.imageRect != imageRect ||
      old.color != color;
}
