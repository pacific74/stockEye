import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'help_screen.dart';
import 'notify_screen.dart';

/// 인증 메일 링크가 돌아올 주소 (웹 앱 주소). 앱 빌드 때 --dart-define=WEB_URL=https://xxx.pages.dev
const String _webUrl = String.fromEnvironment('WEB_URL');
String? get _redirect => kIsWeb ? Uri.base.origin : (_webUrl.isEmpty ? null : _webUrl);

String _authMsg(Object e) {
  final m = e is AuthException ? e.message : '$e';
  if (m.contains('Invalid login credentials')) return '이메일 또는 비밀번호가 맞지 않습니다';
  if (m.contains('Email not confirmed')) return '메일 인증이 아직 안 됐습니다. 받은 메일의 링크를 눌러 주세요';
  if (m.contains('already registered')) return '이미 가입된 이메일입니다. 로그인하세요';
  if (m.contains('Password should be')) return '비밀번호는 6자 이상이어야 합니다';
  if (m.contains('rate limit') || m.contains('security purposes')) return '요청이 너무 잦습니다. 잠시 후 다시 시도하세요';
  if (m.contains('Signups not allowed')) return '지금은 새 가입을 받지 않습니다';
  return m;
}

enum _Mode { login, signup, reset }

/// 로그인 · 회원가입(이메일 인증) · 비밀번호 찾기
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  final _pw2 = TextEditingController();
  _Mode _mode = _Mode.login;
  bool _busy = false;
  String? _error;
  String? _info;

  SupabaseClient get _sb => Supabase.instance.client;

  void _switch(_Mode m) => setState(() {
        _mode = m;
        _error = null;
        _info = null;
      });

  Future<void> _submit() async {
    final email = _email.text.trim();
    if (!email.contains('@')) {
      setState(() => _error = '이메일을 확인하세요');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      switch (_mode) {
        case _Mode.login:
          await _sb.auth.signInWithPassword(email: email, password: _pw.text);
          break;
        case _Mode.signup:
          if (_pw.text.length < 8) throw const AuthException('비밀번호는 8자 이상으로 해 주세요');
          if (_pw.text != _pw2.text) throw const AuthException('비밀번호 확인이 다릅니다');
          final r = await _sb.auth.signUp(email: email, password: _pw.text, emailRedirectTo: _redirect);
          if (r.session == null) {
            _mode = _Mode.login;
            _info = '$email 로 인증 메일을 보냈습니다.\n메일의 링크를 누른 뒤 여기서 로그인하세요.\n(메일이 안 보이면 스팸함 확인)';
          }
          break;
        case _Mode.reset:
          await _sb.auth.resetPasswordForEmail(email, redirectTo: _redirect);
          _mode = _Mode.login;
          _info = '$email 로 비밀번호 재설정 메일을 보냈습니다.\n메일의 링크를 누르면 새 비밀번호를 정하는 화면이 열립니다.';
          break;
      }
    } catch (e) {
      _error = _authMsg(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = {_Mode.login: '로그인', _Mode.signup: '회원가입', _Mode.reset: '비밀번호 찾기'}[_mode]!;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: AutofillGroup(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Image.asset('assets/icon/logo_256.png', width: 88, height: 88),
                ),
                const SizedBox(height: 12),
                Text('StockEye', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text(title, style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(height: 20),
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  decoration: const InputDecoration(labelText: '이메일', border: OutlineInputBorder()),
                ),
                if (_mode != _Mode.reset) ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _pw,
                    obscureText: true,
                    autofillHints: [_mode == _Mode.signup ? AutofillHints.newPassword : AutofillHints.password],
                    onSubmitted: (_) => _mode == _Mode.login && !_busy ? _submit() : null,
                    decoration: InputDecoration(
                        labelText: _mode == _Mode.signup ? '비밀번호 (8자 이상)' : '비밀번호',
                        border: const OutlineInputBorder()),
                  ),
                ],
                if (_mode == _Mode.signup) ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _pw2,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: '비밀번호 확인', border: OutlineInputBorder()),
                  ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Colors.redAccent), textAlign: TextAlign.center),
                ],
                if (_info != null) ...[
                  const SizedBox(height: 12),
                  Text(_info!, style: const TextStyle(color: Colors.lightBlueAccent), textAlign: TextAlign.center),
                ],
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : Text({_Mode.login: '로그인', _Mode.signup: '가입하고 인증 메일 받기', _Mode.reset: '재설정 메일 받기'}[_mode]!),
                  ),
                ),
                const SizedBox(height: 8),
                if (_mode == _Mode.login)
                  Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                    TextButton(onPressed: () => _switch(_Mode.signup), child: const Text('회원가입')),
                    TextButton(onPressed: () => _switch(_Mode.reset), child: const Text('비밀번호 찾기')),
                  ])
                else
                  TextButton(onPressed: () => _switch(_Mode.login), child: const Text('로그인으로 돌아가기')),
                TextButton.icon(
                  onPressed: () =>
                      Navigator.push(context, MaterialPageRoute(builder: (_) => const HelpScreen(showNav: false))),
                  icon: const Icon(Icons.help_outline, size: 18),
                  label: const Text('처음이신가요? 이용 안내'),
                ),
                const SizedBox(height: 4),
                Text('투자 판단 참고용 도구입니다. 매수·매도 권유가 아니며, 결과에 대한 책임은 본인에게 있습니다.',
                    style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// 비밀번호 재설정 메일의 링크로 들어왔을 때: 새 비밀번호 정하기
class NewPasswordScreen extends StatefulWidget {
  const NewPasswordScreen({super.key, required this.onDone});
  final VoidCallback onDone;

  @override
  State<NewPasswordScreen> createState() => _NewPasswordScreenState();
}

class _NewPasswordScreenState extends State<NewPasswordScreen> {
  final _pw = TextEditingController();
  final _pw2 = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    if (_pw.text.length < 8 || _pw.text != _pw2.text) {
      setState(() => _error = _pw.text.length < 8 ? '비밀번호는 8자 이상으로 해 주세요' : '비밀번호 확인이 다릅니다');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Supabase.instance.client.auth.updateUser(UserAttributes(password: _pw.text));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('비밀번호를 바꿨습니다')));
      }
      widget.onDone();
    } catch (e) {
      setState(() => _error = _authMsg(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('새 비밀번호')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(
                controller: _pw,
                obscureText: true,
                decoration: const InputDecoration(labelText: '새 비밀번호 (8자 이상)', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _pw2,
                obscureText: true,
                decoration: const InputDecoration(labelText: '새 비밀번호 확인', border: OutlineInputBorder()),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Colors.redAccent)),
              ],
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: FilledButton(onPressed: _busy ? null : _save, child: const Text('저장')),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 가입은 했지만 관리자 승인 전 (또는 거절)
class PendingScreen extends StatelessWidget {
  const PendingScreen({super.key, this.email, this.rejected = false, this.error, required this.onRefresh});
  final String? email;
  final bool rejected;
  final String? error;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(rejected ? Icons.block : Icons.hourglass_top, size: 56,
                  color: rejected ? Colors.redAccent : Colors.amber),
              const SizedBox(height: 16),
              Text(rejected ? '가입이 승인되지 않았습니다' : '관리자 승인을 기다리고 있어요',
                  style: t.titleLarge, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              Text(
                  error != null
                      ? '회원 정보를 불러오지 못했습니다.\n$error'
                      : rejected
                          ? '관리자에게 문의하세요.'
                          : '${email ?? ''}\n관리자가 승인하면 바로 이용할 수 있습니다.\n승인 후 아래 [다시 확인]을 눌러 주세요.',
                  textAlign: TextAlign.center,
                  style: t.bodyMedium),
              const SizedBox(height: 24),
              if (!rejected)
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                      onPressed: onRefresh, icon: const Icon(Icons.refresh), label: const Text('다시 확인')),
                ),
              if (!rejected) ...[
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context, MaterialPageRoute(builder: (_) => const NotifySettingsScreen(showNav: false))),
                    icon: const Icon(Icons.notifications_active_outlined),
                    label: const Text('승인되면 폰으로 알림 받기'),
                  ),
                ),
              ],
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed: () =>
                    Navigator.push(context, MaterialPageRoute(builder: (_) => const HelpScreen(showNav: false))),
                icon: const Icon(Icons.help_outline, size: 18),
                label: const Text('이용 안내 보기'),
              ),
              TextButton(
                onPressed: () => Supabase.instance.client.auth.signOut(),
                child: const Text('로그아웃'),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
