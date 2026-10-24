import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../voice.dart';
import '../widgets/nav.dart';
import '../widgets/top_actions.dart';

/// 내 휴대폰 알림 설정 (ntfy 앱 토픽)
///  - 승인되면 알림 / 매일 저녁 리포트 요약 / 내 보유종목 경고(손절·목표·확인 필요)
class NotifySettingsScreen extends StatefulWidget {
  const NotifySettingsScreen({super.key, this.showNav = true});
  final bool showNav; // 승인 대기 화면에서 열 때는 하단 메뉴 없음

  @override
  State<NotifySettingsScreen> createState() => _NotifySettingsScreenState();
}

class _NotifySettingsScreenState extends State<NotifySettingsScreen> {
  final _topic = TextEditingController();
  bool _daily = true;
  bool _holdings = true;
  bool _signals = false;
  bool _loading = true;
  bool _busy = false;
  bool _saved = false;
  bool _voice = true; // 당일매매 음성 안내 (이 기기)

  static String _randomTopic() {
    const chars = 'abcdefghijkmnpqrstuvwxyz23456789';
    final r = Random.secure();
    return 'stockeye-${List.generate(10, (_) => chars[r.nextInt(chars.length)]).join()}';
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final v = await VoiceAlert.enabled();
    if (mounted) setState(() => _voice = v);
    Json? p;
    try {
      p = await myProfile();
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      final t = p?['ntfy_topic'] as String?;
      _saved = t != null && t.isNotEmpty;
      _topic.text = _saved ? t! : _randomTopic();
      _daily = p?['notify_daily'] as bool? ?? true;
      _holdings = p?['notify_holdings'] as bool? ?? true;
      _signals = p?['notify_signals'] as bool? ?? false;
      _loading = false;
    });
  }

  void _snack(String m) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _save({bool off = false}) async {
    setState(() => _busy = true);
    try {
      await saveMyNotify(off ? '' : _topic.text.trim(), _daily, _holdings, _signals);
      setState(() => _saved = !off);
      _snack(off ? '알림을 껐습니다' : '저장했습니다');
    } catch (e) {
      _snack('$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _test() async {
    setState(() => _busy = true);
    try {
      final r = await sendTestNotify();
      _snack('${r['message']}');
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      bottomNavigationBar: widget.showNav ? const MainNavBar() : null,
      appBar: AppBar(
          title: widget.showNav ? const LogoTitle('알림 설정') : const Text('알림 설정'),
          actions: widget.showNav ? topActions(context) : null),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('휴대폰 알림 받는 법', style: t.titleSmall),
                    const SizedBox(height: 8),
                    const Text('1. 휴대폰에 ntfy 앱 설치 (Play 스토어 / App Store 에서 "ntfy" 검색)\n'
                        '2. 아래 [복사] → ntfy 앱의 ＋ 버튼 → 토픽 이름에 붙여넣기 → 구독\n'
                        '3. 여기서 [저장] → [테스트 알림] 으로 확인'),
                    const SizedBox(height: 8),
                    Text('토픽 이름은 비밀번호처럼 남에게 알려주지 마세요 (같은 이름을 구독하면 알림을 같이 받습니다).',
                        style: t.bodySmall),
                  ]),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _topic,
                decoration: InputDecoration(
                  labelText: '내 알림 토픽',
                  border: const OutlineInputBorder(),
                  suffixIcon: IconButton(
                    icon: const Icon(Icons.copy),
                    tooltip: '복사',
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: _topic.text.trim()));
                      _snack('복사했습니다. ntfy 앱에서 구독하세요');
                    },
                  ),
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                    onPressed: () => setState(() => _topic.text = _randomTopic()), child: const Text('새 이름 만들기')),
              ),
              SwitchListTile(
                value: _daily,
                onChanged: (v) => setState(() => _daily = v),
                title: const Text('매일 저녁 리포트 요약'),
                subtitle: const Text('시장 분위기 · 오늘의 TOP3'),
              ),
              SwitchListTile(
                value: _holdings,
                onChanged: (v) => setState(() => _holdings = v),
                title: const Text('내 보유종목 매도 예정일'),
                subtitle: const Text('V3 기준 매도 예정일이 3거래일 안이거나 도래하면 (저녁 점검)'),
              ),
              const ListTile(
                dense: true,
                leading: Icon(Icons.info_outline),
                title: Text('관리자 승인이 나면 이 토픽으로 바로 알려 드립니다'),
              ),
              if (isAdminUser) ...[
                const Divider(),
                SwitchListTile(
                  value: _voice,
                  onChanged: (v) async {
                    await VoiceAlert.setEnabled(v);
                    setState(() => _voice = v);
                  },
                  title: const Text('당일매매 음성 안내'),
                  subtitle: const Text('매수 조건 충족 → "매수발생"(여성) · 매도신호 → "매도발생"(남성). '
                      '이 기기에만 저장 · 앱이 켜져 있을 때만 울려요'),
                ),
                Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                  TextButton.icon(
                      onPressed: () => VoiceAlert.buy(force: true),
                      icon: const Icon(Icons.volume_up, size: 18),
                      label: const Text('매수발생 듣기')),
                  TextButton.icon(
                      onPressed: () => VoiceAlert.sell(force: true),
                      icon: const Icon(Icons.volume_up, size: 18),
                      label: const Text('매도발생 듣기')),
                ]),
              ],
              const SizedBox(height: 8),
              FilledButton(onPressed: _busy ? null : () => _save(), child: const Text('저장')),
              const SizedBox(height: 8),
              OutlinedButton(onPressed: _busy || !_saved ? null : _test, child: const Text('테스트 알림 보내기')),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                    '테스트는 PC·배치가 확인할 때 보내서 몇 분 걸리거나, ntfy 무료 한도 때문에 안 올 수도 있어요. '
                    '테스트 알림이 안 와도 정상일 수 있습니다 — 실제 알림(매수·급변·장마감 리포트)은 따로 정상으로 옵니다.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey)),
              ),
              if (_saved)
                TextButton(onPressed: _busy ? null : () => _save(off: true), child: const Text('알림 끄기')),
            ]),
    );
  }
}
