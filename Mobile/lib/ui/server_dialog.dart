import 'package:flutter/material.dart';
import '../domain/app_controller.dart';
import '../services/cloud_session.dart';
import '../services/vietocr_remote.dart';

Future<void> showServerDialog(BuildContext context, AppController app) async {
  final origin = TextEditingController(text: app.serverUrl);
  var insecure = app.serverInsecureLan, saving = false;
  String? error;
  Map<String, dynamic>? account;
  List<Map<String, dynamic>> history = [];
  final cloud = CloudSession.instance;
  Future<void> updateInfo() async {
    final token = await cloud.accessToken();
    final transport = VietOcrRemote(
      origin.text.trim(),
      token,
      allowInsecureLan: insecure,
    );
    try {
      account = await transport.account();
      history = await transport.history();
    } finally {
      transport.close();
    }
  }

  try {
    await cloud.initialize();
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialog) => StatefulBuilder(
        builder: (context, update) {
          Future<void> run(Future<void> Function() task) async {
            update(() {
              saving = true;
              error = null;
            });
            try {
              await task();
            } catch (e) {
              if (dialog.mounted) error = AppController.readableError(e);
            } finally {
              if (dialog.mounted) update(() => saving = false);
            }
          }

          return ListenableBuilder(
            listenable: cloud,
            builder: (context, _) => AlertDialog(
              title: const Text('Google & Raspberry'),
              scrollable: true,
              content: SizedBox(
                width: 480,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Ảnh gửi qua Raspberry để xác minh, sau đó model chạy trên server. Kết quả trả trực tiếp về ứng dụng.',
                    ),
                    const SizedBox(height: 18),
                    TextField(
                      controller: origin,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      enabled: !saving,
                      decoration: const InputDecoration(
                        labelText: 'Địa chỉ Raspberry gateway',
                        hintText: 'https://pi.example.com',
                      ),
                    ),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      title: const Text('Cho phép HTTP trong LAN tin cậy'),
                      value: insecure,
                      onChanged: saving
                          ? null
                          : (v) => update(() => insecure = v ?? false),
                    ),
                    const Text(
                      'Dùng địa chỉ HTTPS tunnel của Pi. Không nhập địa chỉ máy chạy model.',
                    ),
                    const Divider(height: 32),
                    Text(
                      cloud.email ?? 'Chưa đăng nhập Google',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Một định danh cố định cho mỗi tài khoản. Tối đa 500 ảnh/ngày và 30 request trong 60 giây, dùng chung trên mọi thiết bị.',
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      children: [
                        FilledButton.icon(
                          onPressed: saving || app.busy
                              ? null
                              : () => run(cloud.login),
                          icon: const Icon(Icons.login),
                          label: const Text('Đăng nhập Google'),
                        ),
                        OutlinedButton(
                          onPressed: saving || cloud.email == null
                              ? null
                              : () => run(updateInfo),
                          child: const Text('Tài khoản & hạn mức'),
                        ),
                        if (cloud.email != null)
                          TextButton(
                            onPressed: saving || app.busy
                                ? null
                                : () => run(() async {
                                    await cloud.logout();
                                    account = null;
                                    history = [];
                                  }),
                            child: const Text('Đăng xuất'),
                          ),
                      ],
                    ),
                    if (account != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: SelectableText(
                          '${account!['ocrId'] ?? account!['id']}\nHôm nay: ${account!['usedToday']}/${account!['dailyLimit']} ảnh · ${account!['usedLastMinute']}/${account!['ratePerMinute']} trong 60 giây.\nĐặt lại ngày lúc 00:00 giờ Việt Nam.',
                        ),
                      ),
                    if (history.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      const Text('Lịch sử nhận diện trên Supabase'),
                      ...history
                          .take(15)
                          .map(
                            (job) => ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(
                                '#${(job['id'] as String).substring(0, 8)} · ${job['state']}',
                              ),
                              subtitle: Text(job['createdAt'].toString()),
                              trailing: const Icon(Icons.chevron_right),
                              onTap: () => run(() async {
                                final remote = VietOcrRemote(
                                  origin.text.trim(),
                                  await cloud.accessToken(),
                                  allowInsecureLan: insecure,
                                );
                                try {
                                  final full = await remote.get(
                                    job['id'] as String,
                                  );
                                  if (dialog.mounted) {
                                    await showDialog<void>(
                                      context: dialog,
                                      builder: (c) => AlertDialog(
                                        title: const Text('Kết quả OCR'),
                                        scrollable: true,
                                        content: SelectableText(
                                          full['text'] as String? ??
                                              full['error'] as String? ??
                                              full['state'] as String,
                                        ),
                                        actions: [
                                          TextButton(
                                            onPressed: () => Navigator.pop(c),
                                            child: const Text('Đóng'),
                                          ),
                                        ],
                                      ),
                                    );
                                  }
                                } finally {
                                  remote.close();
                                }
                              }),
                            ),
                          ),
                    ],
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 14),
                        child: Text(
                          error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                    if (saving)
                      const Padding(
                        padding: EdgeInsets.only(top: 12),
                        child: LinearProgressIndicator(),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: saving ? null : () => Navigator.pop(dialog),
                  child: const Text('Đóng'),
                ),
                FilledButton(
                  onPressed: saving || app.busy
                      ? null
                      : () => run(() async {
                          await app.configureServer(
                            origin: origin.text,
                            allowInsecureLan: insecure,
                          );
                          if (dialog.mounted) Navigator.pop(dialog);
                        }),
                  child: const Text('Lưu Raspberry'),
                ),
              ],
            ),
          );
        },
      ),
    );
  } finally {
    origin.dispose();
  }
}
