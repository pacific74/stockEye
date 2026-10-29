import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 최근 검색 종목 (최대 10개, 이 기기에만) — 앱 전용 폴더의 작은 파일 하나
///   shared_preferences 플러그인이 깨진 빌드가 있었어서 (2026-10-22 로그인 저장도 같은 이유로 파일) 파일로 저장. 실패해도 조용히 무시.
class RecentSearch {
  static const max = 10;
  static List<Map<String, String>>? _cache;

  static Future<File?> _file() async {
    try {
      final dir = await getApplicationSupportDirectory();
      return File('${dir.path}/stockeye_recent_search.json');
    } catch (_) {
      return null;
    }
  }

  /// 최신순. 못 읽으면 빈 목록
  static Future<List<Map<String, String>>> load() async {
    if (_cache != null) return List.of(_cache!);
    final out = <Map<String, String>>[];
    try {
      final f = await _file();
      if (f != null && await f.exists()) {
        final raw = jsonDecode(await f.readAsString());
        if (raw is List) {
          for (final e in raw) {
            if (e is Map && '${e['code']}'.isNotEmpty && e['code'] != null) {
              out.add({'code': '${e['code']}', 'name': '${e['name'] ?? e['code']}', 'market': '${e['market'] ?? ''}'});
            }
          }
        }
      }
    } catch (_) {}
    _cache = out.take(max).toList();
    return List.of(_cache!);
  }

  static Future<void> _save(List<Map<String, String>> rows) async {
    _cache = rows.take(max).toList();
    try {
      final f = await _file();
      await f?.writeAsString(jsonEncode(_cache), flush: true);
    } catch (_) {}
  }

  /// 종목을 맨 위로 (이미 있으면 옮김, 10개 넘으면 오래된 것 삭제)
  static Future<void> add(Map<String, dynamic> stock) async {
    final code = '${stock['code'] ?? ''}';
    if (code.isEmpty) return;
    final rows = await load();
    rows.removeWhere((r) => r['code'] == code);
    rows.insert(0, {'code': code, 'name': '${stock['name'] ?? code}', 'market': '${stock['market'] ?? ''}'});
    await _save(rows);
  }

  static Future<void> remove(String code) async {
    final rows = await load();
    rows.removeWhere((r) => r['code'] == code);
    await _save(rows);
  }

  static Future<void> clear() => _save([]);
}
