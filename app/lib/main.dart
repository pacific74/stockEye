import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'api.dart';
import 'intraday_screen.dart';
import 'screens/backtest_screen.dart';
import 'screens/candidate_list_screen.dart';
import 'screens/home_screen.dart';
import 'screens/journal_screen.dart';
import 'screens/login_screen.dart';
import 'screens/portfolio_screen.dart';
import 'screens/stats_screen.dart';
import 'update_check.dart';
import 'widgets/nav.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 시작 때 Supabase 준비가 멈추면 로고 화면에서 영원히 멈춰 보임 → 12초 안에 안 끝나면 이유를 화면에 보여 주고 다시 시도 (2026-10-19)
  Object? startError;
  if (useCloud) {
    Future<void> init({bool keepLogin = true}) => Supabase.initialize(
          url: supabaseUrl,
          publishableKey: supabaseAnonKey,
          // implicit: 인증/재설정 메일을 다른 기기(폰 메일앱 → 브라우저)에서 열어도 동작
          authOptions: FlutterAuthClientOptions(
            authFlowType: AuthFlowType.implicit,
            // 폰 저장소 플러그인이 깨진 빌드에서는 로그인 저장 없이라도 시작 (그 경우 앱을 켤 때마다 로그인)
            localStorage: keepLogin ? null : const EmptyLocalStorage(),
          ),
        ).timeout(const Duration(seconds: 12));
    try {
      await init();
    } catch (e) {
      startError = e;
      if ('$e'.toLowerCase().contains('sharedpreferences')) {
        try {
          await init(keepLogin: false);
          startError = null;
        } catch (e2) {
          startError = e2;
        }
      }
    }
  }
  runApp(startError == null ? const StockEyeApp() : _StartError(error: startError));
}

/// 시작 실패 화면 — 오류 내용을 그대로 보여 줌 (캡처해서 알려 주기 쉽게) + 다시 시도
class _StartError extends StatelessWidget {
  const _StartError({required this.error});
  final Object error;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(brightness: Brightness.dark, useMaterial3: true, scaffoldBackgroundColor: const Color(0xFF050B1C)),
      home: Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('시작 중 문제가 생겼어요', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              const Text('인터넷 연결을 확인하고 [다시 시도]를 눌러 보세요. 계속 안 되면 이 화면을 캡처해서 알려 주세요.',
                  style: TextStyle(color: Colors.grey)),
              const SizedBox(height: 16),
              SelectableText('$error', style: const TextStyle(fontSize: 12, color: Colors.orange)),
              const SizedBox(height: 20),
              FilledButton(onPressed: () => main(), child: const Text('다시 시도')),
            ]),
          ),
        ),
      ),
    );
  }
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
  // 탭을 누를 때마다 그 탭 화면을 새로 만들어서 최신 데이터를 다시 불러온다 (메인·관심·보유·일지·검증 모두)
  final _gen = <String, int>{}; // 탭 이름 → 새로 만든 횟수
  int _lastTap = 0;
  // 뒤로가기 (폰 뒤로 버튼 · 브라우저 뒤로): 앱 밖으로 나가지 않고 직전 탭으로 → 메인 → 메인에서 2초 안에 한 번 더 누르면 종료
  final _hist = <int>[];
  int _cur = 0;
  bool _backNav = false;
  DateTime? _exitAt;

  @override
  void initState() {
    super.initState();
    tabIndex.value = 0;
    tabIndex.addListener(_changed);
    tabTap.addListener(_tapped);
    candidateListKey.addListener(_changed);
    // 새 APK 가 올라와 있으면 안내 (안드로이드만, 앱 켤 때 한 번)
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) checkForUpdate(context);
    });
  }

  @override
  void dispose() {
    tabIndex.removeListener(_changed);
    tabTap.removeListener(_tapped);
    candidateListKey.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    final i = tabIndex.value;
    if (i != _cur) {
      if (!_backNav) {
        _hist.add(_cur);
        if (_hist.length > 20) _hist.removeAt(0);
      }
      _cur = i;
    }
    setState(() {});
  }

  void _goBack(int i) {
    _backNav = true;
    tabIndex.value = i;
    _backNav = false;
  }

  void _onBack() {
    while (_hist.isNotEmpty && _hist.last == tabIndex.value) {
      _hist.removeLast();
    }
    if (_hist.isNotEmpty || tabIndex.value != 0) {
      _goBack(_hist.isNotEmpty ? _hist.removeLast() : 0);
      return;
    }
    final now = DateTime.now();
    if (_exitAt != null && now.difference(_exitAt!) < const Duration(seconds: 2)) {
      SystemNavigator.pop();
      return;
    }
    _exitAt = now;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('뒤로 버튼을 한 번 더 누르면 종료돼요'), duration: Duration(seconds: 2)));
  }

  void _tapped() {
    if (tabTap.value == _lastTap) return;
    _lastTap = tabTap.value;
    setState(() {
      final i = tabIndex.value;
      final tabs = visibleTabs;
      if (i >= 0 && i < tabs.length) _gen[tabs[i]] = (_gen[tabs[i]] ?? 0) + 1; // 모든 탭: 누를 때마다 새로 만들어 최신 데이터를 다시 불러옴 (보유 매도 → 메인 반영 등)
    });
  }

  @override
  Widget build(BuildContext context) {
    // 하단 메뉴 순서(visibleTabs)대로 화면을 만듦 — 당일매매·검증·통계는 관리자만
    Widget page(String k) {
      final g = _gen[k] ?? 0;
      return switch (k) {
        'rec' => CandidateListScreen(key: ValueKey('c${candidateListKey.value}-$g'), list: candidateListKey.value),
        'intraday' => IntradayScreen(key: ValueKey('i$g')),
        'port' => PortfolioScreen(key: ValueKey('p$g')),
        'journal' => JournalScreen(key: ValueKey('j$g')),
        'backtest' => BacktestScreen(key: ValueKey('b$g')),
        'stats' => StatsScreen(key: ValueKey('s$g')),
        _ => HomeScreen(key: ValueKey('h$g')),
      };
    }
    final pages = [for (final k in visibleTabs) page(k)];
    return PopScope(
      canPop: false, // 하위 화면(종목 상세 등)은 평소대로 닫히고, 탭 화면에서만 여기로 옴
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _onBack();
      },
      child: Scaffold(
        body: IndexedStack(index: tabIndex.value < pages.length ? tabIndex.value : 0, children: pages),
        bottomNavigationBar: const MainNavBar(),
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
