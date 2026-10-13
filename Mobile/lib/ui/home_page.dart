import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../domain/app_controller.dart';
import '../domain/document.dart';
import '../services/ble_assistant.dart';
import 'assistant_face.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.app, this.ble});
  final AppController app;
  final BleAssistant? ble;
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int tab = 0;
  AppController get app => widget.app;
  String get stateLabel => switch (app.assistant) {
    AssistantState.awake => 'Mình sẵn sàng rồi!',
    AssistantState.received => 'Đã nhận ${app.documents.length} ảnh',
    AssistantState.processing => 'Mình đang đọc chữ…',
    AssistantState.done => 'Xong rồi nhé!',
    AssistantState.error => 'Thử lại cùng mình nhé',
    AssistantState.sleeping => 'Hẹn gặp lại…',
  };
  void _notice(String message) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text(
        'VietOCR',
        style: TextStyle(fontWeight: FontWeight.w800),
      ),
      actions: [
        IconButton(
          tooltip: app.dark ? 'Giao diện sáng' : 'Giao diện tối',
          onPressed: app.toggleTheme,
          icon: Icon(
            app.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
          ),
        ),
        const SizedBox(width: 8),
      ],
    ),
    body: SafeArea(
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: !app.initialized
              ? const Center(child: CircularProgressIndicator())
              : switch (tab) {
                  0 => _photos(),
                  1 => _results(),
                  _ => _assistant(),
                },
        ),
      ),
    ),
    bottomNavigationBar: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (app.documents.isNotEmpty) _recognitionBar(),
        NavigationBar(
          selectedIndex: tab,
          onDestinationSelected: (value) => setState(() => tab = value),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.photo_camera_outlined),
              selectedIcon: Icon(Icons.photo_camera),
              label: 'Ảnh',
            ),
            NavigationDestination(
              icon: Icon(Icons.article_outlined),
              selectedIcon: Icon(Icons.article),
              label: 'Văn bản',
            ),
            NavigationDestination(
              icon: Icon(Icons.smart_toy_outlined),
              selectedIcon: Icon(Icons.smart_toy),
              label: 'Trợ lý',
            ),
          ],
        ),
      ],
    ),
  );

  Widget _recognitionBar() => Padding(
    padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (app.busy) ...[
          LinearProgressIndicator(
            value: app.progress,
            borderRadius: BorderRadius.circular(8),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Text(
              app.progressLabel,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ],
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: app.importing
                ? null
                : app.busy
                ? app.cancel
                : app.recognize,
            icon: Icon(
              app.busy ? Icons.stop_circle_outlined : Icons.auto_awesome,
            ),
            label: Text(
              app.busy
                  ? 'Dừng nhận diện'
                  : 'Nhận diện ${app.documents.length} ảnh',
            ),
          ),
        ),
      ],
    ),
  );

  Widget _statusCard({bool large = false}) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Row(
        children: [
          AssistantFace(state: app.assistant, size: large ? 104 : 68),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  stateLabel,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  'Hoạt động ngoại tuyến',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  widget.ble?.connected == true
                      ? 'Trợ lý đã kết nối'
                      : 'Có thể đọc chữ khi chưa kết nối trợ lý',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );

  Widget _photos() => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      _statusCard(),
      const SizedBox(height: 24),
      Row(
        children: [
          Expanded(
            child: Text(
              'Đọc chữ từ ảnh',
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          Text(
            '${app.documents.length}/10',
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ],
      ),
      const SizedBox(height: 8),
      Text(app.message),
      const SizedBox(height: 18),
      Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: app.busy || app.importing || app.picking
                  ? null
                  : () => app.pick(camera: true),
              icon: const Icon(Icons.camera_alt_outlined),
              label: const Text('Chụp ảnh'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: app.busy || app.importing || app.picking
                  ? null
                  : () => app.pick(camera: false),
              icon: const Icon(Icons.add_photo_alternate_outlined),
              label: const Text('Chọn ảnh'),
            ),
          ),
        ],
      ),
      if (app.importing)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: LinearProgressIndicator(),
        ),
      const SizedBox(height: 16),
      SegmentedButton<bool>(
        segments: const [
          ButtonSegment(
            value: true,
            icon: Icon(Icons.subject),
            label: Text('Nhiều dòng'),
          ),
          ButtonSegment(
            value: false,
            icon: Icon(Icons.short_text),
            label: Text('Một dòng'),
          ),
        ],
        selected: {app.splitLines},
        onSelectionChanged: app.busy
            ? null
            : (values) => app.setSplit(values.single),
      ),
      const SizedBox(height: 20),
      if (app.selected == null)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(
              children: [
                Icon(
                  Icons.document_scanner_outlined,
                  size: 72,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 16),
                const Text(
                  'Biến nét chữ thành văn bản',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Chụp thẳng trang giấy, tránh bóng và đặt chữ đúng chiều. Mỗi lượt tối đa 10 ảnh.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),
                TextButton.icon(
                  onPressed: app.importing ? null : app.addSamples,
                  icon: const Icon(Icons.play_circle_outline),
                  label: const Text('Thử với ảnh mẫu'),
                ),
              ],
            ),
          ),
        )
      else ...[
        _imagePreview(app.selected!),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: Text(
                app.selected!.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(
              tooltip: 'Xoay ảnh 90°',
              onPressed: app.busy || app.importing ? null : app.rotateSelected,
              icon: const Icon(Icons.rotate_right),
            ),
            IconButton(
              tooltip: 'Xóa ảnh',
              onPressed: app.busy || app.importing ? null : app.removeSelected,
              icon: const Icon(Icons.delete_outline),
            ),
          ],
        ),
        SizedBox(
          height: 96,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: app.documents.length,
            separatorBuilder: (_, _) => const SizedBox(width: 10),
            itemBuilder: (context, index) {
              final item = app.documents[index];
              return Semantics(
                label: 'Ảnh ${index + 1}, ${_documentStatus(item)}',
                selected: app.selectedIndex == index,
                child: InkWell(
                  onTap: () => app.select(index),
                  borderRadius: BorderRadius.circular(14),
                  child: Container(
                    width: 84,
                    padding: const EdgeInsets.all(3),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        width: 2,
                        color: app.selectedIndex == index
                            ? Theme.of(context).colorScheme.primary
                            : Colors.transparent,
                      ),
                    ),
                    child: Column(
                      children: [
                        Expanded(
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(10),
                            child: Image.file(
                              File(item.path),
                              width: 78,
                              fit: BoxFit.cover,
                              cacheWidth: 160,
                              errorBuilder: (_, _, _) =>
                                  const Icon(Icons.broken_image_outlined),
                            ),
                          ),
                        ),
                        Text(
                          '${index + 1} · ${_documentStatus(item)}',
                          maxLines: 1,
                          style: const TextStyle(fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
      const SizedBox(height: 12),
      const Text(
        'Chữ quá nhỏ hoặc trang có nhiều cột có thể cần chụp từng vùng riêng.',
        style: TextStyle(fontSize: 12),
      ),
    ],
  );

  Widget _imagePreview(Document item) => ClipRRect(
    borderRadius: BorderRadius.circular(20),
    child: ColoredBox(
      color: Theme.of(context).colorScheme.surfaceContainerHigh,
      child: SizedBox(
        height: 300,
        width: double.infinity,
        child: GestureDetector(
          onTap: () => showDialog<void>(
            context: context,
            builder: (context) => Dialog.fullscreen(
              child: SafeArea(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: InteractiveViewer(
                        maxScale: 8,
                        child: RotatedBox(
                          quarterTurns: item.rotation,
                          child: Image.file(
                            File(item.path),
                            fit: BoxFit.contain,
                            errorBuilder: (_, _, _) =>
                                const Center(child: Text('Không mở được ảnh.')),
                          ),
                        ),
                      ),
                    ),
                    Align(
                      alignment: Alignment.topRight,
                      child: IconButton.filledTonal(
                        tooltip: 'Đóng ảnh',
                        onPressed: () => Navigator.pop(context),
                        icon: const Icon(Icons.close),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          child: RotatedBox(
            quarterTurns: item.rotation,
            child: Image.file(
              File(item.path),
              fit: BoxFit.contain,
              cacheWidth: 1000,
              errorBuilder: (_, _, _) =>
                  const Center(child: Text('Không mở được ảnh. Hãy chọn lại.')),
            ),
          ),
        ),
      ),
    ),
  );

  String _documentStatus(Document document) => switch (document.status) {
    DocumentStatus.ready => 'Sẵn sàng',
    DocumentStatus.processing => 'Đang đọc',
    DocumentStatus.done => 'Xong',
    DocumentStatus.error => 'Lỗi',
    DocumentStatus.cancelled => 'Đã dừng',
  };

  Widget _results() {
    final item = app.selected;
    if (item == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(28),
          child: Text('Chụp hoặc chọn ảnh để bắt đầu đọc chữ.'),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          'Văn bản của bạn',
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          key: ValueKey(
            'selection_${app.selectedIndex}_${app.documents.length}',
          ),
          initialValue: app.selectedIndex,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Ảnh'),
          items: [
            for (var i = 0; i < app.documents.length; i++)
              DropdownMenuItem(
                value: i,
                child: Text(
                  '${i + 1}. ${app.documents[i].name}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: (index) {
            if (index != null) app.select(index);
          },
        ),
        const SizedBox(height: 12),
        Text(
          _documentStatus(item),
          style: TextStyle(color: Theme.of(context).colorScheme.primary),
        ),
        if (item.error.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              item.error,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        const SizedBox(height: 12),
        DocumentEditor(
          document: item,
          enabled: !app.busy,
          onChanged: (text) => app.edit(item.id, text),
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 10,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: item.text.isEmpty ? null : () => _copy(item.text),
              icon: const Icon(Icons.copy_outlined),
              label: const Text('Sao chép ảnh này'),
            ),
            OutlinedButton.icon(
              onPressed: app.allText.isEmpty ? null : () => _copy(app.allText),
              icon: const Icon(Icons.copy_all_outlined),
              label: const Text('Sao chép tất cả'),
            ),
            Builder(
              builder: (buttonContext) => FilledButton.tonalIcon(
                onPressed: app.allText.isEmpty
                    ? null
                    : () => _export(buttonContext),
                icon: const Icon(Icons.share_outlined),
                label: const Text('Lưu / chia sẻ TXT'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Text(app.message),
      ],
    );
  }

  Future<void> _copy(String text) async {
    try {
      await Clipboard.setData(ClipboardData(text: text));
      _notice('Đã sao chép văn bản.');
    } catch (_) {
      _notice('Không sao chép được. Thử lại.');
    }
  }

  Future<void> _export(BuildContext buttonContext) async {
    final box = buttonContext.findRenderObject()! as RenderBox;
    final origin = box.localToGlobal(Offset.zero) & box.size;
    final text = app.allText;
    try {
      await app.flush();
      final folder = await getTemporaryDirectory();
      final file = File(
        '${folder.path}/VietOCR_${DateTime.now().millisecondsSinceEpoch}.txt',
      );
      await file.writeAsString(text, flush: true);
      if (!mounted) return;
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile(file.path, mimeType: 'text/plain')],
          title: 'Văn bản VietOCR',
          sharePositionOrigin: origin,
        ),
      );
    } catch (error) {
      _notice('Không xuất được văn bản: ${AppController.readableError(error)}');
    }
  }

  Widget _assistant() {
    final ble = widget.ble;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        _statusCard(large: true),
        const SizedBox(height: 24),
        Text(
          'Bạn đồng hành',
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        const Text(
          'Trợ lý thức dậy khi kết nối, báo đã nhận ảnh, hiển thị tiến trình và mỉm cười khi xong.',
        ),
        const SizedBox(height: 20),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      ble?.connected == true
                          ? Icons.bluetooth_connected
                          : Icons.bluetooth,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Bluetooth',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                SelectableText(ble?.message ?? 'Bluetooth chưa khả dụng.'),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    OutlinedButton.icon(
                      onPressed: ble?.enableBluetooth,
                      icon: const Icon(Icons.power_settings_new),
                      label: const Text('Bật Bluetooth'),
                    ),
                    FilledButton.icon(
                      onPressed: ble == null || ble.connected || ble.connecting
                          ? null
                          : ble.scanning
                          ? ble.stopScan
                          : ble.scan,
                      icon: Icon(
                        ble?.scanning == true ? Icons.stop : Icons.search,
                      ),
                      label: Text(
                        ble?.scanning == true ? 'Dừng tìm' : 'Tìm trợ lý',
                      ),
                    ),
                    if (ble != null &&
                        (ble.connected ||
                            ble.connecting ||
                            ble.selectedId.isNotEmpty))
                      TextButton(
                        onPressed: ble.forget,
                        child: const Text('Ngắt kết nối'),
                      ),
                  ],
                ),
                if (ble?.scanning == true || ble?.connecting == true)
                  const Padding(
                    padding: EdgeInsets.only(top: 16),
                    child: LinearProgressIndicator(),
                  ),
                if (ble != null && !ble.connected)
                  ...ble.devices.values.map(
                    (device) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        device.name.isEmpty ? 'VietOCR Assistant' : device.name,
                      ),
                      subtitle: Text('Tín hiệu ${device.rssi} dBm'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: ble.connecting
                          ? null
                          : () => ble.connect(device.id, device.name),
                    ),
                  ),
                if (ble?.connected == true) ...[
                  const Divider(height: 28),
                  Wrap(
                    spacing: 8,
                    children: [
                      OutlinedButton.icon(
                        onPressed: app.busy ? null : () => ble!.command('BEEP'),
                        icon: const Icon(Icons.volume_up_outlined),
                        label: const Text('Thử còi'),
                      ),
                      OutlinedButton(
                        onPressed: () => ble!.command('MUTE ON'),
                        child: const Text('Tắt tiếng'),
                      ),
                      OutlinedButton(
                        onPressed: () => ble!.command('MUTE OFF'),
                        child: const Text('Bật tiếng'),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        const Text(
          'Cấp nguồn cho ESP32-S3 và nạp firmware BLE trong thư mục pbl4, rồi tìm trợ lý trong ứng dụng.',
        ),
        const SizedBox(height: 12),
        const Text(
          'Ảnh và văn bản được lưu trên điện thoại. OCR hoạt động khi tắt Wi-Fi và dữ liệu di động.',
          style: TextStyle(fontSize: 12),
        ),
      ],
    );
  }
}

class DocumentEditor extends StatefulWidget {
  const DocumentEditor({
    super.key,
    required this.document,
    required this.enabled,
    required this.onChanged,
  });
  final Document document;
  final bool enabled;
  final ValueChanged<String> onChanged;
  @override
  State<DocumentEditor> createState() => _DocumentEditorState();
}

class _DocumentEditorState extends State<DocumentEditor> {
  late final TextEditingController text;
  @override
  void initState() {
    super.initState();
    text = TextEditingController(text: widget.document.text);
  }

  @override
  void didUpdateWidget(covariant DocumentEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (text.text != widget.document.text) {
      text.value = TextEditingValue(
        text: widget.document.text,
        selection: TextSelection.collapsed(offset: widget.document.text.length),
      );
    }
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
    controller: text,
    onChanged: widget.onChanged,
    readOnly: !widget.enabled,
    minLines: 10,
    maxLines: 24,
    decoration: const InputDecoration(
      hintText:
          'Văn bản sẽ xuất hiện sau khi nhận diện. Bạn có thể sửa trực tiếp tại đây.',
    ),
    style: const TextStyle(fontSize: 17, height: 1.6),
  );
}
