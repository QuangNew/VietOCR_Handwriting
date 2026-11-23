import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../domain/document.dart';
import '../ocr/paper_detector.dart';

enum DocumentViewMode { original, digital, compare }

/// Interactive mobile stage supporting:
/// 1) Ảnh gốc: Google Lens paper brackets + draggable 4 corners & 4 edges + tappable text line highlights.
/// 2) Ảnh văn bản: Clean digital Word document rendering synced with recognized/edited text.
/// 3) Đối chiếu: Finger-friendly ⇄ horizontal slider (drag RIGHT -> reveals Ảnh văn bản on left;
///    drag LEFT -> reveals Ảnh gốc on right).
class LensStage extends StatefulWidget {
  const LensStage({
    super.key,
    required this.item,
    required this.mode,
    required this.lensEnabled,
    required this.canSend,
    required this.onQuadChanged,
    required this.onCropAndSend,
    required this.onCopyText,
    this.onTapBackground,
    this.onOpenFullscreen,
    this.isFullscreen = false,
  });

  final Document item;
  final DocumentViewMode mode;
  final bool lensEnabled;
  final bool canSend;
  final ValueChanged<List<Point2D>?> onQuadChanged;
  final Future<void> Function(List<Point2D> quad, {required bool autoSend})
  onCropAndSend;
  final ValueChanged<String> onCopyText;
  final VoidCallback? onTapBackground;
  final VoidCallback? onOpenFullscreen;
  final bool isFullscreen;

  @override
  State<LensStage> createState() => _LensStageState();
}

class _LensStageState extends State<LensStage> {
  static final _autoPaperCache = <String, DetectedPaperResult?>{};
  static final _warpedPhotoCache = <String, Uint8List>{};

  Size? _imageSize;
  DetectedPaperResult? _clientPaper;
  Uint8List? _warpedPhotoBytes;
  String? _warpedPhotoKey;
  List<Point2D>? _draggingQuad;
  String? _dragKind; // 'corner' | 'edge'
  int? _dragIndex;
  Offset? _dragStartImg;
  List<Point2D>? _dragStartQuad;

  final Set<int> _selectedLineIds = {};
  int? _highlightedLineId;
  double _compareSplit = 0.5; // 0..1: left 0..split = Ảnh văn bản, right split..1 = Ảnh gốc
  bool _compareDragging = false;
  bool _cropping = false;

  String get _cacheKey => '${widget.item.id}:${widget.item.path}:${widget.item.rotation}';

  @override
  void initState() {
    super.initState();
    _loadImageAndPaper();
  }

