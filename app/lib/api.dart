import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

/// 데이터를 어디서 가져올지
///  1) 클라우드 (기본 배포): 빌드할 때 --dart-define=SUPABASE_URL=… --dart-define=SUPABASE_ANON_KEY=…
///     → Supabase 에서 직접 읽음 (PC 서버 불필요, 어디서나 로그인해서 사용)
///  2) PC 서버: 위 값이 없으면 예전처럼 PC 의 FastAPI 서버 (http://PC주소:8000)
const String supabaseUrl = String.fromEnvironment('SUPABASE_URL');
const String supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
bool get useCloud => supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty;

const String _envBase = String.fromEnvironment('API_BASE');

String get apiBase {
  if (useCloud) return 'StockEye 클라우드';
  if (_envBase.isNotEmpty) return _envBase;
  if (kIsWeb && Uri.base.path.startsWith('/app')) return Uri.base.origin;
  return 'http://localhost:8000';
}

typedef Json = Map<String, dynamic>;

Json asMap(dynamic v) => v == null ? <String, dynamic>{} : Map<String, dynamic>.from(v as Map);
List<Json> asList(dynamic v) => (v as List? ?? []).map((e) => asMap(e)).toList();

class Api {
  /// 관심 목록 새로고침: 캐시한 최신 리포트(2분)를 버리고 다시 읽게
  static void forgetReport() { if (useCloud) _Cloud.forgetReport(); }
  static Future<Json> dashboard() => useCloud ? _Cloud.dashboard() : _Http.dashboard();
  /// V3 기준 전략: 선정 상태 · 매수/매도 예정일 · 거래일 달력 · 모의 보유 · 고정 이후 성과 (리포트 market.v3)
  static Future<Json> v3() => useCloud ? _Cloud.v3() : _Http.v3();
  static Future<Json> candidates(String list, {int top = 30}) =>
      useCloud ? _Cloud.candidates(list, top) : _Http.candidates(list, top);
  /// 어제(최근) 분석의 모든 후보 (종합 + 전략별, 종목별 1개) — '지금 매수구간' 계산용
  static Future<List<Json>> allCandidates() => useCloud ? _Cloud.allCandidates() : _Http.allCandidates();
  /// 업종/테마 '오늘' 강도 (GitHub sector-live 가 장중 1시간마다 · 업종 전체 종목 거래대금 가중)
  /// 업종(테마)별 전체 종목 [code, name, 전일 등락%, 거래대금(억), 시가총액(억)] (저녁 배치 · system_status 'sector_members')
  static Json? _secMembers;
  static Future<Json> sectorMembers() async {
    if (_secMembers != null) return _secMembers!;
    final d = useCloud ? await _Cloud.statusOf('sector_members') : <String, dynamic>{};
    if (d.isNotEmpty) _secMembers = d;
    return d;
  }
  static Future<Json> sectorsLive() => useCloud ? _Cloud.statusOf('sectors_live') : Future.value(<String, dynamic>{});
  static Future<Json> sectors() => useCloud ? _Cloud.sectors() : _Http.get('/api/sectors');
  static Future<Json> sector(String group) =>
      useCloud ? _Cloud.sector(group) : _Http.get('/api/sectors/${Uri.encodeComponent(group)}');
  static Future<List<Json>> search(String q) => useCloud ? _Cloud.search(q) : _Http.search(q);
  static Future<Json> stock(String code) => useCloud ? _Cloud.stock(code) : _Http.get('/api/stocks/$code');
  static Future<Json> explain(String code) => useCloud ? _Cloud.explain(code) : _Http.get('/api/stocks/$code/explain');
  static Future<Json> similar(String code) => useCloud ? _Cloud.similar(code) : _Http.get('/api/stocks/$code/similar');
  static Future<Json> requestPattern(String code) => _Cloud.requestPattern(code);
  static Future<Json> patternStatus(String code) => useCloud ? _Cloud.patternStatus(code) : Future.value(<String, dynamic>{});
  /// 관심종목 적중률 계산 요청 (관리자) — only: 'HIT' · 'HIT:nextday' · 'HIT:2025' · 'HIT:early:2024,2025'
  static Future<Json> requestHitRate(String only) => _Cloud.requestHitRate(only);
  static Future<Json> hitRateJob() => useCloud ? _Cloud.hitRateJob() : Future.value(<String, dynamic>{});
  /// 당일단타: PC 가 09:00~10:00 1분마다 올리는 후보 (system_status 'daytrade')
  static Future<Json> daytrade() => useCloud ? _Cloud.daytrade() : Future.value(<String, dynamic>{});
  /// 종가배팅: PC 가 14:50~15:20 1분마다 올리는 후보 (system_status 'closingbet')
  static Future<Json> closingbet() => useCloud ? _Cloud.statusOf('closingbet') : Future.value(<String, dynamic>{});
  /// 당일단타 [종목찾기] (관리자) → GitHub 'daytrade' 작업이 지금 시세로 한 번 계산
  static Future<Json> requestDaytrade() => _Cloud.rpcJob('request_daytrade');
  static Future<Json> requestClosingbet() => _Cloud.rpcJob('request_closingbet');
  static Future<Json> closingbetJob() => useCloud ? _Cloud.statusOf('closingbet_job') : Future.value(<String, dynamic>{});
  /// 상한가포착: PC 가 09:05~15:20 1분마다 올리는 후보 (system_status 'limitcatch')
  static Future<Json> limitcatch() => useCloud ? _Cloud.statusOf('limitcatch') : Future.value(<String, dynamic>{});
  static Future<Json> requestLimitcatch() => _Cloud.rpcJob('request_limitcatch');
  static Future<Json> limitcatchJob() => useCloud ? _Cloud.statusOf('limitcatch_job') : Future.value(<String, dynamic>{});
  static Future<Json> daytradeJob() => useCloud ? _Cloud.statusOf('daytrade_job') : Future.value(<String, dynamic>{});
  static Future<List<Json>> strategies() => useCloud ? _Cloud.strategies() : _Http.getList('/api/strategies');
  /// 추천 기록 (검증 > 추천주): 추천이 있는 날짜 (최근 순) · 그날 추천 전부 (구분이 겹치면 구분마다 한 줄)
  static Future<List<String>> recDates() => useCloud ? _Cloud.recDates() : Future.value(<String>[]);
  static Future<List<Json>> recommendations(String date) =>
      useCloud ? _Cloud.recommendations(date) : Future.value(<Json>[]);
  static Future<Json> backtest(Json req) => useCloud ? _Cloud.backtest(req) : _Http.post('/api/backtest', req);
  static Future<Json> latestBacktest({String? strategy}) => useCloud
      ? _Cloud.latestBacktest(strategy)
      : _Http.get('/api/backtest/latest${strategy == null ? '' : '?strategy=$strategy'}');
  static Future<Json> tradingStatus() => useCloud ? _Cloud.tradingStatus() : _Http.get('/api/trading/status');
  static Future<List<Json>> orders({String status = 'pending'}) =>
      useCloud ? _Cloud.orders(status) : _Http.getList('/api/orders?status=$status');
  static Future<Json> approveOrder(String id) =>
      useCloud ? _Cloud.rpcMap('approve_order', {'p_id': id}) : _Http.post('/api/orders/$id/approve', {});
  static Future<Json> rejectOrder(String id) =>
      useCloud ? _Cloud.rpcMap('reject_order', {'p_id': id}) : _Http.post('/api/orders/$id/reject', {});
  static Future<List<Json>> journal({String? status, String? mode}) {
    if (useCloud) return _Cloud.journal(status, mode);
    final q = [if (status != null) 'status=$status', if (mode != null) 'mode=$mode'].join('&');
    return _Http.getList('/api/journal${q.isEmpty ? '' : '?$q'}');
  }

