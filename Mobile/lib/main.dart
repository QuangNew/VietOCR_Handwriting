import 'dart:async';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'domain/app_controller.dart';
import 'services/app_log.dart';
import 'ui/workspace_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // Bounded decoded preview cache; the model runs only on compute.
  PaintingBinding.instance.imageCache.maximumSizeBytes = 24 * 1024 * 1024;
  PaintingBinding.instance.imageCache.maximumSize = 48;
  final log = AppLog.instance;
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    log.add(
      'Flutter',
      'Lỗi giao diện',
      level: 'ERROR',
      error: details.exception,
      stack: details.stack,
    );
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    log.add(
      'Dart',
      'Lỗi bất đồng bộ',
      level: 'ERROR',
      error: error,
      stack: stack,
    );
    return true;
  };
  unawaited(() async {
    await log.initialize();
    try {
      log.add('App', 'Khởi động', error: 'OCR mode: server-only');
      await log.captureNative();
    } catch (error, stack) {
      log.add(
        'App',
        'Không đọc được thông tin thiết bị',
        level: 'ERROR',
        error: error,
        stack: stack,
      );
    }
  }());
  runApp(const VietOcrApp());
}

class VietOcrApp extends StatefulWidget {
  const VietOcrApp({super.key, this.controller, this.enableBluetooth = false});
  final AppController? controller;
  final bool enableBluetooth;
  @override
  State<VietOcrApp> createState() => _VietOcrAppState();
}

class _VietOcrAppState extends State<VietOcrApp> with WidgetsBindingObserver {
  late final AppController app;
  Future<void> _lifecycle = Future.value();
  bool _dark = true;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    app = widget.controller ?? AppController();
    _dark = app.dark;
    app.addListener(_changed);
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    if (!app.initialized) await app.initialize();
    _changed();
  }

  void _changed() {
    if (!mounted) return;
    if (_dark != app.dark) setState(() => _dark = app.dark);
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
          if (!foreground) {
            await app.background();
          } else {
            app.foreground();
          }
        })
        .catchError((Object error, StackTrace stack) {
          AppLog.instance.add(
            'App',
            'Chuyển trạng thái ứng dụng thất bại',
            level: 'ERROR',
            error: error,
            stack: stack,
          );
        });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    app.removeListener(_changed);
    if (widget.controller == null) app.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = ColorScheme.fromSeed(
      seedColor: const Color(0xff0087bb),
      brightness: app.dark ? Brightness.dark : Brightness.light,
    );
    return MaterialApp(
      title: 'VietOCR',
      debugShowCheckedModeBanner: false,
      themeAnimationDuration: Duration.zero,
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: 'Roboto',
        // Keep font sizes/weights identical in both palettes: color changes only.
        textTheme: ThemeData(useMaterial3: true, fontFamily: 'Roboto').textTheme
            .apply(bodyColor: colors.onSurface, displayColor: colors.onSurface),
        colorScheme: colors,
        scaffoldBackgroundColor: app.dark
            ? const Color(0xff14171b)
            : const Color(0xfff5f7fa),
        appBarTheme: AppBarTheme(
          centerTitle: false,
          backgroundColor: colors.surface,
          foregroundColor: colors.onSurface,
          scrolledUnderElevation: 0,
        ),
        navigationBarTheme: NavigationBarThemeData(
          height: 72,
          backgroundColor: colors.surface,
          indicatorColor: colors.primaryContainer,
          labelTextStyle: WidgetStateProperty.all(
            const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size(48, 48),
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
          ),
        ),
        cardTheme: CardThemeData(
          elevation: 0,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          alignLabelWithHint: true,
        ),
      ),
      home: HomePage(app: app),
    );
  }
}
