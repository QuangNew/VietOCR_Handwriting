import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image/image.dart' as img;
import '../domain/app_controller.dart';
import '../domain/document.dart';
import '../ocr/image_processing.dart' show blackWhitePhoto;
import '../ocr/shape_crop.dart';

typedef CropJob = (
  Uint8List bytes,
  int rotation,
  int x,
  int y,
  int width,
  int height,
);

Uint8List blackWhiteOriginal((Uint8List, int) job) =>
    blackWhitePhoto(job.$1, rotation: job.$2);

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
  String cropShape = 'rectangle';
  double cropAngle = 0;
  List<CropPoint> stroke = [];
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
    if (cropShape == 'freehand' && stroke.length >= 3) {
      final points = stroke.map((p) => Offset(p.$1, p.$2)).toList();
      return _strokeBounds(points);
    }
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

  Rect _strokeBounds(List<Offset> points) {
    final path = Path()..addPolygon(points, true);
    return path.getBounds();
  }

  List<CropPoint> get cropPoints => cropShape == 'freehand'
      ? stroke
      : (start == null || end == null
            ? []
            : [(start!.dx, start!.dy), (end!.dx, end!.dy)]);

  Future<void> _crop() async {
    final rect = selection;
    if (rect == null || saving || widget.app.importing) return;
    setState(() => saving = true);
    try {
      final result = await compute(cropSelection, (
        bytes: await File(widget.item.path).readAsBytes(),
        rotation: widget.item.rotation,
        shape: cropShape,
        points: List<CropPoint>.of(cropPoints),
        angle: cropAngle,
      ));
      final name = 'Crop_${DateTime.now().millisecondsSinceEpoch}.png';
      await widget.app.importImages(
        [(result, name)],
        enqueue: false,
        preserveResolution: true,
      );
      if (!widget.app.documents.any((item) => item.name == name)) {
        throw StateError(widget.app.message);
      }
      _notice('Đã thêm bản nháp crop. Nhấn Gửi khi sẵn sàng.');
    } catch (failure) {
      _notice(AppController.readableError(failure));
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> _blackWhite() async {
    if (saving || widget.app.importing || widget.app.busy) return;
    setState(() => saving = true);
    try {
      final bytes = await compute(blackWhiteOriginal, (
        await File(widget.item.path).readAsBytes(),
        widget.item.rotation,
      ));
      final name =
          '${widget.item.name.split('.').first}_BW_${DateTime.now().millisecondsSinceEpoch}.png';
      await widget.app.importImages(
        [(bytes, name)],
        enqueue: false,
        preserveResolution: true,
      );
      if (!widget.app.documents.any((item) => item.name == name)) {
        throw StateError(widget.app.message);
      }
      _notice(
        'Đã thêm bản đen trắng. Ảnh gốc được giữ nguyên; chọn bản phù hợp để nhận diện.',
      );
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
                        behavior: HitTestBehavior.opaque,
                        onPanStart: cropping
                            ? (details) => setState(() {
                                start = point(details.localPosition);
                                end = start;
                                stroke = [(start!.dx, start!.dy)];
                                cropAngle = 0;
                              })
                            : null,
                        onPanUpdate: cropping
                            ? (details) => setState(() {
                                end = point(details.localPosition);
                                if (cropShape == 'freehand' &&
                                    stroke.length < 4096) {
                                  stroke.add((end!.dx, end!.dy));
                                }
                              })
                            : null,
                        child: IgnorePointer(
                          ignoring: cropping,
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
                                            rotateOutline(
                                              selectionOutline(
                                                cropPoints,
                                                cropShape,
                                              ),
                                              cropAngle,
                                            ),
                                            imageRect,
                                            size!,
                                            Theme.of(
                                              context,
                                            ).colorScheme.primary,
                                          ),
                                        ),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          if (cropping)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Wrap(
                    spacing: 8,
                    children: [
                      for (final mode in [
                        ('rectangle', 'Chữ nhật'),
                        ('ellipse', 'Elip'),
                        ('freehand', 'Tự vẽ'),
                      ])
                        ChoiceChip(
                          label: Text(mode.$2),
                          selected: cropShape == mode.$1,
                          onSelected: (_) => setState(() {
                            cropShape = mode.$1;
                            start = end = null;
                            stroke = [];
                            cropAngle = 0;
                          }),
                        ),
                    ],
                  ),
                  Row(
                    children: [
                      Text('Xoay ${cropAngle.round()}°'),
                      Expanded(
                        child: Slider(
                          value: cropAngle,
                          min: -180,
                          max: 180,
                          divisions: 360,
                          onChanged: selection == null
                              ? null
                              : (v) => setState(() => cropAngle = v),
                        ),
                      ),
                      TextButton(
                        onPressed: () => setState(() => cropAngle = 0),
                        child: const Text('0°'),
                      ),
                    ],
                  ),
                ],
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
                OutlinedButton.icon(
                  onPressed: saving || widget.app.importing
                      ? null
                      : _blackWhite,
                  icon: const Icon(Icons.contrast),
                  label: const Text('Tạo bản đen trắng OCR'),
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
  final List<CropPoint> selection;
  final Rect imageRect;
  final Size size;
  final Color color;
  @override
  void paint(Canvas canvas, Size _) {
    final path = Path()
      ..addPolygon(
        selection
            .map(
              (p) => Offset(
                imageRect.left + p.$1 / size.width * imageRect.width,
                imageRect.top + p.$2 / size.height * imageRect.height,
              ),
            )
            .toList(),
        true,
      );
    canvas.drawPath(
      path,
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