  static Future<Json> closePosition(String id, double price, {String reason = '수동', String? exitTime}) => useCloud
      ? _Cloud.closePosition(id, price, reason, exitTime)
      : _Http.post('/api/journal/$id/close', {'price': price, 'reason': reason, 'exit_time': exitTime});
  static Future<Json> journalAnalysis({String? mode}) => useCloud
      ? _Cloud.journalAnalysis(mode, ai: false)
      : _Http.get('/api/journal/analysis${mode == null ? '' : '?mode=$mode'}');
  static Future<Json> journalAI({String? mode}) => useCloud
      ? _Cloud.journalAnalysis(mode, ai: true)
      : _Http.get('/api/journal/analysis/ai${mode == null ? '' : '?mode=$mode'}');
  static Future<List<Json>> portfolioReview() =>
      useCloud ? _Cloud.portfolioReview() : _Http.getList('/api/portfolio/review');
  /// 종목별 최근 분석 점수 {code: score} (클라우드: 전 종목 상세에서, PC 모드: 종목 화면 API)
  static Future<Map<String, double>> scores(List<String> codes) async => {
        for (final e in (await stockMeta(codes)).entries)
          if (e.value['score'] is num) e.key: (e.value['score'] as num).toDouble()
      };

  /// 종목별 {score, market} (최근 분석 기준)
  static Future<Map<String, Json>> stockMeta(List<String> codes) async {
    final want = codes.toSet().where((c) => c.isNotEmpty).toList();
    if (want.isEmpty) return {};
    try {
      if (useCloud) {
        final rows =
            await Supabase.instance.client.from('stock_details').select('code,score,market').inFilter('code', want);
        return {for (final r in rows) r['code'] as String: {'score': r['score'], 'market': r['market']}};
      }
      final res = await Future.wait(want.map((c) => _Http.get('/api/stocks/$c').then((d) => MapEntry(c, d),
          onError: (_) => MapEntry(c, <String, dynamic>{}))));
      return {
        for (final e in res)
          e.key: {
            'score': asMap(e.value['candidate'])['score'],
            'market': asMap(e.value['candidate'])['market'],
          }
      };
    } catch (_) {
      return {};
    }
  }

