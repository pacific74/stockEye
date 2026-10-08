import 'package:flutter/material.dart';

/// 앱 버전 — GitHub Actions 빌드 때 --dart-define 으로 넣는다 (app.yml)
///   APP_BUILD = 빌드 번호 (Actions 실행 번호, 앱·웹 같은 번호)
///   APP_TIME  = 빌드 시각 (한국 시간, 예: 10/08 17:30)
///   APP_COMMIT = 커밋 앞 7자리
/// PC 에서 직접 실행하면 값이 없어 '개발 빌드' 로 표시.
const appVersion = '0.1.0';
const appBuild = String.fromEnvironment('APP_BUILD');
const appBuildTime = String.fromEnvironment('APP_TIME');
const appCommit = String.fromEnvironment('APP_COMMIT');

/// 예: "v0.1.0 · 빌드 #57 · 10/08 17:30"
String get versionText {
  if (appBuild.isEmpty) return 'v$appVersion · 개발 빌드';
  return [
    'v$appVersion',
    '빌드 #$appBuild',
    if (appBuildTime.isNotEmpty) appBuildTime,
  ].join(' · ');
}

/// 화면 맨 아래 작은 버전 줄 (하단 메뉴 밑)
class VersionFooter extends StatelessWidget {
  const VersionFooter({super.key});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      color: cs.surfaceContainer,
      padding: EdgeInsets.only(top: 1, bottom: 2 + MediaQuery.of(context).padding.bottom),
      child: Text(versionText,
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 10, color: cs.onSurfaceVariant.withValues(alpha: 0.8))),
    );
  }
}
