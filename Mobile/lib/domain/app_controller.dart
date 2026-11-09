import 'dart:async';
import 'dart:collection';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../ocr/decoder.dart';
import '../ocr/engine.dart';
import '../ocr/remote_engine.dart';
import '../services/cloud_session.dart';
import '../services/vietocr_remote.dart';
import '../services/session_store.dart';
import '../services/app_log.dart';
import 'document.dart';

class AppController extends ChangeNotifier {
  AppController({SessionStore? store, OcrEngine? engine})
    : store = store ?? SessionStore(),
      engine = engine ?? UnavailableServerEngine(),
      _managedEngine = engine == null;
  final SessionStore store;
  OcrEngine engine;
  final bool _managedEngine;
  final cloud = CloudSession.instance;
  String? _accountId;
  String? get accountEmail => cloud.email;
  String serverUrl = 'http://127.0.0.1:5082';
  bool gatewayVerified = false;
  String? _lastVerifiedAccount;
  bool get canUseWorkspace =>
      !_managedEngine ||
      (_accountId != null &&
          cloud.userId == _accountId &&
          (gatewayVerified || _lastVerifiedAccount == _accountId));
  bool get canSend => !_managedEngine || gatewayVerified;
  Future<void> verifyGateway() async {
    final remote = VietOcrRemote(
      serverUrl,
      '',
      allowInsecureLan: serverInsecureLan,
      tokenProvider: cloud.accessToken,
    );
    try {
      final session = await remote.session();
      if ((session['account'] as Map)['userId'] != cloud.userId) {
        throw StateError('Tài khoản gateway không trùng phiên Google.');
      }
      gatewayVerified = true;
      _lastVerifiedAccount = cloud.userId;
      await (await SharedPreferences.getInstance()).setString(
        'v2VerifiedAccount',
        cloud.userId!,
      );
      message = 'Đã xác minh Google qua Raspberry. Ảnh chỉ gửi khi nhấn Gửi.';
    } catch (e) {
      gatewayVerified = false;
      message = readableError(e);
      rethrow;
    } finally {
      remote.close();
      _notify();
    }
  }

