import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../domain/app_controller.dart';
import '../domain/document.dart';
import 'document_page.dart';
import 'pi_camera_page.dart';
import 'settings_page.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.app});
  final AppController app;

  @override
  State<HomePage> createState() => _HomePageState();
}

enum _Filter { all, drafts, results }

class _HomePageState extends State<HomePage> {
  _Filter filter = _Filter.all;
  bool openingLogin = false;
  bool loginOpened = false;
  AppController get app => widget.app;

  Future<void> _login() async {
    setState(() => openingLogin = true);
    try {
      await app.cloud.login();
      if (mounted) setState(() => loginOpened = true);
    } catch (error) {
      if (mounted) showNotice(context, AppController.readableError(error));
    } finally {
      if (mounted) setState(() => openingLogin = false);
    }
  }

  void _connect() => unawaited(app.verifyGateway().catchError((Object _) {}));

  void _settings() => Navigator.of(
    context,
  ).push<void>(MaterialPageRoute(builder: (_) => SettingsPage(app: app)));

  Future<void> _addPhoto({required bool camera}) async {
    if (camera && !app.canSend) {
      showNotice(context, 'Kết nối Raspberry để mở webcam.');
      return;
    }
    if (filter != _Filter.all) setState(() => filter = _Filter.all);
    if (camera) {
      await Navigator.of(
        context,
      ).push<void>(MaterialPageRoute(builder: (_) => PiCameraPage(app: app)));
    } else {
      await app.pickImages();
      if (mounted && app.message.isNotEmpty) showNotice(context, app.message);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const Text(
          'VietHandOCR',
          style: TextStyle(fontWeight: FontWeight.w800),
        ),
        actions: [
          IconButton(
            tooltip: 'Cài đặt',
            icon: const Icon(Icons.settings_outlined),
            onPressed: app.initialized ? _settings : null,
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        bottom: false,
        child: !app.initialized
            ? const Center(child: CircularProgressIndicator())
            : app.canUseWorkspace
            ? _workspace(context)
            : _welcome(context),
      ),
      bottomNavigationBar: app.initialized && app.canUseWorkspace
          ? _SendBar(app: app)
          : null,
    ),
  );

  Widget _welcome(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final signedIn = app.accountEmail != null;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: colors.primaryContainer,
                    borderRadius: BorderRadius.circular(24),
                  ),
                  child: Icon(
                    Icons.document_scanner_outlined,
                    size: 34,
                    color: colors.onPrimaryContainer,
                  ),
                ),
              ),
              const SizedBox(height: 26),
              Text(
                signedIn ? 'Kết nối Raspberry' : 'Đọc chữ từ ảnh',
                style: Theme.of(context).textTheme.headlineLarge,
              ),
              const SizedBox(height: 12),
              Text(
                signedIn
                    ? app.connectionError ??
                          'Xác minh tài khoản để chụp và gửi ảnh.'
                    : 'Chụp bằng webcam Raspberry hoặc chọn ảnh có sẵn để chuyển thành văn bản.',
              ),
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: openingLogin || app.checkingConnection
                    ? null
                    : signedIn
                    ? _connect
                    : _login,
                icon: Icon(signedIn ? Icons.refresh : Icons.login),
                label: Text(
                  app.checkingConnection
                      ? 'Đang xác minh…'
                      : signedIn
                      ? 'Kết nối lại'
                      : 'Đăng nhập Google',
                ),
              ),
              if (loginOpened && !signedIn)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Text(
                    'Hoàn tất đăng nhập trong trình duyệt rồi quay lại VietHandOCR.',
                  ),
                ),
              if (signedIn)
                TextButton(
                  onPressed: _settings,
                  child: const Text('Cài đặt kết nối'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _workspace(BuildContext context) {
    final docs = app.documents;
    final visible = docs.reversed
        .where(
          (d) => switch (filter) {
            _Filter.all => true,
            _Filter.drafts => d.status != DocumentStatus.done,
            _Filter.results => d.status == DocumentStatus.done,
          },
        )
        .toList();
    return CustomScrollView(
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Tài liệu của bạn',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 8),
                _ConnectionState(app: app, retry: _connect),
                const SizedBox(height: 16),
                _PhotoActions(
                  camera: app.importing || !app.canSend
                      ? null
                      : () => _addPhoto(camera: true),
                  gallery: app.importing || app.picking
                      ? null
                      : () => _addPhoto(camera: false),
                ),
                if (app.importing || app.picking) ...[
                  const SizedBox(height: 12),
                  const LinearProgressIndicator(semanticsLabel: 'Đang mở ảnh'),
                ],
                if (docs.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    children: [
                      for (final (value, label) in const [
                        (_Filter.all, 'Tất cả'),
                        (_Filter.drafts, 'Chưa xong'),
                        (_Filter.results, 'Đã đọc'),
                      ])
                        ChoiceChip(
                          label: Text(label),
                          selected: filter == value,
                          onSelected: (_) => setState(() => filter = value),
                        ),
                    ],
                  ),
                  if (filter == _Filter.results && app.allText.isNotEmpty)
                    TextButton.icon(
                      onPressed: () async {
                        try {
                          await shareText(app.allText);
                        } catch (error) {
                          if (context.mounted) {
                            showNotice(
                              context,
                              AppController.readableError(error),
                            );
                          }
                        }
                      },
                      icon: const Icon(Icons.ios_share),
                      label: const Text('Xuất tất cả văn bản'),
                    ),
                ],
              ],
            ),
          ),
        ),
        if (visible.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      docs.isEmpty
                          ? Icons.photo_library_outlined
                          : Icons.description_outlined,
                      size: 42,
                      color: Theme.of(context).colorScheme.outline,
                    ),
                    const SizedBox(height: 14),
                    Text(
                      docs.isEmpty
                          ? 'Chưa có tài liệu'
                          : filter == _Filter.results
                          ? 'Chưa có văn bản'
                          : 'Tất cả ảnh đã được đọc',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    if (docs.isEmpty) ...[
                      const SizedBox(height: 6),
                      const Text(
                        'Chụp tài liệu hoặc chọn ảnh để bắt đầu.',
                        textAlign: TextAlign.center,
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
          sliver: SliverList.builder(
            itemCount: visible.length,
            itemBuilder: (context, index) {
              final item = visible[index];
              return Padding(
                key: ValueKey(item.id),
                padding: const EdgeInsets.only(bottom: 8),
                child: _DocumentTile(
                  item: item,
                  choose: app.busy || app.importing || !item.canSend
                      ? null
                      : (value) => app.setIncluded(item.id, value ?? false),
                  open: () => Navigator.of(context).push<void>(
                    MaterialPageRoute(
                      builder: (_) => DocumentPage(app: app, id: item.id),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _ConnectionState extends StatelessWidget {
  const _ConnectionState({required this.app, required this.retry});
  final AppController app;
  final VoidCallback retry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Row(
      children: [
        Icon(
          app.canSend ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
          size: 18,
          color: app.canSend ? colors.primary : colors.error,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            app.checkingConnection
                ? 'Đang kiểm tra kết nối…'
                : app.canSend
                ? 'Raspberry đã kết nối'
                : 'Ngoại tuyến · ảnh vẫn được lưu',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        if (!app.canSend)
          TextButton(
            onPressed: app.checkingConnection ? null : retry,
            child: const Text('Kết nối lại'),
          ),
      ],
    );
  }
}

class _PhotoActions extends StatelessWidget {
  const _PhotoActions({this.camera, this.gallery});
  final VoidCallback? camera, gallery;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final shoot = FilledButton.icon(
        onPressed: camera,
        icon: const Icon(Icons.camera_alt_outlined),
        label: const Text('Chụp tài liệu'),
      );
      final select = OutlinedButton.icon(
        onPressed: gallery,
        icon: const Icon(Icons.photo_library_outlined),
        label: const Text('Chọn ảnh'),
      );
      if (constraints.maxWidth < 295 ||
          MediaQuery.textScalerOf(context).scale(14) > 18) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [shoot, const SizedBox(height: 8), select],
        );
      }
      return Row(
        children: [
          Expanded(child: shoot),
          const SizedBox(width: 10),
          Expanded(child: select),
        ],
      );
    },
  );
}

class _DocumentTile extends StatelessWidget {
  const _DocumentTile({required this.item, required this.open, this.choose});
  final Document item;
  final VoidCallback open;
  final ValueChanged<bool?>? choose;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final status = documentStatus(item);
    return Card(
      color: colors.surfaceContainerLow,
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        leading: ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: RotatedBox(
            quarterTurns: item.rotation,
            child: Image.file(
              File(item.path),
              width: 52,
              height: 52,
              fit: BoxFit.cover,
              cacheWidth: 144,
              errorBuilder: (_, _, _) => const SizedBox(
                width: 52,
                height: 52,
                child: Icon(Icons.broken_image_outlined),
              ),
            ),
          ),
        ),
        title: Text(item.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          status,
          style: TextStyle(
            color: item.status == DocumentStatus.error
                ? colors.error
                : colors.onSurfaceVariant,
          ),
        ),
        trailing: item.canSend
            ? Checkbox(
                value: item.included,
                onChanged: choose,
                semanticLabel: 'Chọn gửi ${item.name}',
              )
            : Icon(
                item.status == DocumentStatus.done
                    ? Icons.chevron_right
                    : Icons.hourglass_top_rounded,
              ),
        onTap: open,
      ),
    );
  }
}

class _SendBar extends StatelessWidget {
  const _SendBar({required this.app});
  final AppController app;

  @override
  Widget build(BuildContext context) {
    if (app.sendCount == 0 && !app.busy && !app.hasPendingResults) {
      return const SizedBox.shrink();
    }
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surfaceContainer,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: app.busy
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    LinearProgressIndicator(value: app.progress),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            app.progressLabel.isEmpty
                                ? 'Đang chuẩn bị gửi…'
                                : app.progressLabel,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        TextButton(
                          onPressed: app.cancel,
                          child: const Text('Tạm dừng'),
                        ),
                      ],
                    ),
                  ],
                )
              : app.sendCount == 0
              ? const Text('Đang chờ văn bản từ máy chủ…')
              : Wrap(
                  alignment: WrapAlignment.spaceBetween,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    PopupMenuButton<bool>(
                      tooltip: 'Cách đọc ảnh',
                      initialValue: app.splitLines,
                      onSelected: app.setSplit,
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: true, child: Text('Tự tách dòng')),
                        PopupMenuItem(value: false, child: Text('Một dòng')),
                      ],
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(app.splitLines ? 'Tự tách dòng' : 'Một dòng'),
                            const Icon(Icons.expand_more, size: 18),
                          ],
                        ),
                      ),
                    ),
                    FilterChip(
                      selected: app.correctText,
                      onSelected: app.busy ? null : app.setCorrectText,
                      label: const Text('Nội suy BARTpho'),
                      tooltip: 'Chạy thêm BARTpho v2 sau ML_s44 để sửa lỗi dấu/ngữ cảnh',
                    ),
                    FilledButton.icon(
                      onPressed: app.canSend && !app.importing
                          ? () async {
                              await app.recognize();
                              if (context.mounted) {
                                showNotice(context, app.message);
                              }
                            }
                          : null,
                      icon: const Icon(Icons.send_outlined),
                      label: Text('Gửi ${app.sendCount} ảnh'),
                    ),
                  ],
                ),
        ),
      ),
    );
  }
}
