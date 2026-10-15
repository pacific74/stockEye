import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

import 'api.dart';

/// 지금 시세 (네이버 실시간 시세).
///  - 클라우드: Supabase 함수 live_quotes 가 대신 받아서 20초간 캐시 (웹 브라우저도 동작)
///  - PC 서버 모드: 앱이 직접 요청 (안드로이드/PC 앱)
class LiveQuote {
  LiveQuote({
    required this.code,
    this.name,
    required this.price,
    required this.change,
    required this.ratio,
    this.open,
    this.high,
    this.low,
    this.volume,
    this.status,
    this.tradedAt,
    this.overPrice,
    this.overRatio,
    this.overStatus,
  });

  final String code;
  final String? name;
  final double price; // 현재가 (장 마감 뒤에는 종가)
  final double change; // 전일 대비 (원 / 포인트)
  final double ratio; // 전일 대비 %
  final double? open, high, low, volume;
  final String? status; // OPEN / CLOSE / PREOPEN …
  final DateTime? tradedAt; // 마지막 체결 시각 (한국 시간)
  final double? overPrice, overRatio; // 넥스트레이드(장전·장후) 가격
  final String? overStatus;

  bool get isOpen => status == 'OPEN';

  /// 넥스트레이드 프리마켓(08:00~08:50)·애프터마켓(15:40~20:00) 거래 중이고 정규장은 닫힘 → 현재가로 NXT 가격을 씀 (2026-10-16)
  bool get nxtOn => overStatus == 'OPEN' && (overPrice ?? 0) > 0 && status != 'OPEN';

  /// NXT 가격의 정규장 가격 대비 % (프리마켓 = 전일 종가 대비 · 애프터마켓 = 오늘 종가 대비)
  double? get nxtRatio => !nxtOn || price <= 0 ? null : (overPrice! / price - 1) * 100;

  /// 네이버 응답의 한 종목을 해석 (숫자는 '71,200' 같은 문자열, 부호는 compareToPreviousPrice.code 로)
  static LiveQuote? fromNaver(Map<String, dynamic> m) {
    final code = (m['itemCode'] ?? m['reutersCode'] ?? m['symbolCode'])?.toString();
    final price = _num(m['closePriceRaw'] ?? m['closePrice'] ?? m['nowVal']);
    if (code == null || price == null) return null;
    final sign = _sign(m['compareToPreviousPrice']);
    double signed(double? v) => v == null ? 0 : (sign == 0 ? v : v.abs() * sign);
    final over = m['overMarketPriceInfo'] is Map ? Map<String, dynamic>.from(m['overMarketPriceInfo'] as Map) : null;
    final overSign = over == null ? 0 : _sign(over['compareToPreviousPrice']);
    final overRatio = over == null ? null : _num(over['fluctuationsRatioRaw'] ?? over['fluctuationsRatio']);
    return LiveQuote(
      code: code,
      name: (m['stockName'] ?? m['indexName'] ?? m['itemName'])?.toString(),
      price: price,
      change: signed(_num(m['compareToPreviousClosePriceRaw'] ?? m['compareToPreviousClosePrice'])),
      ratio: signed(_num(m['fluctuationsRatioRaw'] ?? m['fluctuationsRatio'])),
      open: _num(m['openPriceRaw'] ?? m['openPrice']),
      high: _num(m['highPriceRaw'] ?? m['highPrice']),
      low: _num(m['lowPriceRaw'] ?? m['lowPrice']),
      volume: _num(m['accumulatedTradingVolumeRaw'] ?? m['accumulatedTradingVolume']),
      status: m['marketStatus']?.toString(),
      tradedAt: DateTime.tryParse('${m['localTradedAt'] ?? ''}')?.toUtc().add(const Duration(hours: 9)),
      overPrice: over == null ? null : _num(over['overPriceRaw'] ?? over['overPrice']),
      overRatio: overRatio == null ? null : (overSign == 0 ? overRatio : overRatio.abs() * overSign),
      overStatus: over?['overMarketStatus']?.toString(),
    );
  }

  static double? _num(dynamic v) {
    if (v == null) return null;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString().replaceAll(',', '').replaceAll('%', '').trim());
  }

  /// 1 상한 · 2 상승 → +1 / 3 보합 → 0 / 4 하한 · 5 하락 → -1 (모르면 0 = 받은 부호 그대로)
  static int _sign(dynamic c) {
    if (c is! Map) return 0;
    final code = '${c['code'] ?? ''}';
    final name = '${c['name'] ?? ''}'.toUpperCase();
    if (code == '1' || code == '2' || name.contains('RISING') || name.contains('UPPER')) return 1;
    if (code == '4' || code == '5' || name.contains('FALLING') || name.contains('LOWER')) return -1;
    if (code == '3' || name.contains('EVEN')) return 0;
    return 0;
  }
}

class LiveResult {
  LiveResult(this.quotes, {this.fetchedAt, this.error, this.stale = false});
  final Map<String, LiveQuote> quotes;
  final DateTime? fetchedAt;
  final String? error;
  final bool stale;
}

class Live {
  /// 최근에 받은 종목 시세 (종목코드 → 시세) — 카드의 '오늘 등락률' 배지가 씀
  static final Map<String, LiveQuote> last = {};

  static Future<LiveResult> indices() => _get('index', const ['KOSPI', 'KOSDAQ']);

