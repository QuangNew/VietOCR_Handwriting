import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../domain/document.dart';

class AssistantFace extends StatefulWidget {
  const AssistantFace({super.key, required this.state, this.size = 100});
  final AssistantState state;
  final double size;
  @override
  State<AssistantFace> createState() => _AssistantFaceState();
}

class _AssistantFaceState extends State<AssistantFace>
    with SingleTickerProviderStateMixin {
  late final AnimationController animation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 4),
  )..repeat();
  @override
  void dispose() {
    animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Gương mặt trợ lý ${widget.state.name}',
    child: SizedBox.square(
      dimension: widget.size,
      child: AnimatedBuilder(
        animation: animation,
        builder: (_, _) => CustomPaint(
          painter: _FacePainter(
            widget.state,
            animation.value,
            Theme.of(context).colorScheme.primary,
            Theme.of(context).colorScheme.surfaceContainerHighest,
          ),
        ),
      ),
    ),
  );
}

class _FacePainter extends CustomPainter {
  _FacePainter(this.state, this.phase, this.color, this.background);
  final AssistantState state;
  final double phase;
  final Color color, background;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 100, size.height / 100);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(0, 0, 100, 100),
        const Radius.circular(28),
      ),
      Paint()..color = background,
    );
    final paint = Paint()
      ..color = color
      ..strokeWidth = 6
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;
    final blink = phase > .94 || state == AssistantState.sleeping;
    for (final x in [32.0, 68.0]) {
      if (state == AssistantState.done) {
        canvas.drawArc(
          Rect.fromCenter(center: Offset(x, 44), width: 18, height: 16),
          math.pi,
          math.pi,
          false,
          paint,
        );
      } else if (blink) {
        canvas.drawLine(Offset(x - 7, 44), Offset(x + 7, 44), paint);
      } else {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(
              center: Offset(x, 43 + math.sin(phase * math.pi * 2) * 1.5),
              width: 12,
              height: state == AssistantState.processing ? 15 : 22,
            ),
            const Radius.circular(6),
          ),
          Paint()..color = color,
        );
      }
    }
    if (state == AssistantState.error) {
      canvas.drawArc(
        const Rect.fromLTWH(38, 66, 24, 16),
        math.pi,
        math.pi,
        false,
        paint,
      );
    } else if (state == AssistantState.processing) {
      for (var i = 0; i < 3; i++) {
        canvas.drawCircle(
          Offset(40.0 + 10 * i, 70),
          2 + (math.sin(phase * math.pi * 8 - i) + 1),
          Paint()..color = color,
        );
      }
    } else {
      canvas.drawArc(
        const Rect.fromLTWH(35, 52, 30, 24),
        0,
        math.pi,
        false,
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _FacePainter oldDelegate) =>
      state != oldDelegate.state ||
      phase != oldDelegate.phase ||
      color != oldDelegate.color ||
      background != oldDelegate.background;
}
