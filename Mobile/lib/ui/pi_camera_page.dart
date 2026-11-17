import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;
import '../ocr/image_processing.dart';
import '../domain/app_controller.dart';
import '../services/gateway_client.dart';
import '../services/scoped_token.dart';

Uint8List mirrorCameraPhoto(Uint8List bytes) => Uint8List.fromList(
  img.encodePng(img.flipHorizontal(decodePhoto(bytes)), level: 3),
);

class PiCameraPage extends StatefulWidget {
  const PiCameraPage({super.key, required this.app});
  final AppController app;
  @override
  State<PiCameraPage> createState() => _PiCameraPageState();
}

class _PiCameraPageState extends State<PiCameraPage>
    with WidgetsBindingObserver {
  late VietOcrRemote client;
  List<Map<String, dynamic>> cameras = [];
  String? selected, error;
  Uint8List? frame, review;
  StreamSubscription<Uint8List>? stream;
  Timer? reviewTimer;
  bool capturing = false, mirror = false;
  int seconds = 0;
  DateTime last = DateTime.fromMillisecondsSinceEpoch(0);
  late final String? owner;
  int generation = 0;
  bool get sameAccount => owner == widget.app.cloud.userId;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    owner = widget.app.cloud.userId;
    widget.app.cloud.addListener(accountChanged);
    client = makeClient();
    unawaited(load());
  }

  void accountChanged() {
    if (sameAccount || !mounted) return;
    generation++;
    client.close();
    unawaited(stream?.cancel());
    reviewTimer?.cancel();
    setState(() {
      frame = null;
      review = null;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !sameAccount) {
        Navigator.of(context).popUntil((route) => route.isFirst);
      }
    });
  }

  VietOcrRemote makeClient() => VietOcrRemote(
    widget.app.serverUrl,
    '',
    allowInsecureLan: widget.app.serverInsecureLan,
    tokenProvider: scopedToken(
      owner: owner,
      currentOwner: () => widget.app.cloud.userId,
      fetch: widget.app.cloud.accessToken,
    ),
  );
  Future<void> load() async {
    try {
      final items = await client.cameras();
      if (!mounted || !sameAccount) return;
      setState(() => cameras = items);
      if (items.isNotEmpty) await open(items.first['id'] as String);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> open(String id) async {
    if (!sameAccount) return;
    final current = ++generation;
    client.close();
    await stream?.cancel();
    if (!mounted || !sameAccount || current != generation) return;
    client = makeClient();
    setState(() {
      selected = id;
      error = null;
      frame = null;
    });
    stream = client
        .frames(id)
        .listen(
          (bytes) {
            if (!mounted ||
                !sameAccount ||
                current != generation ||
                review != null ||
                DateTime.now().difference(last).inMilliseconds < 60) {
              return;
            }
            last = DateTime.now();
            setState(() => frame = bytes);
          },
          onError: (Object e) {
            if (mounted && sameAccount && current == generation) {
              setState(() => error = e.toString());
            }
          },
        );
  }

  Future<void> capture() async {
    if (!sameAccount || selected == null || capturing) return;
    setState(() => capturing = true);
    final account = widget.app.cloud.userId, mirrored = mirror;
    try {
      final bytes = await client.snapshot(selected!);
      if (!mounted || account != widget.app.cloud.userId) return;
      final stamp = DateTime.now().millisecondsSinceEpoch;
      final name = 'Raspberry_$stamp.jpg';
      await widget.app.importImages([(bytes, name)], preserveResolution: true);
      if (!mounted || account != widget.app.cloud.userId) return;
      final original = widget.app.documents
          .where((d) => d.name == name)
          .firstOrNull;
      if (original == null) throw StateError(widget.app.message);
      var captured = bytes;
      if (mirrored) {
        captured = await compute(mirrorCameraPhoto, bytes);
        if (!mounted || account != widget.app.cloud.userId) return;
        final mirrorName = 'Mirror_$stamp.png';
        await widget.app.importImages([
          (captured, mirrorName),
        ], preserveResolution: true);
        if (!widget.app.documents.any((d) => d.name == mirrorName)) {
          throw StateError(widget.app.message);
        }
        widget.app.setIncluded(original.id, false);
      }
      setState(() {
        review = captured;
        seconds = 3;
        error = null;
      });
      reviewTimer?.cancel();
      reviewTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (!mounted) {
          timer.cancel();
          return;
        }
        if (seconds <= 1) {
          skip();
        } else {
          setState(() => seconds--);
        }
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => capturing = false);
    }
  }

  void skip() {
    reviewTimer?.cancel();
    if (mounted) {
      setState(() {
        review = null;
        seconds = 0;
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      generation++;
      client.close();
      unawaited(stream?.cancel());
    } else if (sameAccount && selected != null) {
      unawaited(open(selected!));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.app.cloud.removeListener(accountChanged);
    generation++;
    reviewTimer?.cancel();
    client.close();
    unawaited(stream?.cancel());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Camera Raspberry')),
    body: SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: DropdownButtonFormField<String>(
              initialValue: selected,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Webcam dùng chung'),
              items: cameras
                  .map(
                    (c) => DropdownMenuItem(
                      value: c['id'] as String,
                      child: Text(c['name'] as String),
                    ),
                  )
                  .toList(),
              onChanged: (id) {
                if (id != null) unawaited(open(id));
              },
            ),
          ),
          SwitchListTile.adaptive(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16),
            title: const Text('Lật gương trái–phải'),
            subtitle: const Text(
              'Áp dụng cho preview và ảnh chụp; giữ bản gốc.',
            ),
            value: mirror,
            onChanged: capturing || review != null
                ? null
                : (value) => setState(() => mirror = value),
          ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          Expanded(
            child: ColoredBox(
              color: Colors.black,
              child: Center(
                child: (review ?? frame) == null
                    ? const CircularProgressIndicator()
                    : InteractiveViewer(
                        maxScale: 5,
                        child: Transform.flip(
                          flipX: review == null && mirror,
                          child: Image.memory(
                            review ?? frame!,
                            gaplessPlayback: true,
                            cacheWidth: review == null ? 1280 : null,
                            fit: BoxFit.contain,
                          ),
                        ),
                      ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                Text(
                  review != null
                      ? 'Đã lưu bản nháp · xem lại ${seconds}s'
                      : 'Ảnh chưa gửi OCR. Camera được chia sẻ giữa các tài khoản.',
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 12,
                  children: [
                    if (review != null)
                      FilledButton(
                        onPressed: skip,
                        child: const Text('Bỏ qua · Chụp tiếp'),
                      )
                    else
                      FilledButton.icon(
                        onPressed: capturing || selected == null
                            ? null
                            : capture,
                        icon: const Icon(Icons.camera_alt),
                        label: Text(capturing ? 'Đang chụp…' : 'Chụp ảnh'),
                      ),
                    OutlinedButton(
                      onPressed: selected == null
                          ? load
                          : () => open(selected!),
                      child: const Text('Kết nối lại'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
