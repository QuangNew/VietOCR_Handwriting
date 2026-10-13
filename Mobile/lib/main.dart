import 'dart:async';
import 'package:flutter/material.dart';
import 'domain/app_controller.dart';
import 'services/ble_assistant.dart';
import 'ui/home_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const VietOcrApp());
}

class VietOcrApp extends StatefulWidget {
  const VietOcrApp({super.key, this.controller, this.enableBluetooth = true});
  final AppController? controller;
  final bool enableBluetooth;
  @override
  State<VietOcrApp> createState() => _VietOcrAppState();
}

class _VietOcrAppState extends State<VietOcrApp> with WidgetsBindingObserver {
  late final AppController app;
  BleAssistant? ble;
  Future<void> _lifecycle = Future.value();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    app = widget.controller ?? AppController();
    if (widget.enableBluetooth) ble = BleAssistant();
    app.addListener(_changed);
    ble?.addListener(_changed);
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    if (!app.initialized) await app.initialize();
    try {
      await ble?.initialize();
    } catch (error) {
      ble?.message = 'Bluetooth chưa sẵn sàng: $error';
    }
    _changed();
  }

  void _changed() {
    if (!mounted) return;
    ble?.update(
      app.assistant,
      app.documents.length,
      ((app.progress ?? 0) * 100).round(),
    );
    setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (app.picking) return;
    final foreground = state == AppLifecycleState.resumed;
    if (!foreground &&
        state != AppLifecycleState.paused &&
        state != AppLifecycleState.detached &&
        state != AppLifecycleState.hidden) {
      return;
    }
    _lifecycle = _lifecycle
        .then((_) async {
          if (!foreground) await app.background();
          await ble?.setForeground(foreground);
        })
        .catchError((Object error) {
          debugPrint('Lifecycle: $error');
        });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    app.removeListener(_changed);
    ble?.removeListener(_changed);
    ble?.dispose();
    if (widget.controller == null) app.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = ColorScheme.fromSeed(
      seedColor: const Color(0xff88d577),
      brightness: app.dark ? Brightness.dark : Brightness.light,
    );
    return MaterialApp(
      title: 'VietOCR',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: colors,
        scaffoldBackgroundColor: app.dark
            ? const Color(0xff101410)
            : const Color(0xfff4f7f1),
        cardTheme: CardThemeData(
          elevation: 0,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(24),
          ),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          alignLabelWithHint: true,
        ),
      ),
      home: HomePage(app: app, ble: ble),
    );
  }
}
