enum DocumentStatus { ready, processing, done, error, cancelled }

class Document {
  Document({
    required this.id,
    required this.path,
    required this.name,
    this.text = '',
    this.status = DocumentStatus.ready,
    this.error = '',
    this.rotation = 0,
    this.included = true,
    this.jobId,
    this.lens,
    this.hasPipeline = false,
    this.customQuad,
  });
  final String id, path, name;
  String text, error;
  DocumentStatus status;
  int rotation;
  bool included;
  String? jobId;
  Map<String, dynamic>? lens;
  bool hasPipeline;
  List<List<double>>? customQuad;
  bool get canSend => status != DocumentStatus.processing;

  Map<String, dynamic> toJson() => {
    'id': id,
    'path': path,
    'name': name,
    'text': text,
    'status': status.name,
    'error': error,
    'rotation': rotation,
    'included': included,
    if (jobId != null) 'jobId': jobId,
    if (lens != null) 'lens': lens,
    if (hasPipeline) 'hasPipeline': hasPipeline,
    if (customQuad != null) 'customQuad': customQuad,
  };

  factory Document.fromJson(Map<String, dynamic> json) {
    var status = DocumentStatus.values.firstWhere(
      (value) => value.name == json['status'],
      orElse: () => DocumentStatus.ready,
    );
    if (status == DocumentStatus.processing) status = DocumentStatus.cancelled;
    List<List<double>>? parsedQuad;
    final rawQuad = json['customQuad'];
    if (rawQuad is List && rawQuad.length == 4) {
      final pts = <List<double>>[];
      for (final p in rawQuad) {
        if (p is List && p.length >= 2 && p[0] is num && p[1] is num) {
          pts.add([(p[0] as num).toDouble(), (p[1] as num).toDouble()]);
        }
      }
      if (pts.length == 4) parsedQuad = pts;
    }
    return Document(
      id: json['id'] as String,
      path: json['path'] as String,
      name: json['name'] as String,
      text: json['text'] as String? ?? '',
      error: json['error'] as String? ?? '',
      rotation: json['rotation'] as int? ?? 0,
      included: json['included'] as bool? ?? true,
      status: status,
      jobId: json['jobId'] as String?,
      lens: json['lens'] is Map
          ? Map<String, dynamic>.from(json['lens'] as Map)
          : null,
      hasPipeline: json['hasPipeline'] as bool? ?? false,
      customQuad: parsedQuad,
    );
  }
}
