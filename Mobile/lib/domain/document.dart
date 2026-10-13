enum DocumentStatus { ready, processing, done, error, cancelled }

enum AssistantState { awake, received, processing, done, error, sleeping }

class Document {
  Document({
    required this.id,
    required this.path,
    required this.name,
    this.text = '',
    this.status = DocumentStatus.ready,
    this.error = '',
    this.rotation = 0,
  });
  final String id, path, name;
  String text, error;
  DocumentStatus status;
  int rotation;

  Map<String, dynamic> toJson() => {
    'id': id,
    'path': path,
    'name': name,
    'text': text,
    'status': status.name,
    'error': error,
    'rotation': rotation,
  };

  factory Document.fromJson(Map<String, dynamic> json) {
    var status = DocumentStatus.values.firstWhere(
      (value) => value.name == json['status'],
      orElse: () => DocumentStatus.ready,
    );
    if (status == DocumentStatus.processing) status = DocumentStatus.cancelled;
    return Document(
      id: json['id'] as String,
      path: json['path'] as String,
      name: json['name'] as String,
      text: json['text'] as String? ?? '',
      error: json['error'] as String? ?? '',
      rotation: json['rotation'] as int? ?? 0,
      status: status,
    );
  }
}
