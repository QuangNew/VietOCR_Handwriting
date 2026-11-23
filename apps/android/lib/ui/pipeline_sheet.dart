import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../domain/app_controller.dart';
import '../domain/document.dart';

/// Mobile-first 5-stage visual Pipeline Demo page (vertical layout for phone screens).
class PipelineDemoPage extends StatefulWidget {
  const PipelineDemoPage({super.key, required this.app, required this.item});
  final AppController app;
  final Document item;

  @override
  State<PipelineDemoPage> createState() => _PipelineDemoPageState();
}

class _PipelineDemoPageState extends State<PipelineDemoPage> {
  Map<String, dynamic>? _pipe;
  String? _error;
  bool _loading = true;
  bool _overviewMode = false; // Step-by-step default fits phone screens best
  int _activeStep = 0;
  int? _tappedLineId;
  Timer? _autoTimer;

  static const _lineColors = [
    Color(0xff72cfff),
    Color(0xffb4e688),
    Color(0xfff7c873),
    Color(0xfff49393),
    Color(0xffc8a2ff),
    Color(0xff5eead4),
  ];

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _autoTimer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.app.fetchPipeline(widget.item);
      if (!mounted) return;
      setState(() {
        _pipe = data;
        _loading = false;
        if (data == null) {
          _error =
              'Chưa có dữ liệu chi tiết 5 khâu cho ảnh này. Hãy gửi lại ảnh với bản Compute Server mới.';
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = AppController.readableError(e);
      });
    }
  }

  void _toggleAutoPlay() {
    if (_autoTimer != null) {
      _autoTimer?.cancel();
      setState(() => _autoTimer = null);
      return;
    }
    if (_pipe == null) return;
    setState(() {
      _overviewMode = false;
      _activeStep = 0;
    });
    _autoTimer = Timer.periodic(const Duration(milliseconds: 3200), (_) {
      if (!mounted) return;
      setState(() => _activeStep = (_activeStep + 1) % 5);
    });
  }

  String _fmtMs(dynamic raw) {
    final v = (raw as num?)?.toDouble() ?? 0;
    if (v <= 0) return '0 ms';
    return v >= 1000
        ? '${(v / 1000).toStringAsFixed(2)} s'
        : '${v.round()} ms';
  }

  Uint8List? _decodeDataUrl(dynamic raw) {
    if (raw is! String || raw.isEmpty) return null;
    final idx = raw.indexOf(',');
    if (idx < 0) return null;
    try {
      return base64Decode(raw.substring(idx + 1));
    } catch (_) {
      return null;
    }
  }

  List<({String type, String text})> _diffWords(String raw, String fixed) {
    final a = raw.trim().isEmpty ? <String>[] : raw.trim().split(RegExp(r'\s+'));
    final b =
        fixed.trim().isEmpty ? <String>[] : fixed.trim().split(RegExp(r'\s+'));
    final m = a.length, n = b.length;
    final dp = List.generate(m + 1, (_) => List<int>.filled(n + 1, 0));
    for (var i = m - 1; i >= 0; i--) {
      for (var j = n - 1; j >= 0; j--) {
        dp[i][j] = a[i] == b[j]
            ? dp[i + 1][j + 1] + 1
            : math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    final out = <({String type, String text})>[];
    var i = 0, j = 0;
    while (i < m && j < n) {
      if (a[i] == b[j]) {
        out.add((type: 'eq', text: a[i]));
        i++;
        j++;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        out.add((type: 'del', text: a[i]));
        i++;
      } else {
        out.add((type: 'ins', text: b[j]));
        j++;
      }
    }
    while (i < m) {
      out.add((type: 'del', text: a[i++]));
    }
    while (j < n) {
      out.add((type: 'ins', text: b[j++]));
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pipeline 5 khâu'),
        actions: [
          if (_pipe != null) ...[
            IconButton(
              tooltip: _overviewMode ? 'Xem từng bước' : 'Xem tổng quan',
              icon: Icon(
                _overviewMode ? Icons.view_carousel_outlined : Icons.view_agenda_outlined,
              ),
              onPressed: () {
                _autoTimer?.cancel();
                setState(() {
                  _autoTimer = null;
                  _overviewMode = !_overviewMode;
                });
              },
            ),
            IconButton(
              tooltip: _autoTimer != null ? 'Dừng tự chạy' : 'Tự chạy demo',
              icon: Icon(
                _autoTimer != null ? Icons.stop_circle_outlined : Icons.play_circle_outline,
              ),
              onPressed: _toggleAutoPlay,
            ),
          ],
        ],
      ),
      body: SafeArea(
        top: false,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _pipe == null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.auto_graph_outlined,
                        size: 42,
                        color: colors.outline,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _error ?? 'Chưa có dữ liệu Pipeline.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 12),
                      OutlinedButton(
                        onPressed: _load,
                        child: const Text('Tải lại'),
                      ),
                    ],
                  ),
                ),
              )
            : _buildContent(context, _pipe!),
      ),
      bottomNavigationBar: _pipe != null && !_overviewMode
          ? Material(
              color: colors.surfaceContainer,
              child: SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 8,
                  ),
                  child: Row(
                    children: [
                      OutlinedButton.icon(
                        onPressed: _activeStep > 0
                            ? () {
                                _autoTimer?.cancel();
                                setState(() {
                                  _autoTimer = null;
                                  _activeStep--;
                                });
                              }
                            : null,
                        icon: const Icon(Icons.chevron_left),
                        label: const Text('Trước'),
                      ),
                      Expanded(
                        child: Text(
                          'Khâu ${_activeStep + 1} / 5',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                      ),
                      FilledButton.icon(
                        onPressed: _activeStep < 4
                            ? () {
                                _autoTimer?.cancel();
                                setState(() {
                                  _autoTimer = null;
                                  _activeStep++;
                                });
                              }
                            : null,
                        icon: const Icon(Icons.chevron_right),
                        label: const Text('Tiếp'),
                      ),
                    ],
                  ),
                ),
              ),
            )
          : null,
    );
  }

  Widget _buildContent(BuildContext context, Map<String, dynamic> pipe) {
    final t = pipe['timings'] is Map
        ? Map<String, dynamic>.from(pipe['timings'] as Map)
        : <String, dynamic>{};
    final lines = pipe['lines'] is List
        ? (pipe['lines'] as List)
              .whereType<Map>()
              .map((m) => Map<String, dynamic>.from(m))
              .toList()
        : <Map<String, dynamic>>[];

    final steps = [
      ('① Giấy', pipe['paperDetected'] == true ? 'Scanner' : 'Legacy'),
      ('② Mực', _fmtMs(t['preprocessMs'])),
      ('③ Dòng', '${lines.length} dòng'),
      ('④ ML_s44', _fmtMs(t['recognitionMs'])),
      ('⑤ BARTpho', pipe['corrected'] == true ? _fmtMs(t['correctionMs']) : 'Tắt'),
    ];

    final pre = (t['preprocessMs'] as num?)?.toDouble() ?? 0;
    final seg = (t['segmentMs'] as num?)?.toDouble() ?? 0;
    final rec = (t['recognitionMs'] as num?)?.toDouble() ?? 0;
    final cor = (t['correctionMs'] as num?)?.toDouble() ?? 0;
    final total = math.max(1.0, pre + seg + rec + cor);

    return ListView(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 24),
      children: [
        // Horizontal scrollable step chips (mobile-friendly!)
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (var i = 0; i < steps.length; i++)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    selected: !_overviewMode && _activeStep == i,
                    label: Text('${steps[i].$1} · ${steps[i].$2}'),
                    onSelected: (_) {
                      _autoTimer?.cancel();
                      setState(() {
                        _autoTimer = null;
                        _overviewMode = false;
                        _activeStep = i;
                      });
                    },
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        // Stacked timing bar
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: SizedBox(
            height: 8,
            child: Row(
              children: [
                if (pre > 0)
                  Expanded(
                    flex: math.max(1, (pre / total * 100).round()),
                    child: const ColoredBox(color: Color(0xff72cfff)),
                  ),
                if (seg > 0)
                  Expanded(
                    flex: math.max(1, (seg / total * 100).round()),
                    child: const ColoredBox(color: Color(0xfff7c873)),
                  ),
                if (rec > 0)
                  Expanded(
                    flex: math.max(1, (rec / total * 100).round()),
                    child: const ColoredBox(color: Color(0xffa6e38a)),
                  ),
                if (cor > 0)
                  Expanded(
                    flex: math.max(1, (cor / total * 100).round()),
                    child: const ColoredBox(color: Color(0xffc8a2ff)),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Tổng ${_fmtMs(t['totalMs'])} · ${pipe['device'] ?? 'auto'} · ${pipe['sourceWidth']}×${pipe['sourceHeight']} px',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        if (_overviewMode)
          for (var i = 0; i < 5; i++) ...[
            _buildStageCard(context, i, pipe, lines, t),
            const SizedBox(height: 12),
          ]
        else
          _buildStageCard(context, _activeStep, pipe, lines, t),
      ],
    );
  }

  Widget _buildStageCard(
    BuildContext context,
    int idx,
    Map<String, dynamic> pipe,
    List<Map<String, dynamic>> lines,
    Map<String, dynamic> t,
  ) {
    final colors = Theme.of(context).colorScheme;
    final previews = pipe['previews'] is Map
        ? Map<String, dynamic>.from(pipe['previews'] as Map)
        : <String, dynamic>{};

    Widget imgBox(String label, Uint8List? bytes, {Widget? fallback}) => Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: ColoredBox(
            color: Colors.black87,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 260),
              child: bytes != null
                  ? Image.memory(bytes, fit: BoxFit.contain)
                  : fallback ??
                        const SizedBox(
                          height: 120,
                          child: Center(
                            child: Text(
                              'Không có ảnh xem trước',
                              style: TextStyle(color: Colors.white54),
                            ),
                          ),
                        ),
            ),
          ),
        ),
      ],
    );

    return Card(
      color: colors.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (idx == 0) ...[
              Text(
                'KHÂU 1 · Định vị vùng giấy (Paper Detection)',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  Chip(
                    label: Text(
                      pipe['paperDetected'] == true
                          ? 'Scanner · Tự phát hiện giấy'
                          : 'Legacy · Toàn khung',
                    ),
                  ),
                  Chip(label: Text('Tiền xử lý: ${_fmtMs(t['preprocessMs'])}')),
                ],
              ),
              const SizedBox(height: 10),
              imgBox(
                'Ảnh gốc',
                null,
                fallback: Image.file(
                  File(widget.item.path),
                  fit: BoxFit.contain,
                  cacheWidth: 960,
                ),
              ),
              const SizedBox(height: 10),
              imgBox(
                'Bản đồ phân vùng giấy & lọc nền',
                _decodeDataUrl(previews['paperOverlay']),
              ),
            ] else if (idx == 1) ...[
              Text(
                'KHÂU 2 · Khử bóng & Tách nét mực (Sauvola/Otsu)',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 10),
              imgBox('Ảnh lọc nền giữ mực (Ink Only)', _decodeDataUrl(previews['inkOnly'])),
              const SizedBox(height: 10),
              imgBox('Mặt nạ mực nhị phân (Ink Mask)', _decodeDataUrl(previews['inkMask'])),
            ] else if (idx == 2) ...[
              Text(
                'KHÂU 3 · Tách dòng Native (${lines.length} dòng · ${_fmtMs(t['segmentMs'])})',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 6),
              Text(
                'Chạm một dòng bên dưới để xem vị trí và kết quả nhận dạng.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 10),
              SizedBox(
                height: 260,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: ColoredBox(
                    color: Colors.black87,
                    child: LayoutBuilder(
                      builder: (_, constraints) {
                        final sw = (pipe['sourceWidth'] as num?)?.toDouble() ?? 1000;
                        final sh = (pipe['sourceHeight'] as num?)?.toDouble() ?? 1000;
                        final fitted = applyBoxFit(
                          BoxFit.contain,
                          Size(sw, sh),
                          constraints.biggest,
                        ).destination;
                        final rect = Alignment.center.inscribe(
                          fitted,
                          Offset.zero & constraints.biggest,
                        );
                        return Stack(
                          fit: StackFit.expand,
                          children: [
                            Positioned.fromRect(
                              rect: rect,
                              child: Image.file(
                                File(widget.item.path),
                                fit: BoxFit.fill,
                                cacheWidth: 960,
                              ),
                            ),
                            Positioned.fill(
                              child: CustomPaint(
                                painter: _SegLinesPainter(
                                  rect: rect,
                                  sourceSize: Size(sw, sh),
                                  lines: lines,
                                  highlightedId: _tappedLineId,
                                  palette: _lineColors,
                                ),
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final l in lines.take(24))
                    ChoiceChip(
                      label: Text('#${l['id']}'),
                      selected: _tappedLineId == (l['id'] as num?)?.toInt(),
                      onSelected: (_) => setState(
                        () => _tappedLineId = (l['id'] as num?)?.toInt(),
                      ),
                    ),
                ],
              ),
              if (lines.isNotEmpty) ...[
                const SizedBox(height: 8),
                Builder(
                  builder: (_) {
                    final chosen = lines.firstWhere(
                      (l) => (l['id'] as num?)?.toInt() == _tappedLineId,
                      orElse: () => lines.first,
                    );
                    return Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: colors.surfaceContainer,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        'Dòng #${chosen['id']} (${_fmtMs(chosen['ms'])}): ${chosen['text'] ?? ''}',
                      ),
                    );
                  },
                ),
              ],
            ] else if (idx == 3) ...[
              Text(
                'KHÂU 4 · Chuẩn hóa V2c (64px) & ${pipe['model'] ?? 'ML_s44'}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              for (final l in lines)
                Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainer,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            '#${l['id']}',
                            style: TextStyle(
                              fontWeight: FontWeight.w700,
                              color: colors.primary,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            _fmtMs(l['ms']),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                      if (_decodeDataUrl(l['v2cThumb']) case final strip?) ...[
                        const SizedBox(height: 6),
                        Container(
                          height: 36,
                          width: double.infinity,
                          padding: const EdgeInsets.all(2),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(5),
                          ),
                          child: Image.memory(
                            strip,
                            fit: BoxFit.contain,
                            alignment: Alignment.centerLeft,
                          ),
                        ),
                      ],
                      const SizedBox(height: 6),
                      Text(
                        l['rawText']?.toString() ?? l['text']?.toString() ?? '',
                      ),
                    ],
                  ),
                ),
            ] else ...[
              Text(
                'KHÂU 5 · Bartpho_v2_fp16 + Edit Guard v3',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 6),
              Text(
                pipe['corrected'] == true
                    ? 'Đã nội suy (${_fmtMs(t['correctionMs'])}) · Sửa ${lines.where((l) => l['changed'] == true).length}/${lines.length} dòng'
                    : 'Đang tắt BARTpho (0 MiB VRAM thêm). Bật "Nội suy BARTpho" và gửi lại để xem so sánh từng từ.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 10),
              for (final l in lines)
                Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainer,
                    borderRadius: BorderRadius.circular(10),
                    border: l['changed'] == true
                        ? Border.all(
                            color: colors.primary.withValues(alpha: 0.6),
                          )
                        : null,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Dòng #${l['id']}${l['changed'] == true ? ' · Đã sửa' : ''}',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                          color: l['changed'] == true
                              ? colors.primary
                              : colors.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 4),
                      if (l['changed'] == true)
                        Text.rich(
                          TextSpan(
                            children: [
                              for (final seg in _diffWords(
                                l['rawText']?.toString() ?? '',
                                l['text']?.toString() ?? '',
                              ))
                                TextSpan(
                                  text: '${seg.text} ',
                                  style: seg.type == 'del'
                                      ? TextStyle(
                                          color: colors.error,
                                          decoration: TextDecoration.lineThrough,
                                        )
                                      : seg.type == 'ins'
                                      ? TextStyle(
                                          color: colors.primary,
                                          fontWeight: FontWeight.w700,
                                        )
                                      : null,
                                ),
                            ],
                          ),
                        )
                      else
                        Text(l['text']?.toString() ?? ''),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SegLinesPainter extends CustomPainter {
  const _SegLinesPainter({
    required this.rect,
    required this.sourceSize,
    required this.lines,
    required this.highlightedId,
    required this.palette,
  });
  final Rect rect;
  final Size sourceSize;
  final List<Map<String, dynamic>> lines;
  final int? highlightedId;
  final List<Color> palette;

  @override
  void paint(Canvas canvas, Size size) {
    for (var i = 0; i < lines.length; i++) {
      final l = lines[i];
      final raw = l['polygon'];
      if (raw is! List || raw.length < 3) continue;
      final pts = raw
          .whereType<List>()
          .where((p) => p.length >= 2)
          .map(
            (p) => Offset(
              rect.left + ((p[0] as num).toDouble() / sourceSize.width) * rect.width,
              rect.top + ((p[1] as num).toDouble() / sourceSize.height) * rect.height,
            ),
          )
          .toList();
      if (pts.length < 3) continue;
      final id = (l['id'] as num?)?.toInt();
      final color = palette[i % palette.length];
      final isHi = highlightedId == id;
      final path = Path()..addPolygon(pts, true);
      canvas.drawPath(
        path,
        Paint()..color = color.withValues(alpha: isHi ? 0.42 : 0.18),
      );
      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = isHi ? 2.4 : 1.4,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _SegLinesPainter old) =>
      old.highlightedId != highlightedId || old.lines != lines;
}
