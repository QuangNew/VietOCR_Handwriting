/// Pins a network client to the account that created it, including refresh races.
/// This is a local privacy guard; the gateway still validates the actual JWT.
Future<String> Function() scopedToken({
  required String? owner,
  required String? Function() currentOwner,
  required Future<String> Function() fetch,
}) => () async {
  void check() {
    if (owner == null || currentOwner() != owner) {
      throw StateError('Phiên tài khoản đã thay đổi. Mở lại chức năng này.');
    }
  }

  check();
  final token = await fetch();
  check();
  return token;
};