  @override
  void didUpdateWidget(covariant LensStage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.item.id != widget.item.id ||
        oldWidget.item.path != widget.item.path ||
        oldWidget.item.rotation != widget.item.rotation) {
      _selectedLineIds.clear();
      _highlightedLineId = null;
      _draggingQuad = null;
      _warpedPhotoBytes = null;
      _warpedPhotoKey = null;
      _loadImageAndPaper();
    } else if (widget.mode == DocumentViewMode.compare) {
      _ensureWarpedPhoto();
    }
  }

  Future<void> _ensureWarpedPhoto() async {
    final quadInfo = _resolveActiveQuad();
    if (!quadInfo.detected || quadInfo.quad == null) return;
    final quadKey = quadInfo.quad!
        .map((p) => '${p[0].toStringAsFixed(1)},${p[1].toStringAsFixed(1)}')
        .join(';');
    final fullKey = '$_cacheKey:$quadKey';
    if (_warpedPhotoKey == fullKey && _warpedPhotoBytes != null) return;
    if (_warpedPhotoCache.containsKey(fullKey)) {
      if (mounted) {
        setState(() {
          _warpedPhotoKey = fullKey;
          _warpedPhotoBytes = _warpedPhotoCache[fullKey];
        });
      }
      return;
    }
    try {
      final file = File(widget.item.path);
      if (!await file.exists()) return;
      final raw = await file.readAsBytes();
      final warped = await compute(
        warpPhotoToFlat90Bytes,
        (
          bytes: raw,
          rotation: widget.item.rotation,
          quad: quadInfo.quad!,
          maxSide: 820,
          png: false,
        ),
      );
      _warpedPhotoCache[fullKey] = warped;
      if (_warpedPhotoCache.length > 12) {
        _warpedPhotoCache.remove(_warpedPhotoCache.keys.first);
      }
      if (mounted) {
        setState(() {
          _warpedPhotoKey = fullKey;
          _warpedPhotoBytes = warped;
        });
      }
    } catch (_) {
      /* fallback cleanly to original photo if warp fails */
    }
  }

  Future<void> _loadImageAndPaper() async {
    final key = _cacheKey;
    try {
      final file = File(widget.item.path);
      if (!await file.exists()) return;
      final buffer = await ui.ImmutableBuffer.fromFilePath(widget.item.path);
      try {
        final descriptor = await ui.ImageDescriptor.encoded(buffer);
        try {
          final rotated = widget.item.rotation.isOdd;
          final sz = Size(
            (rotated ? descriptor.height : descriptor.width).toDouble(),
            (rotated ? descriptor.width : descriptor.height).toDouble(),
          );
          if (mounted && key == _cacheKey) {
            setState(() => _imageSize = sz);
          }
        } finally {
          descriptor.dispose();
        }
      } finally {
        buffer.dispose();
      }
      if (widget.item.lens != null) return;
      if (_autoPaperCache.containsKey(key)) {
        if (mounted && key == _cacheKey) {
          setState(() => _clientPaper = _autoPaperCache[key]);
        }
        return;
      }
      final bytes = await file.readAsBytes();
      final detected = await compute(
        detectPaperQuadFromFileBytes,
        (bytes, widget.item.rotation),
      );
      _autoPaperCache[key] = detected;
      if (_autoPaperCache.length > 40) {
        _autoPaperCache.remove(_autoPaperCache.keys.first);
      }
      if (mounted && key == _cacheKey) {
        setState(() => _clientPaper = detected);
      }
    } catch (_) {
      /* ignore unreadable fixture/temp paths gracefully */
    }
  }

  Size get _sourceSize {
    final lens = widget.item.lens;
    if (lens != null) {
      final sw = (lens['sourceWidth'] as num?)?.toDouble() ?? 0;
      final sh = (lens['sourceHeight'] as num?)?.toDouble() ?? 0;
      if (sw > 0 && sh > 0) return Size(sw, sh);
    }
    if (_clientPaper != null) {
      return Size(_clientPaper!.sourceWidth, _clientPaper!.sourceHeight);
    }
    return _imageSize ?? const Size(1000, 1000);
  }

  List<Map<String, dynamic>> get _lensLines {
    final raw = widget.item.lens?['lines'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  ({List<Point2D>? quad, bool detected, bool isCustom}) _resolveActiveQuad() {
    if (_draggingQuad != null && _draggingQuad!.length == 4) {
      return (quad: _draggingQuad, detected: true, isCustom: true);
    }
    if (widget.item.customQuad != null && widget.item.customQuad!.length == 4) {
      return (quad: widget.item.customQuad, detected: true, isCustom: true);
    }
    final serverQuad = _parseQuad(widget.item.lens?['paperQuad']);
    if (serverQuad != null) {
      final det = widget.item.lens?['paperDetected'] as bool? ?? true;
      return (quad: serverQuad, detected: det, isCustom: false);
    }
    if (_clientPaper != null) {
      return (quad: _clientPaper!.paperQuad, detected: true, isCustom: false);
    }
    if (_imageSize != null && _imageSize!.width >= 32 && _imageSize!.height >= 32) {
      final w = _sourceSize.width, h = _sourceSize.height;
      final px = w * 0.03, py = h * 0.03;
      return (
        quad: [
          [px, py],
          [w - px, py],
          [w - px, h - py],
          [px, h - py],
        ],
        detected: false,
        isCustom: false,
      );
    }
    return (quad: null, detected: false, isCustom: false);
  }

  List<Point2D>? _parseQuad(dynamic raw) {
    if (raw is! List || raw.length != 4) return null;
    final out = <Point2D>[];
    for (final p in raw) {
      if (p is List && p.length >= 2 && p[0] is num && p[1] is num) {
        out.add([(p[0] as num).toDouble(), (p[1] as num).toDouble()]);
      }
    }
    return out.length == 4 ? (orderQuad(out) ?? out) : null;
  }

  Rect _containedRect(Size box, Size src) {
    if (box.width <= 0 || box.height <= 0 || src.width <= 0 || src.height <= 0) {
      return Rect.zero;
    }
    final fitted = applyBoxFit(BoxFit.contain, src, box).destination;
    return Alignment.center.inscribe(fitted, Offset.zero & box);
  }

  Offset _srcToWidget(Point2D p, Rect rect, Size src) => Offset(
    rect.left + (p[0] / src.width) * rect.width,
    rect.top + (p[1] / src.height) * rect.height,
  );

  Point2D _widgetToSrc(Offset local, Rect rect, Size src) => [
    (((local.dx - rect.left) / math.max(1.0, rect.width)) * src.width)
        .clamp(0.0, src.width),
    (((local.dy - rect.top) / math.max(1.0, rect.height)) * src.height)
        .clamp(0.0, src.height),
  ];

  void _handleLensPanStart(
    DragStartDetails details,
    Rect imageRect,
    Size src,
    List<Point2D> quad,
  ) {
    final pos = details.localPosition;
    const hitRadius = 34.0;
    var bestDist = hitRadius;
    String? hitKind;
    int? hitIdx;

    // 1) Check 4 corners first (highest priority)
    for (var i = 0; i < 4; i++) {
      final c = _srcToWidget(quad[i], imageRect, src);
      final d = (c - pos).distance;
      if (d < bestDist) {
        bestDist = d;
        hitKind = 'corner';
        hitIdx = i;
      }
    }
    // 2) Check 4 edge midpoints
    if (hitKind == null) {
      bestDist = 30.0;
      for (var i = 0; i < 4; i++) {
        final a = _srcToWidget(quad[i], imageRect, src);
        final b = _srcToWidget(quad[(i + 1) % 4], imageRect, src);
        final mid = Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
        final d = (mid - pos).distance;
        if (d < bestDist) {
          bestDist = d;
          hitKind = 'edge';
          hitIdx = i;
        }
      }
    }
    if (hitKind == null || hitIdx == null) return;
    final imgPt = _widgetToSrc(pos, imageRect, src);
    setState(() {
      _dragKind = hitKind;
      _dragIndex = hitIdx;
      _dragStartImg = Offset(imgPt[0], imgPt[1]);
      _dragStartQuad = quad.map((p) => <double>[p[0], p[1]]).toList();
      _draggingQuad = quad.map((p) => <double>[p[0], p[1]]).toList();
    });
  }

  void _handleLensPanUpdate(
    DragUpdateDetails details,
    Rect imageRect,
    Size src,
  ) {
    if (_dragKind == null || _dragIndex == null || _dragStartQuad == null) return;
    final imgPt = _widgetToSrc(details.localPosition, imageRect, src);
    final next = _dragStartQuad!.map((p) => <double>[p[0], p[1]]).toList();

    if (_dragKind == 'corner') {
      next[_dragIndex!] = [
        (imgPt[0] * 10).round() / 10,
        (imgPt[1] * 10).round() / 10,
      ];
    } else {
      final dx = imgPt[0] - _dragStartImg!.dx;
      final dy = imgPt[1] - _dragStartImg!.dy;
      final i = _dragIndex!;
      final j = (i + 1) % 4;
      next[i] = [
        ((_dragStartQuad![i][0] + dx).clamp(0.0, src.width) * 10).round() / 10,
        ((_dragStartQuad![i][1] + dy).clamp(0.0, src.height) * 10).round() / 10,
      ];
      next[j] = [
        ((_dragStartQuad![j][0] + dx).clamp(0.0, src.width) * 10).round() / 10,
        ((_dragStartQuad![j][1] + dy).clamp(0.0, src.height) * 10).round() / 10,
      ];
    }

    final b = polygonBounds(next);
    if (b.width < 40 || b.height < 40) return;
    final ordered = orderQuad(next) ?? next;
    final lines = _lensLines;
    setState(() {
      _draggingQuad = ordered;
      if (lines.isNotEmpty) {
        _selectedLineIds
          ..clear()
          ..addAll(
            linesInsideQuad(lines, ordered)
                .map((l) => (l['id'] as num?)?.toInt())
                .whereType<int>(),
          );
      }
    });
  }

  void _handleLensPanEnd() {
    if (_draggingQuad == null) return;
    final committed = _draggingQuad!;
    setState(() {
      _dragKind = null;
      _dragIndex = null;
      _dragStartImg = null;
      _dragStartQuad = null;
      _draggingQuad = null;
    });
    widget.onQuadChanged(committed);
  }

  void _handleTapOriginal(Offset pos, Rect imageRect, Size src) {
    final lines = _lensLines;
    if (widget.lensEnabled && lines.isNotEmpty && imageRect.contains(pos)) {
      final pt = _widgetToSrc(pos, imageRect, src);
      for (final line in lines) {
        final rawPoly = line['polygon'];
        if (rawPoly is! List || rawPoly.length < 3) continue;
        final poly = rawPoly
            .whereType<List>()
            .where((p) => p.length >= 2)
            .map(
              (p) => <double>[(p[0] as num).toDouble(), (p[1] as num).toDouble()],
            )
            .toList();
        if (poly.length >= 3 && pointInPolygon(pt[0], pt[1], poly)) {
          final id = (line['id'] as num?)?.toInt();
          if (id != null) {
            setState(() {
              if (!_selectedLineIds.remove(id)) _selectedLineIds.add(id);
            });
            return;
          }
        }
      }
    }
    widget.onTapBackground?.call();
  }

  void _updateCompareFromX(double dx, Rect imageRect) {
    if (imageRect.width <= 0) return;
    final pct = ((dx - imageRect.left) / imageRect.width).clamp(0.0, 1.0);
    setState(() => _compareSplit = pct);
  }

  Future<void> _triggerCrop(List<Point2D> quad) async {
    if (_cropping) return;
    setState(() => _cropping = true);
    try {
      await widget.onCropAndSend(quad, autoSend: widget.canSend);
    } finally {
      if (mounted) setState(() => _cropping = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final quadInfo = _resolveActiveQuad();
    final lines = _lensLines;
    final hasLines = lines.isNotEmpty;
    final activeQuad = quadInfo.detected ? quadInfo.quad : null;
    if (widget.mode == DocumentViewMode.compare && activeQuad != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _ensureWarpedPhoto());
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final box = constraints.biggest;
        final src = _sourceSize;
        final origRect = _containedRect(box, src);
        final flatSize = computeQuadFlatSize(activeQuad, src.width, src.height);
        final pad = widget.mode == DocumentViewMode.original ? 0.0 : 8.0;
        final innerBox = Size(
          math.max(24, box.width - pad * 2),
          math.max(24, box.height - pad * 2),
        );
        final fittedFlat = _containedRect(
          innerBox,
          Size(flatSize.width.toDouble(), flatSize.height.toDouble()),
        );
        final flatRect = fittedFlat.shift(Offset(pad, pad));
        final imageRect =
            widget.mode == DocumentViewMode.original ? origRect : flatRect;

        return ClipRRect(
          borderRadius: BorderRadius.circular(widget.isFullscreen ? 0 : 14),
          child: ColoredBox(
            color: isDark ? const Color(0xff0d1212) : const Color(0xffd2dad7),
            child: Stack(
              fit: StackFit.expand,
              children: [
                // Layer 1: Original photo (in Original mode) OR 90-deg flat perspective-warped photo (in Compare mode)
                if (widget.mode == DocumentViewMode.original)
                  Positioned.fromRect(
                    rect: origRect,
                    child: RotatedBox(
                      quarterTurns: widget.item.rotation,
                      child: Image.file(
                        File(widget.item.path),
                        fit: BoxFit.fill,
                        cacheWidth: 1400,
                        errorBuilder: (_, _, _) => const Center(
                          child: Icon(Icons.broken_image_outlined, size: 36),
                        ),
                      ),
                    ),
                  )
                else if (widget.mode == DocumentViewMode.compare)
                  Positioned.fromRect(
                    rect: flatRect,
                    child: _warpedPhotoBytes != null
                        ? Image.memory(
                            _warpedPhotoBytes!,
                            fit: BoxFit.fill,
                            gaplessPlayback: true,
                          )
                        : RotatedBox(
                            quarterTurns: widget.item.rotation,
                            child: Image.file(
                              File(widget.item.path),
                              fit: BoxFit.fill,
                              cacheWidth: 1400,
                              errorBuilder: (_, _, _) => const Center(
                                child: Icon(Icons.broken_image_outlined, size: 36),
                              ),
                            ),
                          ),
                  ),

                // Layer 2: 90-deg flat Word page (full in Digital mode, clipped 0..split in Compare mode)
                if (widget.mode != DocumentViewMode.original &&
                    flatRect.width > 12 &&
                    flatRect.height > 12)
                  Positioned.fromRect(
                    rect: flatRect,
                    child: GestureDetector(
                      behavior: HitTestBehavior.translucent,
                      onTapUp: widget.mode == DocumentViewMode.digital
                          ? (d) {
                              final hitId = DigitalDocumentPainter.hitTestLineId(
                                local: d.localPosition,
                                size: flatRect.size,
                                text: widget.item.text,
                                lens: widget.item.lens,
                                paperQuad: activeQuad,
                                sourceSize: src,
                              );
                              setState(() {
                                _highlightedLineId =
                                    _highlightedLineId == hitId ? null : hitId;
                              });
                            }
                          : null,
                      child: ClipRect(
                        clipper: widget.mode == DocumentViewMode.compare
                            ? _LeftSplitClipper(_compareSplit)
                            : null,
                        child: CustomPaint(
                          painter: DigitalDocumentPainter(
                            text: widget.item.text,
                            lens: widget.item.lens,
                            paperQuad: activeQuad,
                            sourceSize: src,
                            isDark: isDark,
                            highlightedLineId: _highlightedLineId,
                          ),
                        ),
                      ),
                    ),
                  ),

                // Layer 3: Interactive Google Lens Overlay (Original mode only)
                if (widget.mode == DocumentViewMode.original &&
                    widget.lensEnabled &&
                    imageRect.width > 12 &&
                    imageRect.height > 12 &&
                    (quadInfo.quad != null || hasLines))
                  Positioned.fill(
                    child: GestureDetector(
                      behavior: HitTestBehavior.translucent,
                      onTapUp: (d) =>
                          _handleTapOriginal(d.localPosition, imageRect, src),
                      onPanStart: quadInfo.quad != null
                          ? (d) => _handleLensPanStart(
                              d,
                              imageRect,
                              src,
                              quadInfo.quad!,
                            )
                          : null,
                      onPanUpdate: quadInfo.quad != null
                          ? (d) => _handleLensPanUpdate(d, imageRect, src)
                          : null,
                      onPanEnd: (_) => _handleLensPanEnd(),
                      onPanCancel: _handleLensPanEnd,
                      child: CustomPaint(
                        painter: _LensOverlayPainter(
                          imageRect: imageRect,
                          sourceSize: src,
                          paperQuad: quadInfo.quad,
                          showScrim:
                              quadInfo.detected || hasLines || quadInfo.isCustom,
                          showDashedGuide:
                              quadInfo.isCustom || _dragKind != null,
                          lines: lines,
                          selectedLineIds: _selectedLineIds,
                          activeCorner:
                              _dragKind == 'corner' ? _dragIndex : null,
                          activeEdge: _dragKind == 'edge' ? _dragIndex : null,
                        ),
                      ),
                    ),
                  )
                else if (widget.mode == DocumentViewMode.original)
                  Positioned.fill(
                    child: GestureDetector(
                      behavior: HitTestBehavior.translucent,
                      onTap: widget.onTapBackground,
                    ),
                  ),

                // Layer 4: Interactive Đối chiếu drag divider (drag RIGHT -> Ảnh văn bản, LEFT -> Ảnh gốc)
                if (widget.mode == DocumentViewMode.compare &&
                    imageRect.width > 12 &&
                    imageRect.height > 12)
                  Positioned.fromRect(
                    rect: imageRect,
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTapDown: (d) => _updateCompareFromX(
                        imageRect.left + d.localPosition.dx,
                        imageRect,
                      ),
                      onHorizontalDragStart: (d) {
                        setState(() => _compareDragging = true);
                        _updateCompareFromX(
                          imageRect.left + d.localPosition.dx,
                          imageRect,
                        );
                      },
                      onHorizontalDragUpdate: (d) => _updateCompareFromX(
                        imageRect.left + d.localPosition.dx,
                        imageRect,
                      ),
                      onHorizontalDragEnd: (_) =>
                          setState(() => _compareDragging = false),
                      onHorizontalDragCancel: () =>
                          setState(() => _compareDragging = false),
                      child: Stack(
                        clipBehavior: Clip.none,
                        children: [
                          Positioned(
                            top: 8,
                            left: 8,
                            child: AnimatedOpacity(
                              duration: const Duration(milliseconds: 120),
                              opacity: _compareSplit < 0.16 ? 0 : 1,
                              child: const _CompareBadge('Ảnh văn bản'),
                            ),
                          ),
                          Positioned(
                            top: 8,
                            right: 8,
                            child: AnimatedOpacity(
                              duration: const Duration(milliseconds: 120),
                              opacity: _compareSplit > 0.84 ? 0 : 1,
                              child: const _CompareBadge('Ảnh gốc'),
                            ),
                          ),
                          Positioned(
                            left: imageRect.width * _compareSplit - 1.5,
                            top: 0,
                            bottom: 0,
                            child: IgnorePointer(
                              child: Container(
                                width: 3,
                                decoration: BoxDecoration(
                                  color: Colors.white,
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(alpha: 0.65),
                                      blurRadius: 8,
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                          Positioned(
                            left: imageRect.width * _compareSplit - 21,
                            top: imageRect.height / 2 - 21,
                            child: AnimatedScale(
                              duration: const Duration(milliseconds: 120),
                              scale: _compareDragging ? 1.1 : 1.0,
                              child: Container(
                                width: 42,
                                height: 42,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: colors.primary,
                                  border: Border.all(
                                    color: Colors.white,
                                    width: 2.5,
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: Colors.black.withValues(alpha: 0.48),
                                      blurRadius: 12,
                                      offset: const Offset(0, 3),
                                    ),
                                  ],
                                ),
                                child: Icon(
                                  Icons.compare_arrows_rounded,
                                  color: colors.onPrimary,
                                  size: 22,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),

                // Top-right Fullscreen expand icon (compact & unobtrusive)
                if (!widget.isFullscreen && widget.onOpenFullscreen != null)
                  Positioned(
                    top: 8,
                    right: 8,
                    child: Material(
                      color: Colors.black.withValues(alpha: 0.56),
                      shape: const CircleBorder(),
                      child: InkWell(
                        customBorder: const CircleBorder(),
                        onTap: widget.onOpenFullscreen,
                        child: const Padding(
                          padding: EdgeInsets.all(7),
                          child: Icon(
                            Icons.open_in_full_rounded,
                            color: Colors.white,
                            size: 17,
                          ),
                        ),
                      ),
                    ),
                  ),

                // Compact floating Lens action pill at bottom of stage (Original mode only)
                if (widget.mode == DocumentViewMode.original &&
                    widget.lensEnabled &&
                    (quadInfo.detected || quadInfo.isCustom || hasLines))
                  Positioned(
                    left: 8,
                    right: 8,
                    bottom: 8,
                    child: Center(
                      child: _buildLensBar(quadInfo, lines),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildLensBar(
    ({List<Point2D>? quad, bool detected, bool isCustom}) quadInfo,
    List<Map<String, dynamic>> lines,
  ) {
    final chosenLines = lines
        .where((l) => _selectedLineIds.contains((l['id'] as num?)?.toInt()))
        .toList();

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: const Color(0xe6161b20),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.white.withValues(alpha: 0.16)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.42),
            blurRadius: 14,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (chosenLines.isNotEmpty) ...[
              Text(
                '${chosenLines.length}/${lines.length} dòng',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 6),
              _PillAction(
                label: 'Sao chép',
                primary: true,
                onTap: () {
                  final text = chosenLines
                      .map((l) => l['text']?.toString() ?? '')
                      .join('\n');
                  widget.onCopyText(text);
                },
              ),
              const SizedBox(width: 4),
              _PillAction(
                label: 'Bỏ chọn',
                onTap: () => setState(() => _selectedLineIds.clear()),
              ),
            ] else if (lines.isNotEmpty) ...[
              Text(
                '✦ ${lines.length} dòng',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(width: 6),
              _PillAction(
                label: 'Chọn hết',
                onTap: () => setState(() {
                  _selectedLineIds
                    ..clear()
                    ..addAll(
                      lines
                          .map((l) => (l['id'] as num?)?.toInt())
                          .whereType<int>(),
                    );
                }),
              ),
            ] else ...[
              Text(
                quadInfo.isCustom ? '✦ Khung đã chỉnh' : '✦ Kéo 4 góc chỉnh khung',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
            if (quadInfo.quad != null && (lines.isEmpty || quadInfo.isCustom)) ...[
              const SizedBox(width: 6),
              _PillAction(
                label: _cropping
                    ? 'Đang cắt…'
                    : widget.canSend
                    ? 'Cắt & Gửi'
                    : 'Cắt khung',
                primary: chosenLines.isEmpty,
                onTap: _cropping ? null : () => _triggerCrop(quadInfo.quad!),
              ),
            ],
            if (quadInfo.isCustom) ...[
              const SizedBox(width: 4),
              _PillAction(
                label: 'Đặt lại',
                onTap: () {
                  setState(() => _selectedLineIds.clear());
                  widget.onQuadChanged(null);
                },
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PillAction extends StatelessWidget {
  const _PillAction({
    required this.label,
    required this.onTap,
    this.primary = false,
  });
  final String label;
  final VoidCallback? onTap;
  final bool primary;

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(999),
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: primary
            ? const Color(0xff8ab4f8)
            : Colors.white.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: primary ? const Color(0xff0b192c) : Colors.white,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    ),
  );
}

class _CompareBadge extends StatelessWidget {
  const _CompareBadge(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
    decoration: BoxDecoration(
      color: const Color(0xcc0f141c),
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: Colors.white.withValues(alpha: 0.22)),
    ),
    child: Text(
      text,
      style: const TextStyle(
        color: Colors.white,
        fontSize: 11,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}

class _LeftSplitClipper extends CustomClipper<Rect> {
  const _LeftSplitClipper(this.fraction);
  final double fraction;
  @override
  Rect getClip(Size size) =>
      Rect.fromLTRB(0, 0, size.width * fraction.clamp(0.0, 1.0), size.height);
  @override
  bool shouldReclip(covariant _LeftSplitClipper old) =>
      old.fraction != fraction;
}

class _LensOverlayPainter extends CustomPainter {
  const _LensOverlayPainter({
    required this.imageRect,
    required this.sourceSize,
    required this.paperQuad,
    required this.showScrim,
    required this.showDashedGuide,
    required this.lines,
    required this.selectedLineIds,
    required this.activeCorner,
    required this.activeEdge,
  });

  final Rect imageRect;
  final Size sourceSize;
  final List<Point2D>? paperQuad;
  final bool showScrim;
  final bool showDashedGuide;
  final List<Map<String, dynamic>> lines;
  final Set<int> selectedLineIds;
  final int? activeCorner;
  final int? activeEdge;

  Offset _map(Point2D p) => Offset(
    imageRect.left + (p[0] / sourceSize.width) * imageRect.width,
    imageRect.top + (p[1] / sourceSize.height) * imageRect.height,
  );

  @override
  void paint(Canvas canvas, Size size) {
    final quadPts = paperQuad?.map(_map).toList();

    // 1) Outside-paper scrim
    if (quadPts != null && quadPts.length == 4 && showScrim) {
      final path = Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(imageRect)
        ..addPolygon(quadPts, true);
      canvas.drawPath(
        path,
        Paint()..color = Colors.black.withValues(alpha: 0.45),
      );
    }

    // 2) Text line highlight pills
    for (final line in lines) {
      final rawPoly = line['polygon'];
      if (rawPoly is! List || rawPoly.length < 3) continue;
      final pts = rawPoly
          .whereType<List>()
          .where((p) => p.length >= 2)
          .map(
            (p) => _map([(p[0] as num).toDouble(), (p[1] as num).toDouble()]),
          )
          .toList();
      if (pts.length < 3) continue;
      final id = (line['id'] as num?)?.toInt();
      final isSel = id != null && selectedLineIds.contains(id);
      final polyPath = Path()..addPolygon(pts, true);
      canvas.drawPath(
        polyPath,
        Paint()
          ..color = isSel
              ? const Color(0x7a4299f5)
              : const Color(0x66ffffff)
          ..style = PaintingStyle.fill,
      );
      canvas.drawPath(
        polyPath,
        Paint()
          ..color = isSel
              ? const Color(0xf58aceff)
              : const Color(0xb0ffffff)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2,
      );
    }

    // 3) 4 white rounded Google Lens corner brackets + draggable corner dots & edge pills
    if (quadPts != null && quadPts.length == 4) {
      if (showDashedGuide) {
        canvas.drawPath(
          Path()..addPolygon(quadPts, true),
          Paint()
            ..color = Colors.white.withValues(alpha: 0.45)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.3,
        );
      }
      final minSide = math.max(
        40.0,
        math.min(imageRect.width, imageRect.height),
      );
      final armLen = (minSide * 0.11).clamp(16.0, 34.0);
      final rad = armLen * 0.42;

      Offset along(Offset a, Offset b, double dist) {
        final d = b - a;
        final len = math.max(1.0, d.distance);
        final t = math.min(0.42, dist / len);
        return Offset(a.dx + d.dx * t, a.dy + d.dy * t);
      }

      final bracketShadow = Paint()
        ..color = Colors.black.withValues(alpha: 0.55)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6.2
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round;
      final bracketPaint = Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.8
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round;

      for (var i = 0; i < 4; i++) {
        final prev = quadPts[(i + 3) % 4];
        final curr = quadPts[i];
        final next = quadPts[(i + 1) % 4];
        final pStart = along(curr, prev, armLen);
        final pIn = along(curr, prev, rad);
        final pOut = along(curr, next, rad);
        final pEnd = along(curr, next, armLen);
        final p = Path()
          ..moveTo(pStart.dx, pStart.dy)
          ..lineTo(pIn.dx, pIn.dy)
          ..quadraticBezierTo(curr.dx, curr.dy, pOut.dx, pOut.dy)
          ..lineTo(pEnd.dx, pEnd.dy);
        canvas.drawPath(p, bracketShadow);
        canvas.drawPath(p, bracketPaint);
      }

      // 4 edge midpoint drag pills
      for (var i = 0; i < 4; i++) {
        final a = quadPts[i];
        final b = quadPts[(i + 1) % 4];
        final mid = Offset((a.dx + b.dx) / 2, (a.dy + b.dy) / 2);
        final angle = math.atan2(b.dy - a.dy, b.dx - a.dx);
        final active = activeEdge == i;
        canvas.save();
        canvas.translate(mid.dx, mid.dy);
        canvas.rotate(angle);
        final rrect = RRect.fromRectAndRadius(
          const Rect.fromLTWH(-12, -3, 24, 6),
          const Radius.circular(3),
        );
        canvas.drawRRect(
          rrect,
          Paint()
            ..color = active
                ? const Color(0xff72cfff)
                : Colors.white.withValues(alpha: 0.85),
        );
        canvas.drawRRect(
          rrect,
          Paint()
            ..color = Colors.black.withValues(alpha: 0.55)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.0,
        );
        canvas.restore();
      }

      // 4 corner anchor dots
      for (var i = 0; i < 4; i++) {
        final c = quadPts[i];
        final active = activeCorner == i;
        canvas.drawCircle(
          c,
          active ? 7.5 : 5.5,
          Paint()
            ..color = active ? const Color(0xff72cfff) : Colors.white,
        );
        canvas.drawCircle(
          c,
          active ? 7.5 : 5.5,
          Paint()
            ..color = Colors.black.withValues(alpha: 0.65)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.4,
        );
      }
    }
  }

  @override
  bool shouldRepaint(covariant _LensOverlayPainter old) => true;
}

/// Crisp 90-degree flat Word-document renderer ("Ảnh văn bản") aligned 1:1 with the
/// perspective-rectified paper POV via exact projective homography H.
class DigitalDocumentPainter extends CustomPainter {
  const DigitalDocumentPainter({
    required this.text,
    required this.lens,
    required this.paperQuad,
    required this.sourceSize,
    required this.isDark,
    this.highlightedLineId,
  });

  final String text;
  final Map<String, dynamic>? lens;
  final List<Point2D>? paperQuad;
  final Size sourceSize;
  final bool isDark;
  final int? highlightedLineId;

  static List<({int id, String text, double x, double y, double w, double h, double fontSize})>
  _computeLayout({
    required Size size,
    required String text,
    required Map<String, dynamic>? lens,
    required List<Point2D>? paperQuad,
    required Size sourceSize,
  }) {
    final out =
        <({int id, String text, double x, double y, double w, double h, double fontSize})>[];
    if (size.width < 12 || size.height < 12) return out;

    final rawQuad = (paperQuad != null && paperQuad.length == 4)
        ? (orderQuad(paperQuad) ?? paperQuad)
        : <Point2D>[
            [0, 0],
            [sourceSize.width, 0],
            [sourceSize.width, sourceSize.height],
            [0, sourceSize.height],
          ];
    final dstRect = <Point2D>[
      [0, 0],
      [size.width, 0],
      [size.width, size.height],
      [0, size.height],
    ];
    final hMat = computeHomography(rawQuad, dstRect);

    final rawLines = lens?['lines'];
    final geoLines = rawLines is List
        ? rawLines
              .whereType<Map>()
              .map((m) => Map<String, dynamic>.from(m))
              .where(
                (m) => m['polygon'] is List && (m['polygon'] as List).length >= 3,
              )
              .toList()
        : <Map<String, dynamic>>[];
    final editedLines = text.split('\n');

    if (geoLines.isNotEmpty) {
      final metrics =
          <({int id, String lineText, QuadBounds bounds, double boxH})>[];
      for (var i = 0; i < geoLines.length; i++) {
        final line = geoLines[i];
        final lineText =
            (editedLines.length == geoLines.length
                ? editedLines[i]
                : line['text']?.toString()) ??
            '';
        if (lineText.trim().isEmpty) continue;
        final flatPoly = (line['polygon'] as List)
            .whereType<List>()
            .where((p) => p.length >= 2)
            .map(
              (p) => projectPoint(hMat, [
                (p[0] as num).toDouble(),
                (p[1] as num).toDouble(),
              ]),
            )
            .toList();
        if (flatPoly.length < 3) continue;
        final b = polygonBounds(flatPoly);
        metrics.add((
          id: (line['id'] as num?)?.toInt() ?? (i + 1),
          lineText: lineText,
          bounds: b,
          boxH: math.max(9.0, b.height),
        ));
      }
      final heights = metrics.map((m) => m.boxH).toList()..sort();
      final medH = heights.isNotEmpty ? heights[heights.length ~/ 2] : 14.0;
      final baseSize = (medH * 0.56).clamp(8.5, 22.0);
      final padX = math.max(6.0, size.width * 0.025);

      for (final m in metrics) {
        var fontSize = (m.boxH * 0.6).clamp(baseSize * 0.9, baseSize * 1.12);
        final startX = m.bounds.minX
            .clamp(padX, math.max(padX, size.width - padX - 24))
            .toDouble();
        final maxLineW = math.max(24.0, size.width - padX - startX);
        var tp = TextPainter(
          text: TextSpan(
            text: m.lineText,
            style: TextStyle(fontSize: fontSize, fontFamily: 'Roboto'),
          ),
          textDirection: TextDirection.ltr,
          maxLines: 1,
        )..layout();
        if (tp.width > maxLineW && tp.width > 1) {
          fontSize = math.max(7.2, fontSize * (maxLineW / tp.width));
          tp = TextPainter(
            text: TextSpan(
              text: m.lineText,
              style: TextStyle(fontSize: fontSize, fontFamily: 'Roboto'),
            ),
            textDirection: TextDirection.ltr,
            maxLines: 1,
          )..layout();
        }
        final drawY = m.bounds.cy
            .clamp(
              fontSize * 0.6,
              math.max(fontSize * 0.6, size.height - fontSize * 0.6),
            )
            .toDouble();
        final hitH = math.max(m.boxH * 0.85, fontSize * 1.45);
        out.add((
          id: m.id,
          text: m.lineText,
          x: startX,
          y: drawY,
          w: math.max(tp.width, m.bounds.width),
          h: hitH,
          fontSize: fontSize,
        ));
      }
      return out;
    }

    // 1-to-1 single-line Word layout (never wraps a single OCR line onto 2 lines!)
    final padX = math.max(12.0, size.width * 0.06);
    final padY = math.max(12.0, size.height * 0.06);
    final contentW = math.max(36.0, size.width - padX * 2);
    final availH = math.max(36.0, size.height - padY * 2);
    final raw = text.trim().isNotEmpty ? text.split('\n') : ['(Chưa có văn bản nhận dạng)'];
    final count = math.max(1, raw.length);

    var fontSize = ((availH / count) * 0.54).clamp(9.0, 20.0);
    for (var attempt = 0; attempt < 22; attempt++) {
      var maxW = 0.0;
      for (final s in raw) {
        final tp = TextPainter(
          text: TextSpan(
            text: s,
            style: TextStyle(fontSize: fontSize, fontFamily: 'Roboto'),
          ),
          textDirection: TextDirection.ltr,
          maxLines: 1,
        )..layout();
        if (tp.width > maxW) maxW = tp.width;
      }
      if (maxW <= contentW && count * fontSize * 1.6 <= availH) break;
      fontSize *= 0.93;
      if (fontSize <= 7.8) break;
    }
    final step = math.min(fontSize * 1.7, availH / count);
    for (var i = 0; i < raw.length; i++) {
      final s = raw[i];
      if (s.trim().isEmpty) continue;
      final y = padY + step * (i + 0.5);
      if (y > size.height - padY * 0.35) break;
      final tp = TextPainter(
        text: TextSpan(
          text: s,
          style: TextStyle(fontSize: fontSize, fontFamily: 'Roboto'),
        ),
        textDirection: TextDirection.ltr,
        maxLines: 1,
      )..layout(maxWidth: contentW);
      out.add((
        id: i + 1,
        text: s,
        x: padX,
        y: y,
        w: tp.width,
        h: math.max(fontSize * 1.35, step * 0.85),
        fontSize: fontSize,
      ));
    }
    return out;
  }

  static int? hitTestLineId({
    required Offset local,
    required Size size,
    required String text,
    required Map<String, dynamic>? lens,
    required List<Point2D>? paperQuad,
    required Size sourceSize,
  }) {
    final rows = _computeLayout(
      size: size,
      text: text,
      lens: lens,
      paperQuad: paperQuad,
      sourceSize: sourceSize,
    );
    for (final r in rows) {
      final rect = Rect.fromLTWH(r.x - 4, r.y - r.h / 2, r.w + 8, r.h);
      if (rect.contains(local)) return r.id;
    }
    return null;
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width < 12 || size.height < 12) return;
    // Pure flat 90-degree white Word sheet filling the rectified area 1:1
    final pageRect = Offset.zero & size;
    canvas.drawRect(pageRect, Paint()..color = const Color(0xfffcfcfa));
    canvas.drawRect(
      pageRect.deflate(0.5),
      Paint()
        ..color = isDark
            ? Colors.white.withValues(alpha: 0.24)
            : const Color(0xb894a3b8)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0,
    );

    final rows = _computeLayout(
      size: size,
      text: text,
      lens: lens,
      paperQuad: paperQuad,
      sourceSize: sourceSize,
    );
    final hasText = text.trim().isNotEmpty;
    for (final r in rows) {
      if (highlightedLineId == r.id) {
        final glow = RRect.fromRectAndRadius(
          Rect.fromLTWH(
            math.max(2, r.x - 4),
            math.max(2, r.y - r.h / 2),
            math.min(size.width - 4, r.w + 8),
            r.h,
          ),
          const Radius.circular(4),
        );
        canvas.drawRRect(glow, Paint()..color = const Color(0x3838bdf8));
        canvas.drawRRect(
          glow,
          Paint()
            ..color = const Color(0xf00ea5e9)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.5,
        );
      }
      final tp = TextPainter(
        text: TextSpan(
          text: r.text,
          style: TextStyle(
            color: hasText ? const Color(0xff141a22) : const Color(0xff94a3b8),
            fontSize: r.fontSize,
            fontFamily: 'Roboto',
            height: 1.15,
          ),
        ),
        textDirection: TextDirection.ltr,
        maxLines: 1,
      )..layout(maxWidth: math.max(16, size.width - r.x - 6));
      tp.paint(canvas, Offset(r.x, r.y - tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant DigitalDocumentPainter old) =>
      old.text != text ||
      old.lens != lens ||
      old.paperQuad != paperQuad ||
      old.isDark != isDark ||
      old.highlightedLineId != highlightedLineId;
}

/// Fullscreen interactive viewer for phone screens so users have maximum space
/// to drag Lens corners or compare Ảnh văn bản vs Ảnh gốc with one thumb.
class FullscreenDocumentStagePage extends StatefulWidget {
  const FullscreenDocumentStagePage({
    super.key,
    required this.item,
    required this.initialMode,
    required this.lensEnabled,
    required this.canSend,
    required this.onQuadChanged,
    required this.onCropAndSend,
  });

  final Document item;
  final DocumentViewMode initialMode;
  final bool lensEnabled;
  final bool canSend;
  final ValueChanged<List<Point2D>?> onQuadChanged;
  final Future<void> Function(List<Point2D> quad, {required bool autoSend})
  onCropAndSend;

  @override
  State<FullscreenDocumentStagePage> createState() =>
      _FullscreenDocumentStagePageState();
}

class _FullscreenDocumentStagePageState
    extends State<FullscreenDocumentStagePage> {
  late DocumentViewMode mode = widget.initialMode;
  late bool lensEnabled = widget.lensEnabled;

  @override
  Widget build(BuildContext context) {
    final hasText = widget.item.text.trim().isNotEmpty;
    if (!hasText && mode != DocumentViewMode.original) {
      mode = DocumentViewMode.original;
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.item.name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          if (mode == DocumentViewMode.original)
            IconButton(
              tooltip: lensEnabled ? 'Tắt khung Lens' : 'Bật khung Lens',
              icon: Icon(
                lensEnabled ? Icons.auto_awesome : Icons.auto_awesome_outlined,
              ),
              onPressed: () => setState(() => lensEnabled = !lensEnabled),
            ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 8),
              child: ViewModeSegmentedBar(
                mode: mode,
                canDigital: hasText,
                onChanged: (next) => setState(() => mode = next),
              ),
            ),
            Expanded(
              child: LensStage(
                item: widget.item,
                mode: mode,
                lensEnabled: lensEnabled,
                canSend: widget.canSend,
                isFullscreen: true,
                onQuadChanged: (q) {
                  widget.onQuadChanged(q);
                  setState(() {});
                },
                onCropAndSend: (q, {required bool autoSend}) async {
                  await widget.onCropAndSend(q, autoSend: autoSend);
                  if (context.mounted) Navigator.pop(context);
                },
                onCopyText: (t) async {
                  await Clipboard.setData(ClipboardData(text: t));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Đã sao chép văn bản đã chọn')),
                    );
                  }
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Compact 3-way mobile view switcher ("Ảnh gốc" | "Ảnh văn bản" | "Đối chiếu")
/// guaranteed to fit cleanly in 1 horizontal row even on 360dp phones.
class ViewModeSegmentedBar extends StatelessWidget {
  const ViewModeSegmentedBar({
    super.key,
    required this.mode,
    required this.canDigital,
    required this.onChanged,
  });

  final DocumentViewMode mode;
  final bool canDigital;
  final ValueChanged<DocumentViewMode> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(11),
      ),
      child: Row(
        children: [
          for (final (value, label, enabled) in [
            (DocumentViewMode.original, 'Ảnh gốc', true),
            (DocumentViewMode.digital, 'Ảnh văn bản', canDigital),
            (DocumentViewMode.compare, 'Đối chiếu', canDigital),
          ])
            Expanded(
              child: GestureDetector(
                onTap: enabled ? () => onChanged(value) : null,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 140),
                  padding: const EdgeInsets.symmetric(
                    vertical: 7,
                    horizontal: 6,
                  ),
                  decoration: BoxDecoration(
                    color: mode == value ? colors.primary : Colors.transparent,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    label,
                    textAlign: TextAlign.center,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight:
                          mode == value ? FontWeight.w700 : FontWeight.w500,
                      color: mode == value
                          ? colors.onPrimary
                          : enabled
                          ? colors.onSurface
                          : colors.onSurface.withValues(alpha: 0.36),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
