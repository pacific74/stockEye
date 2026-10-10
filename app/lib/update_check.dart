import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:ota_update/ota_update.dart';
import 'package:url_launcher/url_launcher.dart';

import 'version.dart';

/// 앱 업데이트 안내 (안드로이드 APK 만)
///   빌드할 때 웹 주소에 version.json({"build": N, "apk": "stockeye.apk"}) 을 같이 올린다 (app.yml).
///   앱을 켜면 그 파일을 읽어, 설치된 빌드 번호보다 크면 '새 버전' 안내 → [업데이트] 누르면 앱 안에서 APK 를 받고
///   바로 안드로이드 설치 화면을 연다 (ota_update). 안드로이드 보안상 마지막 [설치] 한 번은 직접 눌러야 함.
///   앱 안 다운로드가 안 되면 브라우저로 APK 주소를 연다.
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
          '[업데이트]를 누르면 새 버전을 내려받고 설치 화면이 바로 떠요. [설치]만 누르면 돼요. '
          '로그인과 데이터는 그대로 유지돼요.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('나중에')),
        FilledButton(
          onPressed: () {
            Navigator.pop(ctx);
            _install(context, apk, latest);
          },
          child: const Text('업데이트'),
        ),
      ],
    ),
  );
}

/// 앱 안에서 APK 받기 → 설치 화면. 진행률 창을 띄우고, 실패하면 브라우저로
Future<void> _install(BuildContext context, String apk, int build) async {
  final progress = ValueNotifier<String>('내려받는 중… 0%');
  var open = true;
  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => AlertDialog(
      title: Text('업데이트 (빌드 #$build)'),
      content: ValueListenableBuilder<String>(
        valueListenable: progress,
        builder: (_, v, __) => Row(children: [
          const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
          const SizedBox(width: 16),
          Expanded(child: Text(v)),
        ]),
      ),
    ),
  ).then((_) => open = false);
  void close() {
    if (open && context.mounted) Navigator.of(context, rootNavigator: true).pop();
    open = false;
  }

  try {
    await for (final e in OtaUpdate().execute(apk, destinationFilename: 'stockeye_$build.apk')) {
      if (e.status == OtaStatus.DOWNLOADING) {
        progress.value = '내려받는 중… ${e.value ?? 0}%';
      } else if (e.status == OtaStatus.INSTALLING) {
        progress.value = '설치 화면을 여는 중…';
        close();
        return; // 안드로이드 설치 화면에서 [설치] (처음 한 번은 '이 출처 허용'도)
      } else {
        throw Exception('${e.status.name} ${e.value ?? ''}');
      }
    }
    throw Exception('설치 단계 없이 끝남');
  } catch (_) {
    close();
    // 앱 안 설치가 안 되는 기기 → 브라우저로 내려받기
    var ok = false;
    try {
      ok = await launchUrl(Uri.parse(apk), mode: LaunchMode.externalApplication);
    } catch (_) {}
    if (!context.mounted) return;
    if (!ok) await Clipboard.setData(ClipboardData(text: apk));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok
            ? '앱 안에서 설치하지 못해 브라우저로 내려받아요. 다운로드 알림을 눌러 설치하세요.'
            : '업데이트를 열 수 없어 주소를 복사했어요: $apk')));
  }
}
