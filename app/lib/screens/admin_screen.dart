import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/common.dart';

/// (관리자) 회원 관리: 가입 승인 / 거절 / 승인 취소
class AdminUsersScreen extends StatefulWidget {
  const AdminUsersScreen({super.key});

  @override
  State<AdminUsersScreen> createState() => _AdminUsersScreenState();
}

class _AdminUsersScreenState extends State<AdminUsersScreen> {
  late Future<List<Json>> _f = listUsers();
  final Set<String> _busy = {};

  void _reload() => setState(() => _f = listUsers());

  static const _label = {'pending': '승인 대기', 'approved': '승인됨', 'rejected': '거절됨'};
  static const Map<String, Color> _color = {'pending': Colors.amber, 'approved': Colors.green, 'rejected': Colors.redAccent};

  Future<void> _set(Json u, String status) async {
    final id = u['user_id'] as String;
    if (status != 'approved') {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(status == 'rejected' ? '가입을 거절할까요?' : '승인을 취소할까요?'),
          content: Text('${u['email']}\n이 회원은 앱 데이터를 볼 수 없게 됩니다.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('취소')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('확인')),
          ],
        ),
      );
      if (ok != true) return;
    }
    setState(() => _busy.add(id));
    try {
      final r = await setUserStatus(id, status);
      if (mounted && r['ok'] != true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${r['message']}')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      _busy.remove(id);
      _reload();
    }
  }

  String _date(dynamic v) {
    final s = '$v'.replaceFirst('T', ' ');
    return s.length >= 16 ? s.substring(0, 16) : s;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('회원 관리'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _reload),
      ]),
      body: Loader<List<Json>>(
        future: _f,
        onRetry: _reload,
        builder: (context, users) {
          final pending = users.where((u) => u['status'] == 'pending').length;
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text('전체 ${users.length}명 · 승인 대기 $pending명',
                    style: Theme.of(context).textTheme.titleSmall),
              ),
              ...users.map((u) {
                final st = u['status'] as String? ?? 'pending';
                final admin = u['is_admin'] == true;
                final busy = _busy.contains(u['user_id']);
                return Card(
                  child: ListTile(
                    title: Text('${u['email'] ?? '(이메일 없음)'}${admin ? '  ·  관리자' : ''}'),
                    subtitle: Row(children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                            color: (_color[st] ?? Colors.grey).withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(6)),
                        child: Text(_label[st] ?? st, style: TextStyle(color: _color[st], fontSize: 12)),
                      ),
                      const SizedBox(width: 8),
                      Expanded(child: Text('가입 ${_date(u['created_at'])}', overflow: TextOverflow.ellipsis)),
                    ]),
                    trailing: admin
                        ? null
                        : busy
                            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                            : Row(mainAxisSize: MainAxisSize.min, children: [
                                if (st != 'approved')
                                  FilledButton(onPressed: () => _set(u, 'approved'), child: const Text('승인')),
                                if (st == 'pending') const SizedBox(width: 6),
                                if (st == 'pending')
                                  OutlinedButton(onPressed: () => _set(u, 'rejected'), child: const Text('거절')),
                                if (st == 'approved')
                                  OutlinedButton(onPressed: () => _set(u, 'pending'), child: const Text('승인 취소')),
                              ]),
                  ),
                );
              }),
            ],
          );
        },
      ),
    );
  }
}

/// 홈 화면 맨 위: (관리자에게만) 승인 대기 알림
class PendingUsersBanner extends StatelessWidget {
  const PendingUsersBanner({super.key});

  @override
  Widget build(BuildContext context) {
    if (!useCloud || !isAdminUser) return const SizedBox.shrink();
    return FutureBuilder<List<Json>>(
      future: listUsers(),
      builder: (context, snap) {
        final n = (snap.data ?? const <Json>[]).where((u) => u['status'] == 'pending').length;
        if (n == 0) return const SizedBox.shrink();
        return Card(
          color: Colors.amber.withValues(alpha: 0.15),
          child: ListTile(
            dense: true,
            leading: const Icon(Icons.person_add_alt_1, color: Colors.amber),
            title: Text('가입 승인 대기 $n명'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AdminUsersScreen())),
          ),
        );
      },
    );
  }
}
