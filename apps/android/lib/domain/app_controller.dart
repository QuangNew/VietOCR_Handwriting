import 'dart:async';
import 'dart:collection';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../ocr/cancellation.dart';
import '../ocr/engine.dart';
import '../ocr/remote_engine.dart';
import '../services/cloud_session.dart';
import '../services/scoped_token.dart';
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
  String serverUrl = 'https://api.quangnew.tech';
  bool gatewayVerified = false;
  bool checkingConnection = false;
  String? connectionError;
  String? _lastVerifiedAccount;
  bool get canUseWorkspace =>
      !_managedEngine ||
      (_accountId != null &&
          cloud.userId == _accountId &&
          (gatewayVerified || _lastVerifiedAccount == _accountId));
  bool get canSend => !_managedEngine || (gatewayVerified && canUseWorkspace);
  VietOcrRemote gateway() => VietOcrRemote(
    serverUrl,
    '',
    allowInsecureLan: serverInsecureLan,
    tokenProvider: scopedToken(
      owner: _accountId,
      currentOwner: () => cloud.userId,
      fetch: cloud.accessToken,
    ),
  );
  RemoteEngine _remoteFor(String origin, bool allowLan, String? owner) =>
      RemoteEngine(
        origin,
        '',
        allowInsecureLan: allowLan,
        tokenProvider: scopedToken(
          owner: owner,
          currentOwner: () => cloud.userId,
          fetch: cloud.accessToken,
        ),
      );
  Future<void> verifyGateway() async {
    final epoch = _accountEpoch, owner = _accountId, url = serverUrl;
    if (checkingConnection || owner == null) return;
    final remote = gateway();
    checkingConnection = true;
    connectionError = null;
    _notify();
    try {
      final session = await remote.session();
      if (_disposed || epoch != _accountEpoch || url != serverUrl) return;
      if ((session['account'] as Map)['userId'] != owner) {
        throw StateError('Tài khoản gateway không trùng phiên Google.');
      }
      await (await SharedPreferences.getInstance()).setString(
        'v2VerifiedAccount',
        owner,
      );
      if (_disposed || epoch != _accountEpoch || url != serverUrl) return;
      gatewayVerified = true;
      _lastVerifiedAccount = owner;
    } catch (e) {
      if (epoch == _accountEpoch && url == serverUrl) {
        gatewayVerified = false;
        connectionError = readableError(e);
      }
      rethrow;
    } finally {
      remote.close();
      if (epoch == _accountEpoch && url == serverUrl) {
        checkingConnection = false;
      }
      _notify();
    }
  }

  bool serverInsecureLan = false;
  final _picker = ImagePicker();
  final List<Document> _documents = [];
  List<Document> get documents => UnmodifiableListView(_documents);
  int get sendCount => _documents.where((d) => d.included && d.canSend).length;
  bool get hasPendingResults =>
      _documents.any((d) => d.status == DocumentStatus.processing) ||
      autoSendingCount > 0;
  int get autoSendingCount => _autoQueue.length + _autoCancels.length;
  void setIncluded(String id, bool included) {
    if (busy || importing) return;
    for (final d in _documents.where((d) => d.id == id)) {
      d.included = included;
    }
    _scheduleSave();
    _notify();
  }

  void setCustomQuad(String id, List<List<double>>? quad) {
    final doc = _documents.where((d) => d.id == id).firstOrNull;
    if (doc == null) return;
    doc.customQuad = quad;
    _scheduleSave();
    _notify();
  }

  bool dark = true,
      splitLines = true,
      correctText = false,
      cameraAutoSend = true,
      busy = false,
      importing = false,
      initialized = false;
  bool _disposed = false, _picking = false, _background = false;
  bool get picking => _picking;
  String message = 'Chụp rõ nét, đủ sáng để đọc chữ tốt hơn.',
      progressLabel = '';
  double? progress;
  CancellationToken? _cancel;
  Timer? _saveTimer;
  Timer? _recoveryTimer;
  bool _recovering = false;
  int _accountEpoch = 0, _recoveryCursor = 0;
  final _expiredResults = <String>{};
  final _pipelineCache = <String, Map<String, dynamic>>{};
  final _autoQueue = <String>[];
  final _autoCancels = <String, CancellationToken>{};
  int _autoWorkers = 0;
  Future<void>? _running;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize({bool recoverLost = true}) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      dark = prefs.getBool('dark') ?? true;
      splitLines = prefs.getBool('splitLines') ?? true;
      correctText = prefs.getBool('correctText') ?? false;
      cameraAutoSend = prefs.getBool('cameraAutoSend') ?? true;
      serverUrl = prefs.getString('v2GatewayUrl') ?? serverUrl;
      serverInsecureLan = prefs.getBool('ocrServerInsecure') ?? false;
      _lastVerifiedAccount = prefs.getString('v2VerifiedAccount');
      if (_managedEngine) {
        await cloud.initialize();
        _accountId = cloud.userId;
        store.setAccount(_accountId);
        cloud.addListener(_authChanged);
        engine = _remoteFor(serverUrl, serverInsecureLan, _accountId);
      }
      if (!_managedEngine || _accountId != null) {
        _documents.addAll(await store.load());
      }
      if (_disposed) return;
      if (_documents.isNotEmpty) {
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
    unawaited(recoverAcceptedResults());
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
    if (busy || importing || checkingConnection) {
      throw StateError('Dừng nhận diện trước khi đổi server.');
    }
    final next = _remoteFor(origin.trim(), allowInsecureLan, _accountId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('v2GatewayUrl', origin.trim());
    await prefs.setBool('ocrServerInsecure', allowInsecureLan);
    await prefs.remove('ocrServerEnabled');
    await engine.close();
    engine = next;
    gatewayVerified = false;
    connectionError = null;
    serverUrl = origin.trim();
    serverInsecureLan = allowInsecureLan;
    message = 'Nhận diện trên OCR Server. Không có model trên điện thoại.';
    _notify();
    if (_accountId != null) await verifyGateway();
  }

  Future<void> _authWork = Future.value();
  void _authChanged() {
    if (cloud.userId != _accountId) {
      gatewayVerified = false;
      checkingConnection = false;
      connectionError = null;
      _accountEpoch++;
      _cancel?.cancel();
      _recoveryTimer?.cancel();
      _notify();
    }
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
    await engine.close();
    if (_running != null) {
      try {
        await _running;
      } catch (_) {}
    }
    await flush();
    if (_disposed || id != cloud.userId) return;
    engine = id == null
        ? UnavailableServerEngine()
        : _remoteFor(serverUrl, serverInsecureLan, id);
    _documents.clear();
    _expiredResults.clear();
    _pipelineCache.clear();
    _autoQueue.clear();
    _recoveryCursor = 0;
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
      unawaited(recoverAcceptedResults());
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

  Future<void> setCorrectText(bool value) async {
    if (busy) return;
    correctText = value;
    _notify();
    try {
      await (await SharedPreferences.getInstance()).setBool(
        'correctText',
        value,
      );
    } catch (_) {
      message = 'Chưa lưu được lựa chọn sửa lỗi AI.';
      _notify();
    }
  }

  Future<void> setCameraAutoSend(bool value) async {
    cameraAutoSend = value;
    _notify();
    try {
      await (await SharedPreferences.getInstance()).setBool(
        'cameraAutoSend',
        value,
      );
    } catch (_) {
      message = 'Chưa lưu được tuỳ chọn tự động gửi khi chụp.';
      _notify();
    }
  }

  Future<Map<String, dynamic>?> fetchPipeline(Document doc) async {
    final jobId = doc.jobId;
    if (jobId == null || jobId.isEmpty) return null;
    final cached = _pipelineCache[jobId];
    if (cached != null) return cached;
    final currentEngine = engine;
    if (currentEngine is! RichOcrEngine) return null;
    final data = await (currentEngine as RichOcrEngine).fetchPipeline(jobId);
    if (data != null) {
      _pipelineCache[jobId] = data;
    }
    return data;
  }

  /// Background auto-send queue for camera captures (non-blocking so user can shoot every 0.5s).
  void enqueueAutoSend(String id, {bool? correct}) {
    if (_disposed || !canSend) return;
    final doc = _documents.where((d) => d.id == id).firstOrNull;
    if (doc == null ||
        doc.status == DocumentStatus.processing ||
        _autoQueue.contains(id) ||
        _autoCancels.containsKey(id)) {
      return;
    }
    doc.status = DocumentStatus.processing;
    doc.error = '';
    _autoQueue.add(id);
    _notify();
    _pumpAutoWorkers(correct: correct ?? correctText);
  }

  void _pumpAutoWorkers({required bool correct}) {
    final batchEngine = engine;
    final maxWorkers = batchEngine is ConcurrentOcrEngine
        ? (batchEngine as ConcurrentOcrEngine).parallelRequests.clamp(1, 2)
        : 1;
    while (_autoWorkers < maxWorkers && _autoQueue.isNotEmpty) {
      _autoWorkers++;
      final epoch = _accountEpoch;
      unawaited(() async {
        try {
          while (!_disposed &&
              epoch == _accountEpoch &&
              _autoQueue.isNotEmpty) {
            final id = _autoQueue.removeAt(0);
            final doc = _documents.where((d) => d.id == id).firstOrNull;
            if (doc == null) continue;
            final token = CancellationToken();
            _autoCancels[id] = token;
            _notify();
            try {
              if (batchEngine is RichOcrEngine) {
                final rich = await (batchEngine as RichOcrEngine).recognizeRich(
                  doc.path,
                  split: true,
                  correct: correct,
                  rotation: doc.rotation,
                  cancel: token,
                  progress: (_, _) {},
                );
                token.check();
                doc.text = rich.text;
                doc.jobId = rich.jobId ?? doc.jobId;
                doc.lens = rich.lens ?? doc.lens;
                doc.hasPipeline = rich.hasPipeline || doc.hasPipeline;
              } else {
                final text = await batchEngine.recognize(
                  doc.path,
                  split: true,
                  correct: correct,
                  rotation: doc.rotation,
                  cancel: token,
                  progress: (_, _) {},
                );
                token.check();
                doc.text = text;
              }
              doc.status = DocumentStatus.done;
              doc.included = false;
              doc.error = '';
            } on OcrCancelled {
              if (doc.status == DocumentStatus.processing) {
                doc.status = DocumentStatus.cancelled;
              }
            } catch (error, stack) {
              AppLog.instance.add(
                'OCR',
                'Tự động gửi ${doc.name} thất bại',
                level: 'ERROR',
                error: error,
                stack: stack,
              );
              doc.status = DocumentStatus.error;
              doc.error = readableError(error);
            } finally {
              _autoCancels.remove(id);
              await flush();
              _notify();
            }
          }
        } finally {
          _autoWorkers--;
          _notify();
        }
      }());
    }
  }

  Future<void> pickImages() async {
    if (importing || _picking || !initialized) return;
    _picking = true;
    final accountEpoch = _accountEpoch;
    _notify();
    try {
      final files = await _picker.pickMultiImage(requestFullMetadata: false);
      if (!_disposed && accountEpoch == _accountEpoch) {
        await _importFiles(files);
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
    final accountEpoch = _accountEpoch;
    try {
      for (final file in files) {
        if (_disposed || accountEpoch != _accountEpoch) break;
        if (await file.length() > 40 * 1024 * 1024) {
          throw const FormatException('Ảnh vượt 40 MB. Hãy chọn ảnh nhỏ hơn.');
        }
        rows.add((await file.readAsBytes(), file.name));
        if (accountEpoch != _accountEpoch) break;
        added += await _importRows(rows, accountEpoch: accountEpoch);
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
    required int accountEpoch,
  }) async {
    var added = 0;
    for (final (bytes, name) in rows) {
      if (_disposed || accountEpoch != _accountEpoch) break;
      final id =
          '${DateTime.now().microsecondsSinceEpoch}_${_documents.length}';
      final document = await store.import(bytes, name, id);
      if (_disposed || accountEpoch != _accountEpoch) {
        break;
      }
      _documents.add(document);
      added++;
      _notify();
    }
    return added;
  }

  Future<void> importImages(List<(Uint8List, String)> rows) async {
    if (importing || _disposed || rows.isEmpty) return;
    importing = true;
    final accountEpoch = _accountEpoch;
    _notify();
    try {
      final count = await _importRows(rows, accountEpoch: accountEpoch);
      message = 'Đã nhận $count ảnh. Sẵn sàng nhận diện.';
    } catch (error) {
      message = 'Không thêm được ảnh: ${readableError(error)}';
    } finally {
      importing = false;
      await flush();
      _notify();
    }
  }

  Future<void> remove(String id) async {
    if (busy || importing || !canUseWorkspace) return;
    final item = _documents.where((d) => d.id == id).firstOrNull;
    if (item == null || item.status == DocumentStatus.processing) return;
    _documents.remove(item);
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

  void edit(String id, String value) {
    final matches = _documents.where((document) => document.id == id);
    if (busy || matches.isEmpty) return;
    matches.first.text = value;
    _scheduleSave();
    _notify();
  }

  Future<void> recognize({
    bool retryErrors = true,
    String? only,
    bool? split,
    bool? correct,
  }) {
    if (!canSend) {
      message = 'Xác minh phiên Google với Raspberry trước khi gửi.';
      _notify();
      return Future.value();
    }
    if (_disposed || busy || importing || _documents.isEmpty) {
      return Future.value();
    }
    final batch = _documents
        .where(
          (d) =>
              d.canSend &&
              (only == null ? d.included : d.id == only) &&
              (retryErrors || d.status == DocumentStatus.ready),
        )
        .toList();
    if (batch.isEmpty) return Future.value();
    final cancel = CancellationToken();
    _cancel = cancel;
    busy = true;
    progress = 0;
    _notify();
    final operation = _recognize(
      cancel,
      batch,
      split ?? splitLines,
      correct ?? correctText,
    );
    _running = operation;
    return operation.whenComplete(() {
      _running = null;
    });
  }

  Future<void> _recognize(
    CancellationToken cancel,
    List<Document> batch,
    bool split,
    bool correct,
  ) async {
    var completed = 0, failed = 0;
    var workerStopped = false;
    final activeDocuments = <Document>{};
    final batchEngine = engine;
    var cursor = 0;
    Future<void> worker() async {
      while (cursor < batch.length && !workerStopped) {
        final i = cursor++;
        final active = batch[i];
        cancel.check();
        activeDocuments.add(active);
        active.status = DocumentStatus.processing;
        active.error = '';
        _notify();
        try {
          if (batchEngine is RichOcrEngine) {
            final rich = await (batchEngine as RichOcrEngine).recognizeRich(
              active.path,
              split: split,
              correct: correct,
              rotation: active.rotation,
              cancel: cancel,
              progress: (label, fraction) {
                if (_disposed || cancel.isCancelled) return;
                progressLabel = 'Ảnh ${i + 1}/${batch.length} · $label';
                progress = fraction == null
                    ? null
                    : (completed + fraction) / batch.length;
                _notify();
              },
            );
            cancel.check();
            active.text = rich.text;
            active.jobId = rich.jobId ?? active.jobId;
            active.lens = rich.lens ?? active.lens;
            active.hasPipeline = rich.hasPipeline || active.hasPipeline;
          } else {
            final text = await batchEngine.recognize(
              active.path,
              split: split,
              correct: correct,
              rotation: active.rotation,
              cancel: cancel,
              progress: (label, fraction) {
                if (_disposed || cancel.isCancelled) return;
                progressLabel = 'Ảnh ${i + 1}/${batch.length} · $label';
                progress = fraction == null
                    ? null
                    : (completed + fraction) / batch.length;
                _notify();
              },
            );
            cancel.check();
            active.text = text;
          }
          active.status = DocumentStatus.done;
          active.included = false;
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
          }
        }
        activeDocuments.remove(active);
        await flush();
        _notify();
      }
    }

    try {
      final parallel = batchEngine is ConcurrentOcrEngine
          ? (batchEngine as ConcurrentOcrEngine).parallelRequests.clamp(1, 2)
          : 1;
      await Future.wait(
        List.generate(parallel, (_) => worker()),
        eagerError: false,
      );
      message = workerStopped
          ? 'Hàng đợi đã tạm dừng. Kiểm tra đăng nhập, hạn mức hoặc server; các ảnh còn lại được giữ để thử tiếp.'
          : failed == 0
          ? 'Đã đọc xong $completed ảnh. Bạn có thể sửa và sao chép văn bản.'
          : 'Đã đọc $completed ảnh; $failed ảnh cần thử lại.';
    } on OcrCancelled {
      for (final active in activeDocuments) {
        if (active.status == DocumentStatus.processing) {
          active.status = DocumentStatus.cancelled;
        }
      }
      message = 'Đã dừng. Kết quả của $completed ảnh đã đọc được giữ lại.';
    } catch (error, stack) {
      AppLog.instance.add(
        'OCR',
        'Lượt nhận diện thất bại',
        level: 'ERROR',
        error: error,
        stack: stack,
      );
      for (final active in activeDocuments) {
        if (active.status == DocumentStatus.processing) {
          active.status = DocumentStatus.error;
          active.error = readableError(error);
        }
      }
      message = readableError(error);
    } finally {
      busy = false;
      _cancel = null;
      progress = null;
      progressLabel = '';
      await flush();
      await AppLog.instance.captureNative();

      _notify();
      if (!_disposed && !_background) {
        unawaited(recoverAcceptedResults());
      }
    }
  }

  void cancel() {
    final token = _cancel;
    final hasAuto = _autoQueue.isNotEmpty || _autoCancels.isNotEmpty;
    if ((token == null || token.isCancelled) && !hasAuto) return;
    AppLog.instance.add('OCR', 'Tạm dừng gửi');
    token?.cancel();
    _autoQueue.clear();
    for (final c in _autoCancels.values) {
      c.cancel();
    }
    if (_managedEngine && engine is RemoteEngine) {
      final previous = engine;
      engine = _remoteFor(serverUrl, serverInsecureLan, _accountId);
      unawaited(previous.close());
    }
    progressLabel = 'Đang tạm dừng…';
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
    _recoveryTimer?.cancel();
    await flush();
  }

  void foreground() {
    _background = false;
    unawaited(recoverAcceptedResults());
  }

  /// Restored images are never submitted here. Only known accepted jobs are read.
  Future<void> recoverAcceptedResults() async {
    _recoveryTimer?.cancel();
    final recovery = engine;
    if (_disposed ||
        _background ||
        busy ||
        importing ||
        _recovering ||
        !canUseWorkspace ||
        recovery is! AcceptedResultRecovery) {
      return;
    }
    final reader = recovery as AcceptedResultRecovery;
    _recovering = true;
    final epoch = _accountEpoch;
    var more = false, reads = 0;
    final candidates = _documents
        .where(
          (d) =>
              d.status != DocumentStatus.done &&
              !_expiredResults.contains(d.id),
        )
        .toList();
    try {
      for (var offset = 0; offset < candidates.length; offset++) {
        if (_disposed || _background || busy || epoch != _accountEpoch) break;
        final index = (_recoveryCursor + offset) % candidates.length;
        final document = candidates[index];
        try {
          final result = await reader.recoverAccepted(
            document.path,
            rotation: document.rotation,
          );
          if (_disposed ||
              epoch != _accountEpoch ||
              busy ||
              !_documents.contains(document)) {
            break;
          }
          if (result == null) continue;
          reads++;
          switch (result.state) {
            case 'succeeded':
              document.text = result.text;
              document.error = '';
              document.status = DocumentStatus.done;
            case 'failed' || 'cancelled':
              document.error = result.error;
              document.status = DocumentStatus.error;
              _expiredResults.add(document.id);
            default:
              document.status = DocumentStatus.processing;
              more = true;
          }
          if (reads >= 2) {
            _recoveryCursor = (index + 1) % candidates.length;
            more = true;
            break;
          }
        } on RemoteOcrException catch (error) {
          if (epoch != _accountEpoch || _disposed) break;
          if (error.status == 410) {
            document.status = DocumentStatus.error;
            document.error = readableError(error);
            _expiredResults.add(document.id);
          } else {
            more = true;
            break;
          }
        }
      }
      if (!_disposed && epoch == _accountEpoch) {
        await flush();
        _notify();
      }
    } catch (error) {
      more = true;
      AppLog.instance.add(
        'Recovery',
        'Chưa lấy được kết quả; bản nháp vẫn được giữ.',
        error: error,
      );
    } finally {
      _recovering = false;
      if (more && !_disposed && !_background && epoch == _accountEpoch) {
        _recoveryTimer = Timer(
          const Duration(seconds: 4),
          () => unawaited(recoverAcceptedResults()),
        );
      }
    }
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
    if (error is RemoteOcrException) return error.message;
    if (error is SocketException || error is TimeoutException) {
      return 'Mất kết nối. Kiểm tra mạng rồi thử lại.';
    }
    if (error is ArgumentError) {
      return error.message?.toString() ?? 'Cấu hình không hợp lệ.';
    }
    return 'Thao tác chưa hoàn tất. Thử lại hoặc xem Nhật ký trong Cài đặt.';
  }

  @override
  void dispose() {
    cloud.removeListener(_authChanged);
    _disposed = true;
    _saveTimer?.cancel();
    _recoveryTimer?.cancel();
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