  static Future<Json> addHolding(Json h) => useCloud ? _Cloud.addHolding(h) : _Http.post('/api/portfolio', h);
  static Future<void> deleteHolding(String id) =>
      useCloud ? _Cloud.deleteHolding(id) : _Http.send('DELETE', '/api/portfolio/$id');
}

// ============================================================ 클라우드 (Supabase)
class _Cloud {
  static SupabaseClient get db => Supabase.instance.client;

  static const _tsKeys = ['entry_time', 'exit_time', 'signal_time', 'created_at', 'expires_at', 'filled_at', 'time'];

  static Json _norm(dynamic row) {
    final m = asMap(row);
    for (final k in _tsKeys) {
      final v = m[k];
      if (v is String && v.length >= 16) m[k] = ('${v.replaceFirst('T', ' ')}:00').substring(0, 19);
    }
    return m;
  }

  static Json _position(dynamic row) {
    final p = _norm(row);
    final ep = (p['entry_price'] as num?)?.toDouble();
    double? pctOf(String k) {
      final v = (p[k] as num?)?.toDouble();
      if (v == null || ep == null || ep == 0) return null;
      return ((v / ep - 1) * 10000).roundToDouble() / 100;
    }

    p['mae_pct'] = pctOf('min_price'); // 보유 중 최대 손실폭
    p['mfe_pct'] = pctOf('max_price'); // 보유 중 최대 수익폭
    return p;
  }

  static String _ts(String t) => t.length == 10 ? '$t 09:00:00' : (t.length == 16 ? '$t:00' : t);

  // ---------------------------------------------------------------- 리포트
  static Json? _rep;
  static DateTime? _repAt;

  /// 새로고침: 다음 조회 때 최신 리포트를 다시 읽게 (관심 목록 새로고침에서 씀)
  static void forgetReport() => _repAt = null;

