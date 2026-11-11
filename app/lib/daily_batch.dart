import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// (관리자) 일배치 실행 버튼 (2026-11-12) — GitHub 예약 실행이 몇 시간씩 늦어서, 메뉴에서 바로 시작시킴
///   GitHub Actions 'daily-batch' 를 workflow_dispatch 로 호출 (예약과 달리 즉시 시작)
///   토큰은 코드에 넣지 않고 처음 누를 때 한 번 붙여넣어 '이 기기에만' 저장 (fine-grained token · 저장소 stockEye · Actions: Read and write)
///   이미 발행된 날이면 분석은 건너뛰고 1분 안에 끝남 (중복 안전)
const _repo = 'pacific74/stockEye';
const _workflow = 'daily.yml';
const _prefKey = 'gh_dispatch_token';

Future<String?> _loadToken() async {
  try {
    return (await SharedPreferences.getInstance()).getString(_prefKey);
  } catch (_) {
    return null;
  }
}

Future<void> _saveToken(String? t) async {
  try {
    final p = await SharedPreferences.getInstance();
    if (t == null || t.isEmpty) {
      await p.remove(_prefKey);
    } else {
      await p.setString(_prefKey, t);
    }
  } catch (_) {}
}

Future<String?> _askToken(BuildContext context) {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('GitHub 토큰 입력'),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('처음 한 번만 입력해요. 이 기기에만 저장되고 다른 곳으로 보내지 않아요.\n\n'
            'GitHub → Settings → Developer settings → Fine-grained tokens\n'
            '· 저장소: stockEye 만 선택\n'
            '· 권한: Actions → Read and write', style: TextStyle(fontSize: 12.5)),
        const SizedBox(height: 10),
        TextField(controller: c, obscureText: true, autofocus: true, decoration: const InputDecoration(hintText: 'github_pat_...')),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('저장')),
      ],
    ),
  );
}

void _toast(BuildContext context, String msg) {
  if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 6)));
}

/// 메뉴 → '일배치 실행'
Future<void> runDailyBatch(BuildContext context) async {
  var token = await _loadToken();
  if (token == null || token.isEmpty) {
    if (!context.mounted) return;
    token = await _askToken(context);
    if (token == null || token.isEmpty) return;
    await _saveToken(token);
  }
  if (!context.mounted) return;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('일배치를 지금 실행할까요?'),
      content: const Text('GitHub 에서 수집·분석·발행이 시작돼요 (보통 10~15분).\n이미 발행된 날이면 분석은 건너뛰고 금방 끝나요.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('실행')),
      ],
    ),
  );
  if (ok != true) return;
  try {
    final r = await http
        .post(Uri.parse('https://api.github.com/repos/$_repo/actions/workflows/$_workflow/dispatches'),
            headers: {'Authorization': 'Bearer $token', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'},
            body: jsonEncode({'ref': 'main'}))
        .timeout(const Duration(seconds: 20));
    if (r.statusCode == 204) {
      _toast(context, '일배치를 시작했어요. GitHub Actions 에서 진행 상황을 볼 수 있어요 (보통 10~15분)');
    } else if (r.statusCode == 401 || r.statusCode == 403 || r.statusCode == 404) {
      if (r.statusCode == 401) await _saveToken(null);
      _toast(context, '실행 실패 (${r.statusCode}) — 토큰 권한(Actions 쓰기)·저장소 선택을 확인해 주세요${r.statusCode == 401 ? ' · 저장된 토큰을 지웠어요, 다시 눌러 입력' : ''}');
    } else {
      _toast(context, '실행 실패 (${r.statusCode}) ${r.body.length > 120 ? r.body.substring(0, 120) : r.body}');
    }
  } catch (e) {
    _toast(context, '실행 요청 실패: $e');
  }
}

/// 메뉴 → '일배치 토큰 지우기'
Future<void> clearDailyBatchToken(BuildContext context) async {
  await _saveToken(null);
  _toast(context, '저장된 GitHub 토큰을 지웠어요');
}