  bool get serverMode => true;
  bool serverInsecureLan = false;
  final _picker = ImagePicker();
  final List<Document> _documents = [];
  List<Document> get documents => UnmodifiableListView(_documents);
  Document? get selected => _documents.isEmpty
      ? null
      : _documents[selectedIndex.clamp(0, _documents.length - 1)];
  int selectedIndex = 0;
  bool dark = true,
      splitLines = true,
      busy = false,
      importing = false,
      initialized = false;
  bool _disposed = false, _picking = false, _background = false;
  bool _queueHalted = false;
  bool get picking => _picking;
  String message = 'Chụp rõ nét, đủ sáng để đọc chữ tốt hơn.',
      progressLabel = '';
  double? progress;
  AssistantState assistant = AssistantState.awake;
  CancellationToken? _cancel;
  Timer? _saveTimer;
  Future<void>? _running;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize({bool recoverLost = true}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      dark = prefs.getBool('dark') ?? true;
      splitLines = prefs.getBool('splitLines') ?? true;
      serverUrl = prefs.getString('ocrServerUrl') ?? serverUrl;
      serverInsecureLan = prefs.getBool('ocrServerInsecure') ?? false;
      _lastVerifiedAccount = prefs.getString('v2VerifiedAccount');
      if (_managedEngine) {
        await cloud.initialize();
        _accountId = cloud.userId;
        store.setAccount(_accountId);
        cloud.addListener(_authChanged);
        engine = RemoteEngine(
          serverUrl,
          '',
          allowInsecureLan: serverInsecureLan,
          tokenProvider: cloud.accessToken,
        );
      }
      if (!_managedEngine || _accountId != null) {
        _documents.addAll(await store.load());
      }
      if (_disposed) return;
      if (_documents.isNotEmpty) {
        assistant = AssistantState.received;
        message = 'Đã khôi phục ${_documents.length} ảnh và kết quả.';
      }
    } catch (_) {
      message = 'Không khôi phục được phiên trước. Bạn có thể chọn ảnh mới.';
    } finally {
      initialized = true;
      _notify();
    }
    if (recoverLost && Platform.isAndroid && !_disposed) {
      try {
        final lost = await _picker.retrieveLostData();
        if (lost.files?.isNotEmpty ?? false) await _importFiles(lost.files!);
        if (lost.exception != null) {
          message = 'Không khôi phục được ảnh: ${lost.exception!.message}';
          _notify();
        }
      } catch (error) {
        message = 'Không khôi phục được ảnh: ${readableError(error)}';
        _notify();
      }
    }
    if (_managedEngine && _accountId != null) {
      try {
        await verifyGateway();
      } catch (_) {}
    }
  }

  Future<void> toggleTheme() async {
    dark = !dark;
    _notify();
    try {
      await (await SharedPreferences.getInstance()).setBool('dark', dark);
    } catch (_) {
      message = 'Chưa lưu được giao diện. Thử lại khi bộ nhớ còn trống.';
      _notify();
    }
  }

  Future<void> configureServer({
    required String origin,
    required bool allowInsecureLan,
  }) async {
    if (busy || importing) {
      throw StateError('Dừng nhận diện trước khi đổi server.');
    }
    final next = RemoteEngine(
      origin.trim(),
      '',
      allowInsecureLan: allowInsecureLan,
      tokenProvider: cloud.accessToken,
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('ocrServerUrl', origin.trim());
    await prefs.setBool('ocrServerInsecure', allowInsecureLan);
    await prefs.remove('ocrServerEnabled');
    await engine.close();
    engine = next;
    gatewayVerified = false;
    serverUrl = origin.trim();
    serverInsecureLan = allowInsecureLan;
    message = 'Nhận diện trên OCR Server. Không có model trên điện thoại.';
    _notify();
    if (_accountId != null) await verifyGateway();
  }

  Future<void> _authWork = Future.value();
  void _authChanged() {
    _authWork = _authWork.then((_) => _switchAccount()).catchError((
      Object error,
    ) {
      message = 'Không đổi được phiên tài khoản: ${readableError(error)}';
      _notify();
    });
  }

  Future<void> _switchAccount() async {
    final id = cloud.userId;
    if (_disposed || id == _accountId) {
      _notify();
      return;
    }
    cancel();
    if (_running != null) {
      try {
        await _running;
      } catch (_) {}
    }
    await flush();
    _documents.clear();
    selectedIndex = 0;
    _accountId = id;
    gatewayVerified = false;
    store.setAccount(id);
    _documents.addAll(await store.load());
    message = id == null
        ? 'Đã đăng xuất Google.'
        : 'Đã đăng nhập ${cloud.email}.';
    _notify();
    if (id != null) {
      try {
        await verifyGateway();
      } catch (_) {}
    }
  }

  Future<void> setSplit(bool value) async {
    if (busy) return;
    splitLines = value;
    _notify();
    try {
      await (await SharedPreferences.getInstance()).setBool(
        'splitLines',
        value,
      );
    } catch (_) {
      message = 'Chưa lưu được lựa chọn chế độ đọc.';
      _notify();
    }
  }

  void select(int index) {
    selectedIndex = index;
    _notify();
  }

  Future<void> pick({required bool camera}) async {
    if (importing || _picking || !initialized) return;
    _picking = true;
    _notify();
    try {
      final List<XFile> files;
      if (camera) {
        throw StateError('Mở camera Raspberry trong tab Camera.');
      } else {
        files = await _picker.pickMultiImage(requestFullMetadata: false);
      }
      if (!_disposed) {
        await _importFiles(files);
        _startQueue();
      }
    } catch (error) {
      message = 'Không lấy được ảnh: ${readableError(error)}';
      _notify();
    } finally {
      _picking = false;
      _notify();
    }
  }

  Future<void> _importFiles(List<XFile> files) async {
    if (files.isEmpty || _disposed) return;
    final rows = <(Uint8List, String)>[];
    // Keep only one original file in memory at a time during the import below.
    importing = true;
    _notify();
    var added = 0;
    try {
      for (final file in files) {
        if (_disposed) break;
        if (await file.length() > 40 * 1024 * 1024) {
          throw const FormatException('Ảnh vượt 40 MB. Hãy chọn ảnh nhỏ hơn.');
        }
        rows.add((await file.readAsBytes(), file.name));
        added += await _importRows(rows);
        rows.clear();
      }
      message = 'Đã nhận $added ảnh. Sẵn sàng nhận diện.';
    } catch (error) {
      message = 'Đã thêm $added ảnh. ${readableError(error)}';
    } finally {
      importing = false;
      await flush();
      _notify();
    }
  }

  Future<int> _importRows(
    List<(Uint8List, String)> rows, {
    bool preserveResolution = false,
  }) async {
    var added = 0;
    for (final (bytes, name) in rows) {
      if (_disposed) break;
      final id =
          '${DateTime.now().microsecondsSinceEpoch}_${_documents.length}';
      final document = await store.import(
        bytes,
        name,
        id,
        preserveResolution: preserveResolution,
      );
      if (_disposed) {
        await store.remove(document);
        break;
      }
      _documents.add(document);
      added++;
      selectedIndex = _documents.length - 1;
      if (!busy) assistant = AssistantState.received;
      _notify();
    }
    return added;
  }

  // Also used by the bundled offline samples and domain tests.
  Future<void> importImages(
    List<(Uint8List, String)> rows, {
    bool enqueue = false,
    bool preserveResolution = false,
  }) async {
    if (importing || _disposed || rows.isEmpty) return;
    importing = true;
    _notify();
    try {
      final count = await _importRows(
        rows,
        preserveResolution: preserveResolution,
      );
      message = 'Đã nhận $count ảnh. Sẵn sàng nhận diện.';
    } catch (error) {
      message = 'Không thêm được ảnh: ${readableError(error)}';
    } finally {
      importing = false;
      await flush();
      _notify();
    }
    // Capture/crop/import are drafts, including legacy callers using enqueue.
  }

  void _startQueue() {
    if (_queueHalted || _background) return;
    // Explicit Send is the only entry point to recognize().
  }

  Future<void> addSamples() async {
    try {
      final rows = <(Uint8List, String)>[];
      for (final name in ['test.jpg', 'test2.jpg']) {
        final bytes = await rootBundle.load('assets/samples/$name');
        rows.add((
          bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes),
          'Ảnh mẫu ${rows.length + 1}',
        ));
      }
      await importImages(rows);
    } catch (error) {
      message = 'Không mở được ảnh mẫu: ${readableError(error)}';
      _notify();
    }
  }

  Future<void> checkModel() {
    if (busy || importing || _disposed) return Future.value();
    final cancel = CancellationToken();
    _cancel = cancel;
    busy = true;
    assistant = AssistantState.processing;
    _notify();
    final operation = _checkModel(cancel);
    _running = operation;
    return operation.whenComplete(() {
      _running = null;
      _startQueue();
    });
  }

  Future<void> _checkModel(CancellationToken cancel) async {
    File? file;
    try {
      AppLog.instance.add(
        'AI CHECK',
        'Bắt đầu kiểm tra model bằng ảnh mẫu đóng gói',
      );
      final bytes = await rootBundle.load('assets/samples/test.jpg');
      final directory = await store.directory;
      await directory.create(recursive: true);
      file = File('${directory.path}/model-health-check.jpg');
      await file.writeAsBytes(
        bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes),
      );
      final text = await engine.recognize(
        file.path,
        split: false,
        rotation: 0,
        cancel: cancel,
        progress: (label, value) {
          if (_disposed || cancel.isCancelled) return;
          progressLabel = 'Kiểm tra AI · $label';
          progress = value;
          _notify();
        },
      );
      cancel.check();
      const expected = 'KHÁI QUÁT VỀ BIỂN ĐẢO VIỆT NAM';
      final normalized = text
          .trim()
          .replaceAll(RegExp(r'\s+'), ' ')
          .toUpperCase();
      if (normalized != expected) {
        throw StateError(
          'Model đọc sai ảnh chuẩn (mong đợi tiêu đề tiếng Việt). Chưa thể xác nhận AI hoạt động đúng. Xem Log và phiên bản model.',
        );
      }
      _queueHalted = false;
      assistant = AssistantState.awake;
      message =
          'Kiểm tra AI đạt: nội dung ảnh chuẩn khớp hoàn toàn trên máy này.';
      AppLog.instance.add(
        'AI CHECK',
        message,
        error: 'characters=${text.length}',
      );
    } catch (error, stack) {
      _queueHalted = true;
      assistant = cancel.isCancelled
          ? AssistantState.awake
          : AssistantState.error;
      message = 'Kiểm tra AI chưa đạt: ${readableError(error)}';
      AppLog.instance.add(
        'AI CHECK',
        message,
        level: 'ERROR',
        error: error,
        stack: stack,
      );
      try {
        AppLog.instance.add(
          'AI CHECK',
          'Chẩn đoán',
          error: 'server-only; origin=$serverUrl',
        );
      } catch (_) {}
    } finally {
      busy = false;
      _cancel = null;
      progress = null;
      progressLabel = '';
      try {
        if (file != null && await file.exists()) await file.delete();
      } catch (_) {}
      await AppLog.instance.captureNative();

      _notify();
    }
  }

  Future<void> removeSelected() async {
    if (busy || importing || selected == null) return;
    final item = selected!;
    _documents.remove(item);
    selectedIndex = selectedIndex.clamp(
      0,
      (_documents.length - 1).clamp(0, _documents.length),
    );
    assistant = _documents.isEmpty
        ? AssistantState.awake
        : AssistantState.received;
    message = 'Đã xóa ${item.name}';
    _notify();
    await flush();
    try {
      await store.remove(item);
    } catch (_) {
      message = 'Ảnh đã gỡ khỏi lượt đọc; chưa xóa được file cũ.';
      _notify();
    }
  }

  void rotateSelected() {
    if (busy || importing || selected == null) return;
    selected!.rotation = (selected!.rotation + 1) % 4;
    selected!.status = DocumentStatus.ready;
    selected!.error = '';
    assistant = AssistantState.received;
    _scheduleSave();
    _notify();
  }

  void edit(String id, String value) {
    final matches = _documents.where((document) => document.id == id);
    if (busy || matches.isEmpty) return;
    matches.first.text = value;
    _scheduleSave();
    _notify();
  }

  Future<void> recognize({bool retryErrors = true}) {
    if (!canSend) {
      message = 'Xác minh phiên Google với Raspberry trước khi gửi.';
      _notify();
      return Future.value();
    }
    if (_disposed || busy || importing || _documents.isEmpty) {
      return Future.value();
    }
    final cancel = CancellationToken();
    _queueHalted = false;
    _cancel = cancel;
    busy = true;
    assistant = AssistantState.processing;
    progress = 0;
    _notify();
    final operation = _recognize(cancel, retryErrors);
    _running = operation;
    return operation.whenComplete(() {
      _running = null;
      _startQueue();
    });
  }

  Future<void> _recognize(CancellationToken cancel, bool retryErrors) async {
    final batch = List<Document>.of(_documents);
    var completed = 0, failed = 0;
    var workerStopped = false;
    Document? active;
    try {
      for (var i = 0; i < batch.length; i++) {
        cancel.check();
        active = batch[i];
        if (active.status == DocumentStatus.done) continue;
        if (!retryErrors && active.status != DocumentStatus.ready) continue;
        selectedIndex = _documents.indexOf(active);
        active.status = DocumentStatus.processing;
        active.error = '';
        _notify();
        try {
          final text = await engine.recognize(
            active.path,
            split: splitLines,
            rotation: active.rotation,
            cancel: cancel,
            progress: (label, fraction) {
              if (_disposed || cancel.isCancelled) return;
              progressLabel = 'Ảnh ${i + 1}/${_documents.length} · $label';
              progress = fraction == null
                  ? null
                  : (i + fraction) / _documents.length;
              _notify();
            },
          );
          cancel.check();
          active.text = text;
          active.status = DocumentStatus.done;
          completed++;
        } on OcrCancelled {
          rethrow;
        } catch (error, stack) {
          AppLog.instance.add(
            'OCR',
            'Ảnh ${i + 1}/${_documents.length} thất bại',
            level: 'ERROR',
            error: error,
            stack: stack,
          );
          await AppLog.instance.captureNative();
          try {
            AppLog.instance.add(
              'OCR',
              'Thông tin sau lỗi',
              error: 'server-only; origin=$serverUrl',
            );
          } catch (_) {}
          active.status = DocumentStatus.error;
          active.error = readableError(error);
          failed++;
          if (error is RemoteOcrException &&
              [401, 403, 429, 503].contains(error.status)) {
            workerStopped = true;
            _queueHalted = true;
            break; // Keep remaining photos queued when login/quota/server needs attention.
          }
        }
        await flush();
        _notify();
      }
      assistant = failed == 0 ? AssistantState.done : AssistantState.error;
      message = workerStopped
          ? 'Hàng đợi đã tạm dừng. Kiểm tra đăng nhập, hạn mức hoặc server; các ảnh còn lại được giữ để thử tiếp.'
          : failed == 0
          ? 'Đã đọc xong $completed ảnh. Bạn có thể sửa và sao chép văn bản.'
          : 'Đã đọc $completed ảnh; $failed ảnh cần thử lại.';
    } on OcrCancelled {
      _queueHalted = true;
      if (active?.status == DocumentStatus.processing) {
        active!.status = DocumentStatus.cancelled;
      }
      assistant = AssistantState.awake;
      message = 'Đã dừng. Kết quả của $completed ảnh đã đọc được giữ lại.';
    } catch (error, stack) {
      _queueHalted = true;
      AppLog.instance.add(
        'OCR',
        'Lượt nhận diện thất bại',
        level: 'ERROR',
        error: error,
        stack: stack,
      );
      if (active?.status == DocumentStatus.processing) {
        active!.status = DocumentStatus.error;
        active.error = readableError(error);
      }
      assistant = AssistantState.error;
      message = readableError(error);
    } finally {
      busy = false;
      _cancel = null;
      progress = null;
      progressLabel = '';
      await flush();
      await AppLog.instance.captureNative();

      _notify();
    }
  }

  void cancel() {
    if (_cancel != null) AppLog.instance.add('OCR', 'Yêu cầu dừng nhận diện');
    _cancel?.cancel();
    progressLabel = 'Đang dừng sau bước hiện tại…';
    _notify();
  }

  void _scheduleSave() {
    _saveTimer?.cancel();
    _saveTimer = Timer(
      const Duration(milliseconds: 400),
      () => unawaited(flush()),
    );
  }

  Future<void> flush() async {
    _saveTimer?.cancel();
    try {
      await store.save(_documents);
    } catch (_) {
      message = 'Chưa lưu được kết quả. Kiểm tra bộ nhớ điện thoại.';
      _notify();
    }
  }

  Future<void> background() async {
    _background = true;
    if (!_picking) cancel();
    await flush();
  }

  void foreground() {
    _background = false;
  }

  String get allText => _documents
      .where((item) => item.text.isNotEmpty)
      .map((item) => item.text)
      .join('\n\n');
  static String readableError(Object error) {
    if (error is FormatException) return error.message;
    if (error is PlatformException) {
      return error.message ??
          'Không truy cập được chức năng này. Kiểm tra quyền ứng dụng.';
    }
    if (error is FileSystemException) {
      return 'Không đọc/ghi được ảnh. Kiểm tra bộ nhớ và chọn lại ảnh.';
    }
    if (error is StateError) return error.message;
    return 'Không xử lý được ảnh. Thử lại với ảnh rõ hơn. ($error)';
  }

  @override
  void dispose() {
    cloud.removeListener(_authChanged);
    _disposed = true;
    _saveTimer?.cancel();
    _cancel?.cancel();
    unawaited(() async {
      try {
        await _running;
      } finally {
        try {
          await engine.close();
        } catch (error) {
          debugPrint('OCR shutdown: $error');
        }
      }
    }());
    super.dispose();
  }
}