  static Future<Json> _latest() async {
    if (_rep != null && _repAt != null && DateTime.now().difference(_repAt!).inMinutes < 2) return _rep!;
    final r = await db.from('daily_reports').select().order('date', ascending: false).limit(1).maybeSingle();
    if (r == null) {
      throw Exception('아직 리포트가 없습니다.\n첫 일일 배치가 끝나면 나타납니다 (평일 저녁 6시 40분 이후).');
    }
    _rep = asMap(r);
    _repAt = DateTime.now();
    return _rep!;
  }

  static Future<Json> dashboard() async {
    _repAt = null; // 새로고침 = 최신으로
    final r = await _latest();
    // 업종 '전일' 값: 최신 리포트가 장중 재분석이면 그 전 날짜(저녁 확정) 리포트의 업종
    var prev = asList(r['sectors']);
    var prevDate = r['date'];
    if (asMap(r['market'])['intraday'] != null) {
      try {
        final p = await db
            .from('daily_reports')
            .select('date,sectors')
            .lt('date', r['date'] as String)
            .order('date', ascending: false)
            .limit(1)
            .maybeSingle();
        if (p != null) {
          prev = asList(p['sectors']);
          prevDate = p['date'];
        }
      } catch (_) {}
    }
    return {
      'date': r['date'],
      'as_of': r['as_of'],
      'market': r['market'],
      'sectors': asList(r['sectors']),
      'sectors_prev': prev,
      'sectors_prev_date': prevDate,
      'top10': r['top10'] ?? [],
      'strategies': r['strategies'] ?? {},
      'funnel': r['funnel'],
      'ai_explained': r['ai_explained'] ?? 0,
    };
  }

  static Future<Json> v3() async {
    final r = await _latest();
    final m = asMap(asMap(r['market'])['v3']);
    return m.isEmpty ? m : {...m, 'date': r['date']};
  }

  static Future<Json> candidates(String list, int top) async {
    final r = await _latest();
    final rows = await db
        .from('candidates')
        .select('payload')
        .eq('date', r['date'] as String)
        .eq('list', list)
        .order('rank')
        .limit(top);
    final cands = rows.map((e) => asMap(e['payload'])).toList();
    if (list == 'overall') {
      return {
        'list': 'overall',
        'date': r['date'],
        'intraday': asMap(r['market'])['intraday'],
        'name': '상승 후보 (종합 점수)',
        'candidates': cands
      };
    }
    final s = asMap(asMap(r['strategies'])[list]);
    return {
      'list': list,
      'date': r['date'],
      'intraday': asMap(r['market'])['intraday'], // 장중 재분석이면 "11:00" 같은 시각
      'name': s['name'] ?? list,
      'description': s['description'],
      'limitation': s['limitation'],
      'meta': asMap(asMap(r['market'])[list]), // 실험 탭 요약 (예: 익일 유망주 등급 수·어제 후보 결과)
      'candidates': cands,
    };
  }

  static Future<List<Json>> allCandidates() async {
    final r = await _latest();
    final rows = await db.from('candidates').select('payload').eq('date', r['date'] as String).limit(500);
    return _uniqueByCode(rows.map((e) => asMap(e['payload'])));
  }

  static Future<Json> sectors() async {
    final r = await _latest();
    return {'date': r['date'], 'sectors': r['sectors'] ?? [], 'unmatched_theme_names': r['unmatched_theme_names'] ?? []};
  }

  static Future<Json> sector(String group) async {
    final r = await _latest();
    final g = asList(r['sectors']).where((s) => s['group'] == group);
    if (g.isEmpty) throw Exception('업종/테마 없음');
    return g.first;
  }

  // ---------------------------------------------------------------- 종목
  static Future<List<Json>> search(String q) async {
    final s = q.replaceAll(RegExp(r'[,()*%\\."]'), '').trim();
    if (s.isEmpty) return [];
    final rows = await db
        .from('stock_details')
        .select('code,name,market')
        .or('name.ilike.*$s*,code.like.$s*')
        .order('score', ascending: false)
        .limit(20);
    return rows.map(asMap).toList();
  }

