import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import 'version.dart';

/// 앱 업데이트 안내 (안드로이드 APK 만)
///   빌드할 때 웹 주소에 version.json({"build": N, "apk": "stockeye.apk"}) 을 같이 올린다 (app.yml).
///   앱을 켜면 그 파일을 읽어, 설치된 빌드 번호보다 크면 '새 버전' 안내 → [업데이트] 누르면 APK 다운로드.
///   웹은 새로고침이면 최신이라 안내하지 않음. PC 개발 빌드(빌드 번호 없음)도 안내하지 않음.
const _webUrl = String.fromEnvironment('WEB_URL');
bool _shown = false; // 앱 한 번 켤 때 한 번만

Future<void> checkForUpdate(BuildContext context) async {
  if (_shown || kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
  final mine = int.tryParse(appBuild);
  if (mine == null || _webUrl.isEmpty) return;
  final base = _webUrl.endsWith('/') ? _webUrl.substring(0, _webUrl.length - 1) : _webUrl;
  Map<String, dynamic> j;
  try {
    final r = await http
        .get(Uri.parse('$base/version.json?t=${DateTime.now().millisecondsSinceEpoch}'),
            headers: {'Cache-Control': 'no-cache'})
        .timeout(const Duration(seconds: 8));
    if (r.statusCode != 200) return;
    j = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
  } catch (_) {
    return; // 네트워크 문제면 조용히 넘어감
  }
  final latest = (j['build'] as num?)?.toInt();
  if (latest == null || latest <= mine || !context.mounted) return;
  _shown = true;
  final apk = '$base/${j['apk'] ?? 'stockeye.apk'}';
  final time = (j['time'] ?? '').toString();
  await showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('새 버전이 있어요'),
      content: Text('지금 설치된 버전: 빌드 #$mine\n'
          '새 버전: 빌드 #$latest${time.isEmpty ? '' : ' ($time)'}\n\n'
          '[업데이트]를 누르면 새 APK를 내려받아요. 다운로드가 끝나면 알림을 눌러 설치하세요. '
          '데이터와 로그인은 그대로 유지돼요.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('나중에')),
        FilledButton(
          onPressed: () async {
            Navigator.pop(ctx);
            var ok = false;
            try {
              ok = await launchUrl(Uri.parse(apk), mode: LaunchMode.externalApplication);
            } catch (_) {}
            if (!ok && context.mounted) {
              await Clipboard.setData(ClipboardData(text: apk));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('브라우저를 열 수 없어 주소를 복사했어요: $apk')));
              }
            }
          },
          child: const Text('업데이트'),
        ),
      ],
    ),
  );
}
