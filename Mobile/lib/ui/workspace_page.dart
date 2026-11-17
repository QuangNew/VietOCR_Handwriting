import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../domain/app_controller.dart';
import '../domain/document.dart';
import 'image_detail_page.dart';
import 'log_page.dart';
import 'pi_camera_page.dart';
import 'server_dialog.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.app});
  final AppController app;
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int tab = 0;
  AppController get app => widget.app;
  void notice(Object e) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(AppController.readableError(e))));
    }
  }

  Future<void> camera() async {
    if (!app.gatewayVerified) {
      notice(StateError('Kết nối và xác minh Raspberry trước.'));
      return;
    }
    await Navigator.push<void>(
      context,
      MaterialPageRoute(builder: (_) => PiCameraPage(app: app)),
    );
  }

  Future<void> export() async {
    final folder = await getTemporaryDirectory();
    final file = File(
      '${folder.path}/VietOCR-${DateTime.now().millisecondsSinceEpoch}.txt',
    );
    await file.writeAsString(app.allText, flush: true);
    await SharePlus.instance.share(
      ShareParams(files: [XFile(file.path)], title: 'Văn bản VietOCR'),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const Text(
          'VietOCR',
          style: TextStyle(fontWeight: FontWeight.w800),
        ),
        actions: [
          IconButton(
            tooltip: 'Google & Raspberry',
            onPressed: () => showServerDialog(context, app),
            icon: const Icon(Icons.account_circle_outlined),
          ),
          IconButton(
            tooltip: 'Đổi giao diện',
            onPressed: app.toggleTheme,
            icon: Icon(
              app.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
            ),
          ),
        ],
      ),
      body: !app.initialized
          ? const Center(child: CircularProgressIndicator())
          : !app.canUseWorkspace
          ? Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(28),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 500),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.document_scanner_outlined, size: 72),
                      const SizedBox(height: 24),
                      Text(
                        'Từ nét bút đến văn bản',
                        style: Theme.of(context).textTheme.headlineMedium,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Đăng nhập Google và xác minh qua Raspberry để mở không gian tài liệu.',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 24),
                      FilledButton.icon(
                        onPressed: () => showServerDialog(context, app),
                        icon: const Icon(Icons.login),
                        label: const Text('Đăng nhập Google'),
                      ),
                      const SizedBox(height: 12),
                      Text(app.message, textAlign: TextAlign.center),
                    ],
                  ),
                ),
              ),
            )
          : SafeArea(
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
                    child: Row(
                      children: [
                        Icon(
                          app.gatewayVerified
                              ? Icons.cloud_done_outlined
                              : Icons.cloud_off_outlined,
                          size: 18,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '${app.gatewayVerified ? 'Raspberry đã xác minh' : 'Bản nháp offline'} · ${app.accountEmail ?? 'Kiểm thử'}',
                            maxLines: 2,
                          ),
                        ),
                        TextButton(
                          onPressed: () async {
                            try {
                              await app.verifyGateway();
                            } catch (e) {
                              notice(e);
                            }
                          },
                          child: const Text('Kết nối lại'),
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: tab == 2
                        ? const LogPage()
                        : tab == 1
                        ? results()
                        : photos(),
                  ),
                  if (app.busy) LinearProgressIndicator(value: app.progress),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 8,
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            app.busy ? app.progressLabel : app.message,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (app.busy)
                          TextButton(
                            onPressed: app.cancel,
                            child: const Text('Tạm dừng'),
                          )
                        else
                          FilledButton.icon(
                            onPressed: app.sendCount == 0 || !app.canSend
                                ? null
                                : () => app.recognize(),
                            icon: const Icon(Icons.send_outlined),
                            label: Text('Gửi ${app.sendCount} ảnh'),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
      bottomNavigationBar: app.canUseWorkspace
          ? NavigationBar(
              selectedIndex: tab,
              onDestinationSelected: (v) => setState(() => tab = v),
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.photo_library_outlined),
                  label: 'Bản nháp',
                ),
                NavigationDestination(
                  icon: Icon(Icons.article_outlined),
                  label: 'Văn bản',
                ),
                NavigationDestination(
                  icon: Icon(Icons.bug_report_outlined),
                  label: 'Log',
                ),
              ],
            )
          : null,
    ),
  );
  Widget photos() => CustomScrollView(
    slivers: [
      SliverPadding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        sliver: SliverToBoxAdapter(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Tài liệu của bạn',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 8),
              const Text(
                'Chụp, chỉnh sửa rồi Gửi. Ảnh chưa gửi luôn ở trên thiết bị.',
              ),
              const SizedBox(height: 20),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  FilledButton.icon(
                    onPressed: app.importing ? null : camera,
                    icon: const Icon(Icons.camera_alt_outlined),
                    label: const Text('Camera Raspberry'),
                  ),
                  OutlinedButton.icon(
                    onPressed: app.importing
                        ? null
                        : () => app.pick(camera: false),
                    icon: const Icon(Icons.add_photo_alternate_outlined),
                    label: const Text('Tải ảnh lên'),
                  ),
                  OutlinedButton(
                    onPressed: app.busy ? null : app.addSamples,
                    child: const Text('Ảnh mẫu'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  const Text('Tự tách dòng'),
                  Switch(
                    value: app.splitLines,
                    onChanged: app.busy ? null : app.setSplit,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
      if (app.documents.isEmpty)
        const SliverFillRemaining(
          hasScrollBody: false,
          child: Center(child: Text('Chưa có ảnh. Thêm tấm đầu tiên nhé.')),
        ),
      SliverPadding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        sliver: SliverList.builder(
          itemCount: app.documents.length,
          itemBuilder: (context, index) {
            final item = app.documents[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Card(
                child: ListTile(
                  contentPadding: const EdgeInsets.all(12),
                  leading: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Image.file(
                      File(item.path),
                      width: 64,
                      height: 64,
                      fit: BoxFit.cover,
                      cacheWidth: 160,
                    ),
                  ),
                  title: Text(
                    item.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text(
                    item.error.isNotEmpty
                        ? item.error
                        : switch (item.status) {
                            DocumentStatus.ready => 'Bản nháp · chưa gửi',
                            DocumentStatus.processing =>
                              'Đang gửi / chờ kết quả',
                            DocumentStatus.done => 'Hoàn tất',
                            _ => 'Đã tạm dừng · có thể tiếp tục',
                          },
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Checkbox(
                        value: item.included,
                        onChanged: app.busy
                            ? null
                            : (value) =>
                                  app.setIncluded(item.id, value ?? false),
                        semanticLabel: 'Gửi ${item.name}',
                      ),
                      const Icon(Icons.open_in_full),
                    ],
                  ),
                  onTap: () {
                    app.select(index);
                    Navigator.push<void>(
                      context,
                      MaterialPageRoute(
                        builder: (_) => ImageDetailPage(app: app, item: item),
                      ),
                    );
                  },
                ),
              ),
            );
          },
        ),
      ),
    ],
  );
  Widget results() => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              'Văn bản',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
          ),
          IconButton(
            tooltip: 'Chép tất cả',
            onPressed: () =>
                Clipboard.setData(ClipboardData(text: app.allText)),
            icon: const Icon(Icons.copy_all_outlined),
          ),
          IconButton(
            tooltip: 'Xuất .txt',
            onPressed: app.allText.isEmpty ? null : export,
            icon: const Icon(Icons.file_download_outlined),
          ),
        ],
      ),
      for (final d in app.documents.where((d) => d.text.isNotEmpty))
        Padding(
          padding: const EdgeInsets.only(top: 16),
          child: TextFormField(
            key: ValueKey('${d.id}-${d.status}'),
            initialValue: d.text,
            maxLines: null,
            enabled: !app.busy,
            decoration: InputDecoration(
              labelText: d.name,
              alignLabelWithHint: true,
            ),
            onChanged: (v) => app.edit(d.id, v),
          ),
        ),
      if (app.allText.isEmpty)
        const Padding(
          padding: EdgeInsets.only(top: 80),
          child: Center(
            child: Text('Kết quả sẽ xuất hiện sau khi bạn nhấn Gửi.'),
          ),
        ),
    ],
  );
}