  static Future<Json> _detail(String code, String cols) async {
    final r = await db.from('stock_details').select(cols).eq('code', code).maybeSingle();
    if (r == null) throw Exception('종목 데이터가 없습니다 ($code)');
    return asMap(r);
  }

  static Future<Json> stock(String code) async {
    final r = await _detail(code, 'candidate,chart,disclosures,explanation,sector,market');
    return {
      'sector': r['sector'],
      'market': r['market'],
      'candidate': r['candidate'],
      'chart': r['chart'] ?? [],
      'explanation': r['explanation'],
      'disclosures': r['disclosures'] ?? [],
    };
  }

  static Future<Json> explain(String code) async {
    final r = await _detail(code, 'explanation');
    if (r['explanation'] == null) throw Exception('설명이 아직 없습니다');
    return asMap(r['explanation']);
  }

  static Future<Json> similar(String code) async {
    final r = await _detail(code, 'similar_patterns');
    final s = r['similar_patterns'];
    if (s == null) return {'missing': true}; // 아직 계산 안 됨 → 화면에서 [패턴 찾기 요청]
    final m = asMap(s);
    if (m['error'] != null) throw Exception('${m['error']}');
    return m;
  }

  /// 검색 종목 '비슷한 과거 패턴' 요청 (같은 종목이 대기 중이면 그 요청을 같이 씀)
  static Future<Json> requestPattern(String code) async {
    try {
      return asMap(await db.rpc('request_pattern', params: {'p_code': code}));
    } on PostgrestException catch (e) {
      throw Exception(e.message);
    }
  }

  static Future<Json> requestHitRate(String only) async {
    try {
      return asMap(await db.rpc('request_hitrate', params: {'p_only': only}));
    } on PostgrestException catch (e) {
      throw Exception(e.message);
    }
  }

  static Future<Json> rpcJob(String fn) async {
    try {
      return asMap(await db.rpc(fn));
    } on PostgrestException catch (e) {
      throw Exception(e.message);
    }
  }

  static Future<Json> statusOf(String key) async {
    try {
      final r = await db.from('system_status').select('payload,updated_at').eq('key', key).maybeSingle();
      if (r == null) return {};
      return {...asMap(r['payload']), 'updated_at': r['updated_at']};
    } catch (_) {
      return {};
    }
  }

  static Future<Json> daytrade() async {
    try {
      final r = await db.from('system_status').select('payload,updated_at').eq('key', 'daytrade').maybeSingle();
      if (r == null) return {};
      return {...asMap(r['payload']), 'updated_at': r['updated_at']};
    } catch (_) {
      return {};
    }
  }

  /// 적중률 계산 상태 (queued · running · done · failed) + 갱신 시각
  static Future<Json> hitRateJob() async {
    try {
      final r = await db.from('system_status').select('payload,updated_at').eq('key', 'hitrate_job').maybeSingle();
      if (r == null) return {};
      return {...asMap(r['payload']), 'updated_at': r['updated_at']};
    } catch (_) {
      return {};
    }
  }

  /// 그 종목의 최근 패턴 요청 상태 (queued/running/done/failed), 없으면 빈 Map
  static Future<Json> patternStatus(String code) async {
    try {
      return asMap(await db.rpc('pattern_request_status', params: {'p_code': code}));
    } on PostgrestException {
      return {}; // 마이그레이션 전
    }
  }

  // ---------------------------------------------------------------- 전략 / 백테스트
  static Future<List<Json>> strategies() async {
    final meta = await db.from('system_status').select('payload').eq('key', 'strategies').maybeSingle();
    final bts = await db.from('backtests').select('key,start_date,end_date,metrics,metrics_oos,audit_passed');
    final byKey = {for (final b in bts) b['key'] as String: asMap(b)};
    return asList(meta?['payload']).map<Json>((s) {
      final b = byKey[s['key']];
      return {
        ...s,
        'backtest': b == null
            ? null
            : {
                'start': b['start_date'],
                'end': b['end_date'],
                'metrics': b['metrics'],
                'metrics_oos': b['metrics_oos'],
                'audit_passed': b['audit_passed'],
              },
      };
    }).toList();
  }

