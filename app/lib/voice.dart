import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 당일매매 음성 안내 (이 기기에만 저장되는 설정 · 알림 설정 화면에서 켜고 끔)
///   매수 조건 충족(진입조건충족 새로 고정)  → "매수발생" 여성 목소리
///   매도신호포착                            → "매도발생" 남성 목소리
///   기기에 한국어 여성·남성 목소리가 따로 있으면 그걸 고르고, 없으면 같은 목소리의 높낮이를 바꿔 구분
///   앱이 켜져 있을 때만 (당일매매 화면이 1분마다 새로 읽을 때) 울림
class VoiceAlert {
  static const _key = 'voice_alert';
  static final FlutterTts _tts = FlutterTts();
  static bool? _on;
  static Map<String, String>? _female, _male;
  static bool _ready = false;

  static Future<bool> enabled() async {
    if (_on != null) return _on!;
    try {
      final p = await SharedPreferences.getInstance();
      _on = p.getBool(_key) ?? true;
    } catch (_) {
      _on = true;
    }
    return _on!;
  }

  static Future<void> setEnabled(bool v) async {
    _on = v;
    try {
      final p = await SharedPreferences.getInstance();
      await p.setBool(_key, v);
    } catch (_) {}
  }

  // 목소리 이름으로 성별 짐작 (안드로이드 구글 TTS · 윈도우 · 애플 기본 한국어 목소리)
  static const _femaleHints = ['female', 'ism', 'kob', 'heami', 'sunhi', 'yuna', 'sora', 'jimin', 'seoyeon'];
  static const _maleHints = ['male', 'koc', 'kod', 'injoon', 'hyunsu', 'minsu', 'bongjin', 'gookmin', 'jinho'];

  static Future<void> _init() async {
    if (_ready) return;
    _ready = true;
    try {
      await _tts.setLanguage('ko-KR');
      await _tts.setSpeechRate(0.5);
      await _tts.awaitSpeakCompletion(true);
      final vs = await _tts.getVoices;
      final ko = <Map<String, String>>[
        for (final v in (vs as List? ?? const []))
          if ('${(v as Map)['locale'] ?? ''}'.toLowerCase().startsWith('ko'))
            {'name': '${v['name']}', 'locale': '${v['locale']}', 'gender': '${v['gender'] ?? ''}'.toLowerCase()},
      ];
      bool isFemale(String n) => _femaleHints.any(n.contains);
      bool isMale(String n) => !n.contains('female') && _maleHints.any(n.contains);
      Map<String, String>? pick(String g) {
        for (final v in ko) {
          if (v['gender'] == g) return {'name': v['name']!, 'locale': v['locale']!};
        }
        for (final v in ko) {
          final n = v['name']!.toLowerCase();
          if (g == 'female' ? isFemale(n) : isMale(n)) return {'name': v['name']!, 'locale': v['locale']!};
        }
        return null;
      }

      _female = pick('female');
      _male = pick('male');
    } catch (_) {}
  }

  static Future<void> _say(String text, {required bool male}) async {
    await _init();
    try {
      final v = male ? _male : _female;
      if (v != null) await _tts.setVoice(v);
      // 성별 목소리가 따로 없으면 높낮이로 구분 (남성 낮게 · 여성 높게)
      await _tts.setPitch(male ? (_male != null ? 1.0 : 0.6) : (_female != null ? 1.0 : 1.35));
      await _tts.speak(text);
    } catch (_) {}
  }

  /// 매수 조건 충족 (여성)
  static Future<void> buy({bool force = false}) async {
    if (force || await enabled()) await _say('매수발생', male: false);
  }

  /// 매도신호 발생 (남성)
  static Future<void> sell({bool force = false}) async {
    if (force || await enabled()) await _say('매도발생', male: true);
  }
}
