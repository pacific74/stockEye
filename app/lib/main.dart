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
import 'widgets/nav.dart';

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
  // 탭을 누를 때마다 보유·일지는 새로 만들어서 최신 데이터를 다시 불러온다
  final _gen = List<int>.filled(5, 0);
  int _lastTap = 0;

  @override
  void initState() {
    super.initState();
    tabIndex.value = 0;
    tabIndex.addListener(_changed);
    tabTap.addListener(_tapped);
    candidateListKey.addListener(_changed);
  }

  @override
  void dispose() {
    tabIndex.removeListener(_changed);
    tabTap.removeListener(_tapped);
    candidateListKey.removeListener(_changed);
    super.dispose();
  }

  void _changed() => setState(() {});

  void _tapped() {
    if (tabTap.value == _lastTap) return;
    _lastTap = tabTap.value;
    setState(() {
      final i = tabIndex.value;
      if (i == 2 || i == 3) _gen[i]++; // 보유 / 일지: 항상 새로고침
    });
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      const HomeScreen(),
      CandidateListScreen(key: ValueKey('c${candidateListKey.value}'), list: candidateListKey.value),
      PortfolioScreen(key: ValueKey('p${_gen[2]}')),
      JournalScreen(key: ValueKey('j${_gen[3]}')),
      const BacktestScreen(),
    ];
    return Scaffold(
      body: IndexedStack(index: tabIndex.value, children: pages),
      bottomNavigationBar: const MainNavBar(),
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

  Future<Json?>? _profile;
  String? _profileFor;

  void _reloadProfile() => setState(() => _profile = myProfile());

  @override
  Widget build(BuildContext context) {
    final user = _auth.currentUser;
    if (_auth.currentSession == null || user == null) {
      _profileFor = null;
      return const LoginScreen();
    }
    if (_recovery) return NewPasswordScreen(onDone: () => setState(() => _recovery = false));
    if (_profileFor != user.id) {
      _profileFor = user.id;
      _profile = myProfile();
    }
    // 관리자 승인을 받은 회원만 앱 사용
    return FutureBuilder<Json?>(
      future: _profile,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }
        if (snap.hasError) {
          return PendingScreen(email: user.email, error: '${snap.error}', onRefresh: _reloadProfile);
        }
        final p = snap.data;
        isAdminUser = p?['is_admin'] == true;
        final status = p?['status'] as String? ?? 'pending';
        if (status == 'approved') return const HomeShell();
        return PendingScreen(email: user.email, rejected: status == 'rejected', onRefresh: _reloadProfile);
      },
    );
  }
}
