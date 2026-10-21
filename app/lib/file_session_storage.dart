import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

/// 로그인 유지를 파일로 저장 — 폰의 shared_preferences 플러그인이 깨진 빌드에서도 [로그아웃 전까지 로그인 유지]
///   (2026-10-22) shared_preferences 오류로 로그인 저장 없이 시작하던 것(앱을 켤 때마다 로그인) 대신 쓴다.
///   앱 전용 폴더(다른 앱은 못 읽음)의 작은 파일 하나. 로그아웃하면 지움.
class FileSessionStorage extends LocalStorage {
  FileSessionStorage();

  File? _file;

  @override
  Future<void> initialize() async {
    final dir = await getApplicationSupportDirectory();
    _file = File('${dir.path}/stockeye_session.json');
  }

  @override
  Future<bool> hasAccessToken() async => (await accessToken()) != null;

  @override
  Future<String?> accessToken() async {
    try {
      final f = _file;
      if (f == null || !await f.exists()) return null;
      final s = await f.readAsString();
      return s.isEmpty ? null : s;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> persistSession(String persistSessionString) async {
    try {
      await _file?.writeAsString(persistSessionString, flush: true);
    } catch (_) {}
  }

  @override
  Future<void> removePersistedSession() async {
    try {
      final f = _file;
      if (f != null && await f.exists()) await f.delete();
    } catch (_) {}
  }
}
