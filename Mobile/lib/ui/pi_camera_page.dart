import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../domain/app_controller.dart';
import '../services/gateway_client.dart';

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
  bool capturing = false;
  int seconds = 0;
  DateTime last = DateTime.fromMillisecondsSinceEpoch(0);
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    client = makeClient();
    unawaited(load());
  }

  VietOcrRemote makeClient() => VietOcrRemote(
    widget.app.serverUrl,
    '',
    allowInsecureLan: widget.app.serverInsecureLan,
    tokenProvider: widget.app.cloud.accessToken,
  );
  Future<void> load() async {
    try {
      final items = await client.cameras();
      if (!mounted) return;
      setState(() => cameras = items);
      if (items.isNotEmpty) await open(items.first['id'] as String);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> open(String id) async {
    client.close();
    await stream?.cancel();
    client = makeClient();
    if (!mounted) return;
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
                review != null ||
                DateTime.now().difference(last).inMilliseconds < 60) {
              return;
            }
            last = DateTime.now();
            setState(() => frame = bytes);
          },
          onError: (Object e) {
            if (mounted) setState(() => error = e.toString());
          },
        );
  }

  Future<void> capture() async {
    if (selected == null || capturing) return;
    setState(() => capturing = true);
    try {
      final bytes = await client.snapshot(selected!);
      if (!mounted) return;
      await widget.app.importImages([
        (bytes, 'Raspberry_${DateTime.now().millisecondsSinceEpoch}.jpg'),
      ], preserveResolution: true);
      if (!mounted) return;
      setState(() {
        review = bytes;
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
      client.close();
      unawaited(stream?.cancel());
    } else if (selected != null) {
      unawaited(open(selected!));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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