  static Future<Json> backtest(Json req) async {
    final spec = Map<String, dynamic>.from(req)..removeWhere((k, v) => v == null || v == false);
    spec.remove('run_audit');
    if (spec['strategy'] == null) spec.remove('strategy');
    final Json r;
    try {
      r = await db.from('backtest_requests').insert({'spec': spec}).select('id').single();
    } on PostgrestException catch (e) {
      if (e.code == '42501') throw Exception('이미 대기 중인 백테스트 요청이 있습니다. 끝난 뒤 다시 요청하세요.');
      rethrow;
    }
    return {
      'queued': true,
      'id': r['id'],
      'message': '백테스트를 요청했습니다. 다음 배치(평일 저녁 또는 토요일)에서 5년치로 실행한 뒤 이 화면에 결과가 나옵니다.',
    };
  }

  static Future<List<String>> recDates() async {
    final rows = await db.from('recommendations').select('rec_date').order('rec_date', ascending: false).limit(1000);
    final out = <String>[];
    for (final r in rows) {
      final d = '${r['rec_date']}'.substring(0, 10);
      if (!out.contains(d)) out.add(d);
    }
    return out;
  }

  static Future<List<Json>> recommendations(String date) async {
    final rows = await db
        .from('recommendations')
        .select('rec_date,kind,code,name,rec_time,score,status,verdict,price,entry,target1,target2,target3,stop,'
            'stop_pct,target1_pct,rr1,zone1_low,zone1_high,zone2_low,zone2_high,zone3_low,zone3_high,'
            'res_status,res_done,res_pnl,res_filled,res_days,res_max_up,res_max_dn,res_last,res_d_t1,res_d_stop')
        .eq('rec_date', date)
        .order('code')
        .limit(1000);
    return rows.map((e) => asMap(e)).toList();
  }

  static Future<Json> latestBacktest(String? strategy) async {
    if (strategy != null) {
      final r = await db.from('backtests').select('payload').eq('key', strategy).maybeSingle();
      if (r == null) throw Exception('아직 백테스트 결과가 없습니다');
      return asMap(r['payload']);
    }
    final req = await db
        .from('backtest_requests')
        .select('result,done_at')
        .eq('status', 'done')
        .order('done_at', ascending: false)
        .limit(1)
        .maybeSingle();
    if (req != null && req['result'] != null) return asMap(req['result']);
    final r = await db.from('backtests').select('payload').order('updated_at', ascending: false).limit(1).maybeSingle();
    if (r == null) throw Exception('아직 백테스트 결과가 없습니다');
    return asMap(r['payload']);
  }

  /// 내가 요청한 백테스트 상태 (queued/running/done/failed)
  static Future<List<Json>> backtestRequests() async {
    final rows = await db
        .from('backtest_requests')
        .select('id,spec,status,message,created_at,done_at')
        .order('id', ascending: false)
        .limit(10);
    return rows.map(asMap).toList();
  }

  // ---------------------------------------------------------------- 매매 상태 / 주문
  static Future<Json> tradingStatus() async {
    final st = await db.from('system_status').select('payload,updated_at').eq('key', 'trading').maybeSingle();
    final p = asMap(st?['payload']);
    final pending = await db.from('orders').select('id').eq('status', 'pending');
    final opens = await db.from('positions').select('id').eq('status', 'open');
    final cash = await db.from('paper_cash').select('balance').eq('mode', 'paper').maybeSingle();
    final batch = await db.from('system_status').select('payload').eq('key', 'batch').maybeSingle();
    return {
      'mode': p['mode'] ?? 'alert',
      'broker': p['broker'],
      'allow_real_orders': p['allow_real_orders'] ?? false,
      'notify_channels': p['notify_channels'] ?? <String>[],
      'pending_orders': pending.length,
      'open_positions': opens.length,
      'paper_cash': cash?['balance'] ?? p['paper_capital'],
      'batch': batch?['payload'],
      'recent_alerts': <Json>[],
    };
  }

