import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'api.dart';
import 'screens/backtest_screen.dart';
import 'screens/candidate_list_screen.dart';
import 'screens/home_screen.dart';
import 'screens/journal_screen.dart';
import 'screens/login_screen.dart';
import 'screens/portfolio_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (useCloud) {
    await Supabase.initialize(
      url: supabaseUrl,
      publishableKey: supabaseAnonKey,
      // implicit: 인증/재설정 메일을 다른 기기(폰 메일앱 → 브라우저)에서 열어도 동작
      authOptions: const FlutterAuthClientOptions(authFlowType: AuthFlowType.implicit),
    );
  }
  runApp(const StockEyeApp());
}

class StockEyeApp extends StatelessWidget {
  const StockEyeApp({super.key});

  @override
  Widget build(BuildContext context) {
    // 아이콘 색에 맞춘 테마: 남색 배경 + 청록 포인트
    const seed = Color(0xFF12B5D9);
    return MaterialApp(
      title: 'StockEye',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: seed,
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFF050B1C),
      ),
      themeMode: ThemeMode.dark,
      home: useCloud ? const AuthGate() : const HomeShell(),
    );
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _idx = 0;
  final _pages = const [HomeScreen(), CandidateListScreen(), PortfolioScreen(), JournalScreen(), BacktestScreen()];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _idx, children: _pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), label: '오늘'),
          NavigationDestination(icon: Icon(Icons.trending_up), label: '후보'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined), label: '보유'),
          NavigationDestination(icon: Icon(Icons.menu_book_outlined), label: '일지'),
          NavigationDestination(icon: Icon(Icons.history), label: '백테스트'),
        ],
      ),
    );
  }
}

/// 클라우드 모드: 로그인해야 데이터가 보인다 (Supabase 보안 규칙: 본인 매매일지는 본인만)
class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  final _auth = Supabase.instance.client.auth;
  StreamSubscription<AuthState>? _sub;
  bool _recovery = false; // 비밀번호 재설정 메일 링크로 들어온 경우

  @override
  void initState() {
    super.initState();
    _sub = _auth.onAuthStateChange.listen((s) {
      if (!mounted) return;
      setState(() {
        if (s.event == AuthChangeEvent.passwordRecovery) _recovery = true;
        if (s.event == AuthChangeEvent.signedOut) _recovery = false;
      });
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_auth.currentSession == null) return const LoginScreen();
    if (_recovery) return NewPasswordScreen(onDone: () => setState(() => _recovery = false));
    return const HomeShell();
  }
}
