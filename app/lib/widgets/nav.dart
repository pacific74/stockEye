import 'package:flutter/material.dart';

import '../api.dart';
import '../version.dart';

/// 앱 전체 공통 이동: 하단 메뉴(어느 화면에서나) + 상단 로고(누르면 메인)
final ValueNotifier<int> tabIndex = ValueNotifier<int>(0); // 지금 선택된 하단 탭
final ValueNotifier<int> tabTap = ValueNotifier<int>(0); // 하단 탭을 누를 때마다 +1 (같은 탭 다시 눌러도 새로고침)
final ValueNotifier<String> candidateListKey = ValueNotifier<String>('v3'); // 후보 탭에서 처음 보여줄 목록

const navDestinations = [
  NavigationDestination(icon: Icon(Icons.home_outlined), label: '오늘'),
  NavigationDestination(icon: Icon(Icons.trending_up), label: '관심'),
  NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined), label: '보유'),
  NavigationDestination(icon: Icon(Icons.menu_book_outlined), label: '일지'),
  NavigationDestination(icon: Icon(Icons.history), label: '백테스트'),
];

/// 백테스트 탭은 관리자만 (PC 서버 모드는 혼자 쓰므로 항상 보임)
bool get canSeeBacktest => !useCloud || isAdminUser;

/// 지금 사용자에게 보이는 하단 메뉴
List<NavigationDestination> get visibleDestinations =>
    canSeeBacktest ? navDestinations : navDestinations.sublist(0, 4);

/// 하단 탭으로 이동 (열려 있는 하위 화면은 모두 닫고)
void goTab(BuildContext context, int i, {String? list}) {
  if (i >= visibleDestinations.length) i = 0;
  Navigator.of(context).popUntil((r) => r.isFirst);
  if (list != null) candidateListKey.value = list;
  tabIndex.value = i;
  tabTap.value++;
}

/// 모든 화면 아래에 붙는 하단 메뉴 (+ 앱 버전)
class MainNavBar extends StatelessWidget {
  const MainNavBar({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<int>(
      valueListenable: tabIndex,
      builder: (context, i, _) {
        final items = visibleDestinations;
        // 하단 메뉴 + 그 밑에 앱 버전 한 줄 (폰 하단 여백은 버전 줄이 맡음)
        return Column(mainAxisSize: MainAxisSize.min, children: [
          MediaQuery.removePadding(
            context: context,
            removeBottom: true,
            child: NavigationBar(
              selectedIndex: i < items.length ? i : 0,
              onDestinationSelected: (n) => goTab(context, n),
              destinations: items,
            ),
          ),
          const VersionFooter(),
        ]);
      },
    );
  }
}

/// 상단 제목: 로고 + 글자, 누르면 메인(오늘) 화면으로
class LogoTitle extends StatelessWidget {
  const LogoTitle(this.title, {super.key, this.bold = false});
  final String title;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => goTab(context, 0),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.asset('assets/icon/logo_256.png', width: 26, height: 26),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(title,
                overflow: TextOverflow.ellipsis,
                style: bold ? const TextStyle(fontWeight: FontWeight.bold) : null),
          ),
        ]),
      ),
    );
  }
}
