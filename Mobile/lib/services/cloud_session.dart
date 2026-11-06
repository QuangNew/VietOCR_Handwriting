import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'server_credentials.dart';
import 'vietocr_remote.dart';

class EncryptedSessionStorage extends LocalStorage {
  const EncryptedSessionStorage();
  @override
  Future<void> initialize() async {}
  @override
  Future<bool> hasAccessToken() async => (await accessToken()) != null;
  @override
  Future<String?> accessToken() async {
    final value = await ServerCredentials.read();
    return value.startsWith('{') ? value : null;
  }

  @override
  Future<void> persistSession(String value) => ServerCredentials.write(value);
  @override
  Future<void> removePersistedSession() => ServerCredentials.write('');
}

class CloudSession extends ChangeNotifier {
  CloudSession._();
  static final instance = CloudSession._();
  bool _ready = false;
  Future<void>? _initializing;
  SupabaseClient get client => Supabase.instance.client;
  String? get userId => _ready ? client.auth.currentUser?.id : null;
  String? get email => _ready ? client.auth.currentUser?.email : null;
  Future<void> initialize() => _initializing ??= _initialize();
  Future<void> _initialize() async {
    final config =
        jsonDecode(await rootBundle.loadString('assets/config/supabase.json'))
            as Map<String, dynamic>;
    await Supabase.initialize(
      url: config['url'] as String,
      publishableKey: config['publishableKey'] as String,
      authOptions: const FlutterAuthClientOptions(
        authFlowType: AuthFlowType.pkce,
        localStorage: EncryptedSessionStorage(),
      ),
      debug: false,
    );
    _ready = true;
    client.auth.onAuthStateChange.listen(
      (_) => notifyListeners(),
      onError: (_) => notifyListeners(),
    );
    notifyListeners();
  }

  Future<void> login() async {
    await initialize();
    final opened = await client.auth.signInWithOAuth(
      OAuthProvider.google,
      redirectTo: 'vn.pbl4.vietocr://auth/callback',
      authScreenLaunchMode: LaunchMode.externalApplication,
      queryParams: {'prompt': 'select_account'},
    );
    if (!opened) {
      throw StateError('Không mở được trình duyệt đăng nhập Google.');
    }
  }

  Future<String> accessToken() async {
    await initialize();
    var session = client.auth.currentSession;
    if (session == null) {
      throw const RemoteOcrException(
        'Đăng nhập Google trong mục OCR Server trước khi nhận diện.',
        status: 401,
      );
    }
    if ((session.expiresAt ?? 0) <=
        DateTime.now().millisecondsSinceEpoch ~/ 1000 + 90) {
      session = (await client.auth.refreshSession()).session;
    }
    if (session == null) {
      throw const RemoteOcrException(
        'Phiên Google đã hết hạn. Vui lòng đăng nhập lại.',
        status: 401,
      );
    }
    return session.accessToken;
  }

  Future<void> logout() async {
    if (!_ready) return;
    try {
      await client.auth.signOut(scope: SignOutScope.local);
    } finally {
      await ServerCredentials.write('');
    }
  }
}