  static Future<List<Json>> orders(String status) async {
    final rows = await db.from('orders').select().eq('status', status).order('created_at', ascending: false).limit(100);
    return rows.map(_norm).toList();
  }

  static Future<Json> rpcMap(String fn, Json params) async => asMap(await db.rpc(fn, params: params));

  // ---------------------------------------------------------------- 매매일지 / 보유종목
  static Future<List<Json>> journal(String? status, String? mode) async {
    var q = db.from('positions').select();
    if (status != null) q = q.eq('status', status);
    if (mode != null) q = q.eq('mode', mode);
    final rows = await q.order('entry_time', ascending: false).limit(300);
    return rows.map(_position).toList();
  }

  static Future<Json> closePosition(String id, double price, String reason, String? exitTime) async {
    final r = await db.rpc('close_position', params: {
      'p_id': id,
      'p_price': price,
      'p_reason': reason,
      if (exitTime != null) 'p_exit_time': _ts(exitTime),
    });
    return _position(r);
  }

  static Future<Json> journalAnalysis(String? mode, {required bool ai}) async {
    final r = await db.from('journal_analysis').select('payload,updated_at').eq('mode', mode ?? 'all').maybeSingle();
    final empty = <String, dynamic>{'closed': 0, 'message': '아직 분석이 없습니다.\n매매일지 분석은 매일 저녁 배치 때 갱신됩니다.'};
    if (r == null) {
      return ai ? {'stats': empty, 'summary': {'text': empty['message'], 'source': 'rule'}} : empty;
    }
    final p = asMap(r['payload']);
    return ai ? p : asMap(p['stats']);
  }

  static Future<List<Json>> portfolioReview() async {
    final opens = await db.from('positions').select().eq('status', 'open').order('entry_time', ascending: false);
    if (opens.isEmpty) return [];
    final ids = opens.map((p) => p['id'] as String).toList();
    final reviews = await db.from('position_reviews').select('position_id,payload').inFilter('position_id', ids);
    final byId = {for (final r in reviews) r['position_id'] as String: asMap(r['payload'])};
    return opens.map<Json>((row) {
      final p = _position(row);
      final rv = byId[p['id']];
      return <String, dynamic>{
        ...p,
        'avg_price': p['entry_price'],
        'target': p['target1'],
        'buy_date': (p['entry_time'] as String? ?? '').length >= 10 ? (p['entry_time'] as String).substring(0, 10) : null,
        if (rv != null) ...rv,
        if (rv == null) 'status': '점검 대기',
        if (rv == null) 'alerts': ['오늘 저녁 배치 때 손절·목표·추세를 점검합니다'],
      };
    }).toList();
  }

  static Future<Json> addHolding(Json h) async {
    final r = await db.rpc('open_manual_position', params: {
      'p_code': h['code'],
      'p_price': h['avg_price'],
      'p_qty': h['qty'],
      if (h['buy_date'] != null) 'p_entry_time': _ts(h['buy_date'] as String),
      'p_stop': h['stop'],
      'p_target1': h['target'],
      'p_target2': h['target2'],
      'p_memo': h['memo'],
      'p_name': h['name'],
    });
    return _position(r);
  }

  static Future<void> deleteHolding(String id) async {
    await db.from('positions').delete().eq('id', id);
  }
}

