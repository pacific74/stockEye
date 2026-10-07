import 'package:flutter/material.dart';

/// 앱 전체 공통 이동: 하단 메뉴(어느 화면에서나) + 상단 로고(누르면 메인)
final ValueNotifier<int> tabIndex = ValueNotifier<int>(0); // 지금 선택된 하단 탭
final ValueNotifier<int> tabTap = ValueNotifier<int>(0); // 하단 탭을 누를 때마다 +1 (같은 탭 다시 눌러도 새로고침)
final ValueNotifier<String> candidateListKey = ValueNotifier<String>('overall'); // 후보 탭에서 처음 보여줄 목록

const navDestinations = [
  NavigationDestination(icon: Icon(Icons.home_outlined), label: '오늘'),
  NavigationDestination(icon: Icon(Icons.trending_up), label: '후보'),
  NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined), label: '보유'),
  NavigationDestination(icon: Icon(Icons.menu_book_outlined), label: '일지'),
  NavigationDestination(icon: Icon(Icons.history), label: '백테스트'),
];

/// 하단 탭으로 이동 (열려 있는 하위 화면은 모두 닫고)
void goTab(BuildContext context, int i, {String? list}) {
  Navigator.of(context).popUntil((r) => r.isFirst);
  if (list != null) candidateListKey.value = list;
  tabIndex.value = i;
  tabTap.value++;
}

/// 모든 화면 아래에 붙는 하단 메뉴
class MainNavBar extends StatelessWidget {
  const MainNavBar({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<int>(
      valueListenable: tabIndex,
      builder: (context, i, _) => NavigationBar(
        selectedIndex: i,
        onDestinationSelected: (n) => goTab(context, n),
        destinations: navDestinations,
      ),
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
