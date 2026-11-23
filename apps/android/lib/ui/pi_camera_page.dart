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
  bool capturing = false, mirror = false, loading = false, foreground = true;
  bool lastAutoSent = false;
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
    if (!sameAccount || loading || !foreground) return;
    final current = ++generation;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      client.close();
      await stream?.cancel();
      if (!mounted || current != generation) return;
      client = makeClient();
      final items = (await client.cameras())
          .where((camera) => camera['id'] is String && camera['name'] is String)
          .toList();
      if (!mounted || !sameAccount || current != generation) return;
      setState(() {
        cameras = items;
        loading = false;
      });
      if (items.isNotEmpty) {
        await open(items.first['id'] as String);
      } else {
        setState(() => error = 'Raspberry chưa có webcam được cấu hình.');
      }
    } catch (e) {
      if (mounted && current == generation) {
        setState(() => error = AppController.readableError(e));
      }
    } finally {
      if (mounted && current == generation) setState(() => loading = false);
    }
  }

  Future<void> open(String id) async {
    if (!sameAccount || !foreground || capturing) return;
    final current = ++generation;
    client.close();
    await stream?.cancel();
    if (!mounted || !sameAccount || current != generation) return;
    client = makeClient();
    setState(() {
      selected = id;
      loading = false;
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
            setState(() {
              frame = bytes;
              error = null;
            });
          },
          onError: (Object e) {
            if (mounted && sameAccount && current == generation) {
              setState(() => error = AppController.readableError(e));
            }
          },
        );
  }

  Future<void> capture() async {
    if (!sameAccount ||
        selected == null ||
        frame == null ||
        capturing ||
        !foreground ||
        error != null) {
      return;
    }
    setState(() => capturing = true);
    final account = widget.app.cloud.userId,
        mirrored = mirror,
        current = generation;
    try {
      final bytes = await client.snapshot(selected!);
      if (!mounted ||
          account != widget.app.cloud.userId ||
          current != generation) {
        return;
      }
      final stamp = DateTime.now().millisecondsSinceEpoch;
      final name = 'Raspberry_$stamp.jpg';
      await widget.app.importImages([(bytes, name)]);
      if (!mounted ||
          account != widget.app.cloud.userId ||
          current != generation) {
        return;
      }
      final original = widget.app.documents
          .where((d) => d.name == name)
          .firstOrNull;
      if (original == null) throw StateError(widget.app.message);
      var captured = bytes;
      var targetDocId = original.id;
      if (mirrored) {
        captured = await compute(mirrorCameraPhoto, bytes);
        if (!mounted ||
            account != widget.app.cloud.userId ||
            current != generation) {
          return;
        }
        final mirrorName = 'Mirror_$stamp.png';
        await widget.app.importImages([(captured, mirrorName)]);
        final mirroredDoc = widget.app.documents
            .where((d) => d.name == mirrorName)
            .firstOrNull;
        if (mirroredDoc == null) {
          throw StateError(widget.app.message);
        }
        widget.app.setIncluded(original.id, false);
        targetDocId = mirroredDoc.id;
      }
      final shouldAutoSend = widget.app.cameraAutoSend && widget.app.canSend;
      if (shouldAutoSend) {
        widget.app.enqueueAutoSend(targetDocId);
      }
      setState(() {
        review = captured;
        lastAutoSent = shouldAutoSend;
        error = null;
      });
      reviewTimer?.cancel();
      reviewTimer = Timer(const Duration(milliseconds: 500), skip);
    } catch (e) {
      if (mounted && current == generation) {
        setState(() => error = AppController.readableError(e));
      }
    } finally {
      if (mounted) setState(() => capturing = false);
    }
  }

  void skip() {
    reviewTimer?.cancel();
    if (mounted) {
      setState(() {
        review = null;
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive) return;
    final resumed = state == AppLifecycleState.resumed;
    if (resumed == foreground) return;
    foreground = resumed;
    if (!resumed) {
      generation++;
      client.close();
      unawaited(stream?.cancel());
      if (mounted) {
        setState(() {
          loading = false;
          capturing = false;
          frame = null;
        });
      }
    } else if (sameAccount) {
      unawaited(selected == null ? load() : open(selected!));
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
  Widget build(BuildContext context) {
    final currentImage = review ?? frame;
    final colors = Theme.of(context).colorScheme;
    final retry = selected == null ? load : () => open(selected!);
    return ListenableBuilder(
      listenable: widget.app,
      builder: (context, _) => Scaffold(
        appBar: AppBar(
          title: const Text('Camera Raspberry'),
          actions: [
            if (widget.app.autoSendingCount > 0)
              Center(
                child: Container(
                  margin: const EdgeInsets.only(right: 4),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: colors.primaryContainer,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    'Đang gửi ${widget.app.autoSendingCount}',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: colors.onPrimaryContainer,
                    ),
                  ),
                ),
              ),
            IconButton(
              tooltip: 'Lật gương',
              onPressed: capturing || review != null
                  ? null
                  : () => setState(() => mirror = !mirror),
              isSelected: mirror,
              icon: const Icon(Icons.flip_outlined),
              selectedIcon: const Icon(Icons.flip),
            ),
          ],
        ),
        body: SafeArea(
          top: false,
          child: Column(
            children: [
              if (cameras.length > 1)
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 8,
                  ),
                  child: DropdownButton<String>(
                    value: selected,
                    isExpanded: true,
                    items: [
                      for (final camera in cameras)
                        DropdownMenuItem(
                          value: camera['id'] as String,
                          child: Text(camera['name'] as String),
                        ),
                    ],
                    onChanged: capturing || review != null
                        ? null
                        : (id) {
                            if (id != null) unawaited(open(id));
                          },
                  ),
                ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(18),
                    child: ColoredBox(
                      color: colors.surfaceContainerHighest,
                      child: Center(
                        child: error != null
                            ? SingleChildScrollView(
                                padding: const EdgeInsets.all(20),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    const Icon(
                                      Icons.videocam_off_outlined,
                                      size: 36,
                                    ),
                                    const SizedBox(height: 12),
                                    Text(error!, textAlign: TextAlign.center),
                                    TextButton(
                                      onPressed: loading ? null : retry,
                                      child: const Text('Kết nối lại'),
                                    ),
                                  ],
                                ),
                              )
                            : currentImage == null
                            ? const CircularProgressIndicator(
                                semanticsLabel: 'Đang mở webcam',
                              )
                            : InteractiveViewer(
                                key: ValueKey(review != null),
                                maxScale: 5,
                                child: Transform.flip(
                                  flipX: review == null && mirror,
                                  child: Image.memory(
                                    currentImage,
                                    cacheWidth: 1280,
                                    gaplessPlayback: true,
                                    fit: BoxFit.contain,
                                    errorBuilder: (_, _, _) =>
                                        const Icon(Icons.broken_image_outlined),
                                  ),
                                ),
                              ),
                      ),
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: Column(
                  children: [
                    Text(
                      review != null
                          ? (lastAutoSent
                                ? 'Đã chụp · tự động gửi OCR (0.5s)…'
                                : 'Đã lưu bản nháp · chuyển tiếp sau 0.5s…')
                          : 'Đặt trọn vùng chữ trong khung',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 6),
                    FilterChip(
                      selected: widget.app.cameraAutoSend,
                      avatar: Icon(
                        widget.app.cameraAutoSend
                            ? Icons.bolt_rounded
                            : Icons.bolt_outlined,
                        size: 16,
                      ),
                      label: const Text('Tự động gửi OCR sau khi chụp'),
                      onSelected: (v) =>
                          unawaited(widget.app.setCameraAutoSend(v)),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 10,
                      runSpacing: 8,
                      children: [
                        FilledButton.icon(
                          onPressed: review != null
                              ? skip
                              : capturing ||
                                    frame == null ||
                                    error != null ||
                                    widget.app.importing
                              ? null
                              : capture,
                          icon: Icon(
                            review == null
                                ? Icons.camera_alt_outlined
                                : Icons.add_a_photo_outlined,
                          ),
                          label: Text(
                            review != null
                                ? 'Chụp tiếp'
                                : capturing
                                ? 'Đang chụp…'
                                : 'Chụp ảnh',
                          ),
                        ),
                        OutlinedButton(
                          onPressed: capturing
                              ? null
                              : () => Navigator.pop(context),
                          child: const Text('Xong'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