  /// 종목 시세. 50개씩 나눠 한 번에 요청하고, 빠진 종목은 하나씩 다시 요청
  /// (같은 종목 묶음이면 서버 캐시를 여러 사람이 같이 씀 → 코드를 정렬해서 묶음)
  static Future<LiveResult> stocks(List<String> codes) async {
    final want = codes.where((c) => RegExp(r'^[0-9A-Z]{6}$').hasMatch(c)).toSet().toList()..sort();
    if (want.isEmpty) return LiveResult({});
    final chunks = [for (var i = 0; i < want.length; i += 50) want.sublist(i, i + 50 > want.length ? want.length : i + 50)];
    final parts = await Future.wait(chunks.map((c) => _get('stock', c)));
    final quotes = <String, LiveQuote>{for (final r in parts) ...r.quotes};
    final first = parts.first;
    final missing = want.where((c) => !quotes.containsKey(c)).take(30).toList();
    final failedAll = quotes.isEmpty && first.error != null;
    if (missing.isNotEmpty && want.length > 1 && !failedAll) {
      final more = await Future.wait(missing.map((c) => _get('stock', [c])));
      for (final r in more) {
        quotes.addAll(r.quotes);
      }
    }
    last.addAll(quotes); // 화면 어디서나 오늘 등락률을 쓰도록 최근 시세 보관
    return LiveResult(quotes,
        fetchedAt: first.fetchedAt, error: quotes.isEmpty ? first.error : null, stale: parts.any((p) => p.stale));
  }

  /// 여러 결과 합치기
  static LiveResult merge(List<LiveResult> rs) {
    final ok = rs.where((r) => r.quotes.isNotEmpty).toList();
    return LiveResult({for (final r in rs) ...r.quotes},
        fetchedAt: ok.isEmpty ? null : ok.first.fetchedAt,
        error: ok.isEmpty ? rs.map((r) => r.error).whereType<String>().firstOrNull : null,
        stale: rs.any((r) => r.stale));
  }

  static Future<LiveResult> _get(String kind, List<String> codes) async {
    try {
      dynamic body;
      DateTime? at;
      String? err;
      var stale = false;
      if (useCloud) {
        final r = asMap(await Supabase.instance.client
            .rpc('live_quotes', params: {'p_kind': kind, 'p_codes': codes.join(',')}));
        body = r['body'];
        at = DateTime.tryParse('${r['fetched_at'] ?? ''}')?.toUtc().add(const Duration(hours: 9));
        err = r['error']?.toString();
        stale = r['stale'] == true;
        if ((r['status'] as num?)?.toInt() != 200 && body == null) {
          return LiveResult({}, error: err ?? '시세 서버 응답 ${r['status']}');
        }
      } else {
        final res = await http
            .get(Uri.parse('https://polling.finance.naver.com/api/realtime/domestic/$kind/${codes.join(',')}'))
            .timeout(const Duration(seconds: 6));
        body = jsonDecode(utf8.decode(res.bodyBytes));
        at = DateTime.now().toUtc().add(const Duration(hours: 9));
      }
      final datas = body is Map ? (body['datas'] ?? body['data'] ?? body['result']) : body;
      final out = <String, LiveQuote>{};
      if (datas is List) {
        for (final d in datas) {
          if (d is Map) {
            final q = LiveQuote.fromNaver(Map<String, dynamic>.from(d));
            if (q != null) out[q.code] = q;
          }
        }
      }
      return LiveResult(out, fetchedAt: at, error: out.isEmpty ? (err ?? '시세 형식을 읽지 못했습니다') : err, stale: stale);
    } catch (e) {
      final msg = e.toString();
      if (msg.contains('live_quotes') && (msg.contains('does not exist') || msg.contains('PGRST202'))) {
        return LiveResult({}, error: '서버에 "지금 시세" 기능이 아직 없습니다 (2026-10-08_live_quotes.sql 실행 필요)');
      }
      return LiveResult({}, error: msg.replaceFirst('Exception: ', ''));
    }
  }
}

/// 한국 시간 기준 장 상태
class MarketClock {
  MarketClock(this.now, {this.indexStatus, this.lastTrade});

  /// 지금 한국 시간 (기기 시간대와 상관없이)
  static DateTime kstNow() => DateTime.now().toUtc().add(const Duration(hours: 9));

  final DateTime now; // KST
  final String? indexStatus; // 지수 시세의 marketStatus
  final DateTime? lastTrade; // 지수 마지막 체결 시각 (KST)

  int get _hm => now.hour * 100 + now.minute;
  bool get weekend => now.weekday >= DateTime.saturday;

  /// 평일인데 마지막 체결이 오늘이 아니고 이미 9시가 지났다 = 휴장일
  bool get holiday =>
      weekend ||
      (lastTrade != null && _hm >= 910 && !_sameDay(lastTrade!, now) && indexStatus != 'OPEN');

  bool get open => indexStatus == 'OPEN' || (indexStatus == null && !holiday && _hm >= 900 && _hm < 1530);

  /// 넥스트레이드 프리마켓 08:00~08:50 · 애프터마켓 15:40~20:00 (평일, 휴장일 아님)
  bool get nxtHours => !holiday && !open && ((_hm >= 800 && _hm < 850) || (_hm >= 1530 && _hm < 2000));

  String get label {
    if (holiday) return '휴장';
    if (open) return '장중';
    if (_hm < 900) return nxtHours ? '장 시작 전 · NXT 프리마켓' : '장 시작 전';
    return nxtHours ? '장 마감 · NXT 애프터마켓' : '장 마감';
  }

  /// 자동 새로고침 간격 (장중·넥스트레이드 거래 시간 1분, 장 전후 5분, 그 밖엔 안 함)
  Duration? get refreshEvery {
    if (holiday) return null;
    if (open || nxtHours) return const Duration(minutes: 1);
    if (_hm >= 800 && _hm < 2000) return const Duration(minutes: 5);
    return null;
  }

  static bool _sameDay(DateTime a, DateTime b) => a.year == b.year && a.month == b.month && a.day == b.day;
}
