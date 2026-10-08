import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../api.dart';
import '../screens/admin_screen.dart';
import '../screens/help_screen.dart';
import '../screens/notify_screen.dart';
import '../screens/search_screen.dart';
import '../version.dart';

/// 모든 화면 상단 오른쪽 공통 버튼: [검색] [새로고침] [⋮ 메뉴]
///   AppBar(actions: topActions(context, onRefresh: _reload))
List<Widget> topActions(BuildContext context, {VoidCallback? onRefresh, bool search = true, List<Widget> extra = const []}) => [
      ...extra,
      if (search)
        IconButton(
          tooltip: '종목 검색',
          icon: const Icon(Icons.search),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SearchScreen())),
        ),
      if (onRefresh != null) IconButton(tooltip: '새로고침', icon: const Icon(Icons.refresh), onPressed: onRefresh),
      const AppMenu(),
    ];

/// ⋮ 메뉴: 이용 안내 · 알림 설정 · (관리자) 회원 관리 · 로그아웃
class AppMenu extends StatelessWidget {
  const AppMenu({super.key});

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      tooltip: '메뉴',
      onSelected: (v) async {
        Widget? page;
        switch (v) {
          case 'help':
            page = const HelpScreen();
          case 'notify':
            page = const NotifySettingsScreen();
          case 'users':
            page = const AdminUsersScreen();
          case 'logout':
            Navigator.of(context).popUntil((r) => r.isFirst);
            await Supabase.instance.client.auth.signOut();
            return;
        }
        if (page != null && context.mounted) {
          final p = page;
          Navigator.push(context, MaterialPageRoute(builder: (_) => p));
        }
      },
      itemBuilder: (_) => [
        if (useCloud)
          PopupMenuItem(
              enabled: false,
              child: Text(Supabase.instance.client.auth.currentUser?.email ?? '',
                  style: Theme.of(context).textTheme.bodySmall)),
        const PopupMenuItem(value: 'help', child: Text('이용 안내')),
        if (useCloud) const PopupMenuItem(value: 'notify', child: Text('알림 설정')),
        if (useCloud && isAdminUser) const PopupMenuItem(value: 'users', child: Text('회원 관리')),
        if (useCloud) const PopupMenuItem(value: 'logout', child: Text('로그아웃')),
        const PopupMenuDivider(),
        PopupMenuItem(enabled: false, child: Text(versionText, style: Theme.of(context).textTheme.bodySmall)),
      ],
    );
  }
}
