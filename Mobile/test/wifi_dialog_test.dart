import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vietocr_mobile/services/ble_assistant.dart';
import 'package:vietocr_mobile/services/wifi_camera.dart';
import 'package:vietocr_mobile/ui/wifi_dialog.dart';
import 'ble_connection_test.dart' show FakeRadio;

class DialogAssistant extends BleAssistant {
  DialogAssistant() : super(radioClient: FakeRadio()) {
    connected = true;
  }
  int reads = 0, scans = 0;
  @override
  Future<void> refreshWifiState() async {
    reads++;
    wifiState = const WifiState(
      state: 'ready',
      ssid: 'Home',
      savedSsid: 'Home',
      ip: '192.168.100.173',
    );
    notifyListeners();
  }

  @override
  Future<List<String>> scanWifi() async {
    scans++;
    return [];
  }
}

void main() {
  testWidgets(
    'Wi-Fi dialog auto-shows saved LAN and preserves an edited SSID',
    (tester) async {
      final assistant = DialogAssistant();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: WifiDialog(assistant: assistant)),
        ),
      );
      await tester.pump();
      expect(find.textContaining('192.168.100.173'), findsOneWidget);
      expect(
        find.textContaining('Mạng đã lưu trên ESP32: Home'),
        findsOneWidget,
      );
      expect(assistant.reads, 1);
      expect(assistant.scans, 0);
      await tester.enterText(find.byType(TextField).first, 'New network');
      await assistant.refreshWifiState();
      await tester.pump();
      expect(find.text('New network'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      assistant.dispose();
    },
  );
}