// ============================================================ PC 서버 (FastAPI)
class _Http {
  static Future<dynamic> send(String method, String path, [Object? body]) async {
    final uri = Uri.parse('$apiBase$path');
    const headers = {'Content-Type': 'application/json'};
    final http.Response res;
    switch (method) {
      case 'POST':
        res = await http.post(uri, headers: headers, body: jsonEncode(body)).timeout(const Duration(minutes: 15));
        break;
      case 'PATCH':
        res = await http.patch(uri, headers: headers, body: jsonEncode(body)).timeout(const Duration(seconds: 30));
        break;
      case 'DELETE':
        res = await http.delete(uri).timeout(const Duration(seconds: 30));
        break;
      default:
        res = await http.get(uri).timeout(const Duration(minutes: 3));
    }
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode != 200) {
      String msg = text;
      try {
        msg = (jsonDecode(text) as Map)['detail']?.toString() ?? text;
      } catch (_) {}
      throw Exception(msg);
    }
    return jsonDecode(text);
  }

  static Future<Json> get(String path) async => asMap(await send('GET', path));
  static Future<List<Json>> getList(String path) async => asList(await send('GET', path));
  static Future<Json> post(String path, Object body) async => asMap(await send('POST', path, body));

  static Future<Json> dashboard() => get('/api/dashboard');
  static Future<Json> v3() async {
    final d = await dashboard();
    final m = asMap(asMap(d['market'])['v3']);
    return m.isEmpty ? m : {...m, 'date': d['date']};
  }
  static Future<List<Json>> allCandidates() async {
    final lists = await Future.wait(['overall', 'signal', 'buy', 'watch']
        .map((k) => candidates(k, 30).then((d) => asList(d['candidates']), onError: (_) => <Json>[])));
    return _uniqueByCode(lists.expand((l) => l));
  }
  static Future<Json> candidates(String list, int top) => get('/api/candidates?list=$list&top=$top');
  static Future<List<Json>> search(String q) => getList('/api/search?q=${Uri.encodeQueryComponent(q)}');
}

/// 종목별로 하나만 (점수 높은 쪽, 전략 태그는 합침)
List<Json> _uniqueByCode(Iterable<Json> cands) {
  final by = <String, Json>{};
  for (final c in cands) {
    final code = '${c['code']}';
    final old = by[code];
    if (old == null) {
      by[code] = Map<String, dynamic>.from(c);
      continue;
    }
    final tags = {...List<String>.from(old['tags'] as List? ?? []), ...List<String>.from(c['tags'] as List? ?? [])};
    if (((c['score'] as num?) ?? 0) > ((old['score'] as num?) ?? 0)) by[code] = Map<String, dynamic>.from(c);
    by[code]!['tags'] = tags.toList();
  }
  return by.values.toList();
}

// ============================================================ 회원 (관리자 승인제, 클라우드 전용)
/// 지금 로그인한 사람이 관리자인지 (AuthGate 가 회원 정보를 읽을 때 채움)
bool isAdminUser = false;

/// 내 회원 정보 {status: pending|approved|rejected, is_admin, email}
Future<Json?> myProfile() async {
  final db = Supabase.instance.client;
  final uid = db.auth.currentUser?.id;
  if (uid == null) return null;
  final r = await db.from('profiles').select().eq('user_id', uid).maybeSingle();
  return r == null ? null : asMap(r);
}

/// (관리자) 전체 회원 — 승인 대기 먼저
Future<List<Json>> listUsers() async {
  final rows = await Supabase.instance.client.from('profiles').select().order('created_at', ascending: false);
  final list = rows.map(asMap).toList();
  int rank(Json u) => u['status'] == 'pending' ? 0 : (u['status'] == 'approved' ? 1 : 2);
  list.sort((a, b) => rank(a).compareTo(rank(b)));
  return list;
}

/// (관리자) 승인 approved / 거절 rejected / 대기로 되돌리기 pending
Future<Json> setUserStatus(String userId, String status) =>
    _Cloud.rpcMap('set_user_status', {'p_user': userId, 'p_status': status});

/// 내 알림 설정 저장 (토픽 '' = 끄기)
Future<Json> saveMyNotify(String topic, bool daily, bool holdings, bool signals) => _Cloud.rpcMap(
    'set_my_notify', {'p_topic': topic, 'p_daily': daily, 'p_holdings': holdings, 'p_signals': signals});

/// 내 토픽으로 테스트 알림
Future<Json> sendTestNotify() => _Cloud.rpcMap('send_test_notify', {});

/// 백테스트 요청 목록 (클라우드 전용)
Future<List<Json>> backtestRequests() => useCloud ? _Cloud.backtestRequests() : Future.value(<Json>[]);
