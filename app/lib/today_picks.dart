import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'live.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 오늘 살 만한 후보 (지금 가격 기준)
///
/// 어제 장 마감 분석으로 고른 모든 후보(종합 + 전략별) 중에서
/// '지금 가격'이 매매계획의 매수 적정구간 근처에 있는 종목만 다시 고른다.
///  - 손절가 아래 / 1차 목표가 도달 / 오늘 +15% 넘게 급등 / -5% 넘게 급락 → 제외
///  - 매수구간 안 → 먼저, 그다음 구간 바로 위(+2% 이내)·바로 아래(-1.5% 이내)
///  - 같은 묶음 안에서는 점수(어제 마감 분석) 높은 순
///  - 시장 필터: 종목이 속한 시장이 하락장(V2 시장 상태 C)이면 제외
///  - '지금 사면' 목표·손절까지 남은 %와 손익비를 지금 가격으로 다시 계산
class TodayPick {
  TodayPick(this.c, this.q, this.zone, this.order, this.up, this.down);
  final Json c;
  final LiveQuote q;
  final String zone; // 매수구간 안 / 구간 바로 위 / 구간 바로 아래
  final int order; // 0 = 구간 안
  final double up; // 지금가 → 1차 목표 (%)
  final double down; // 지금가 → 손절 (%, 음수)

  double get rr => down == 0 ? 0 : up / -down;
  double get score => (c['score'] as num?)?.toDouble() ?? 0;
  Json get plan => asMap(c['plan']);
}

/// 시장 필터: 지수가 N일선(어제 마감 기준 값) 아래인 시장 {'KOSPI','KOSDAQ'}
///   지금 지수가 있으면 지금 값으로, 없으면 어제 마감 판정으로
Set<String> weakMarkets(Json market, Map<String, LiveQuote> indexQuotes) {
  // V2: 시장 상태가 C(하락장)인 시장 → 신규 매수 중단
  final v2 = asMap(asMap(market['v2'])['market']);
  if (v2.isNotEmpty) {
    return {for (final e in v2.entries) if (asMap(e.value)['state'] == 'C') e.key};
  }
  final out = <String>{};
  for (final i in asList(market['indices'])) {
    final code = '${i['code']}';
    final ma = (i['ma_filter'] as num?)?.toDouble();
    final now = indexQuotes[code]?.price;
    if (ma != null && now != null) {
      if (now < ma) out.add(code);
    } else if (i['above_ma_filter'] == false) {
      out.add(code);
    }
  }
  return out;
}

String marketName(String m) => m == 'KOSPI' ? '코스피' : (m == 'KOSDAQ' ? '코스닥' : m);

List<TodayPick> todayPicks(List<Json> cands, Map<String, LiveQuote> quotes,
    {int limit = 10, Set<String> weak = const {}}) {
  final out = <TodayPick>[];
  for (final c in cands) {
    if (weak.contains(c['market'])) continue; // 시장 필터: 약세 시장 종목은 신규 매수 쉬기
    final q = quotes['${c['code']}'];
    if (q == null || q.price <= 0) continue;
    final plan = asMap(c['plan']);
    double? v(String k) => (plan[k] as num?)?.toDouble();
    final lo = v('entry_low'), hi = v('entry_high'), stop = v('stop'), t1 = v('target1');
    if (lo == null || hi == null || stop == null || t1 == null) continue;
    final p = q.price;
    if (p <= stop || p >= t1 || q.ratio >= 15 || q.ratio <= -5) continue;
    String zone;
    int order;
    if (p >= lo && p <= hi) {
      zone = '매수구간 안';
      order = 0;
    } else if (p > hi && p <= hi * 1.02) {
      zone = '구간 바로 위';
      order = 1;
    } else if (p < lo && p >= lo * 0.985) {
      zone = '구간 바로 아래';
      order = 2;
    } else {
      continue;
    }
    out.add(TodayPick(c, q, zone, order, (t1 / p - 1) * 100, (stop / p - 1) * 100));
  }
  out.sort((a, b) => a.order != b.order ? a.order.compareTo(b.order) : b.score.compareTo(a.score));
  return out.take(limit).toList();
}

/// 후보 한 줄: 이름 · 점수 · 지금가 · 오늘 등락 · 지금 사면 목표/손절/손익비
class TodayPickTile extends StatelessWidget {
  const TodayPickTile({super.key, required this.p, required this.rank});
  final TodayPick p;
  final int rank;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = p.c;
    final zoneColor = p.order == 0 ? Colors.green : (p.order == 1 ? Colors.orange : Colors.blueGrey);
    final tags = List<String>.from(c['tags'] as List? ?? []);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: ListTile(
        leading: CircleAvatar(child: Text('$rank')),
        title: StockName('${c['name']}', market: c['market'] as String?, score: p.score, today: c['today_new'] == true),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 4, runSpacing: 2, children: [
            _chip(p.zone, zoneColor),
            if (c['signal'] == true) _chip('매수 신호', upColor),
            if (c['grade'] != null && c['signal'] != true) _chip('${c['grade']}', verdictColor('${c['grade']}')),
            ...tags.map((k) => _chip(strategyLabels[k] ?? k, Colors.teal)),
          ]),
          const SizedBox(height: 2),
          Text('목표 ${pct(p.up)} · 손절 ${pct(p.down)} · 손익비 1:${p.rr.toStringAsFixed(1)}',
              style: t.bodySmall),
        ]),
        isThreeLine: true,
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(num0(p.q.price), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            Text(pct(p.q.ratio),
                style: TextStyle(color: p.q.ratio >= 0 ? upColor : downColor, fontWeight: FontWeight.bold)),
          ],
        ),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => StockDetailScreen(code: c['code'] as String, name: c['name'] as String))),
      ),
    );
  }

  static Widget _chip(String s, Color color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
        child: Text(s, style: TextStyle(fontSize: 11, color: color)),
      );
}

/// 업종 '오늘' 강도: 거래대금 상위 15종목 지금 등락률 가중 평균 (+ 오른 종목 수)
class SectorToday {
  SectorToday(this.g, this.avg, this.up, this.n);
  final Json g;
  final double avg;
  final int up, n;
}

List<SectorToday> sectorsToday(List<Json> sectors, Map<String, LiveQuote> quotes) {
  final out = <SectorToday>[];
  for (final g in sectors) {
    // 저녁 배치가 준 업종 거래대금 상위 15종목·가중치(평소 거래대금)로 가중 평균 — 저녁 리포트 업종 등락과 같은 방식
    final live = asList(g['live']);
    if (live.isNotEmpty) {
      var sw = 0.0, sr = 0.0, up = 0, n = 0;
      for (final m in live) {
        final r = quotes['${m['code']}']?.ratio;
        final w = (m['w'] as num?)?.toDouble() ?? 0;
        if (r == null || w <= 0) continue;
        sw += w;
        sr += w * r;
        n++;
        if (r > 0) up++;
      }
      if (n >= 3 && sw > 0) {
        out.add(SectorToday(g, sr / sw, up, n));
        continue;
      }
    }
    // (예전 리포트) 대표 종목 단순 평균
    final rs = asList(g['top']).map((m) => quotes['${m['code']}']?.ratio).whereType<double>().toList();
    if (rs.isEmpty) continue;
    out.add(SectorToday(g, rs.reduce((a, b) => a + b) / rs.length, rs.where((r) => r > 0).length, rs.length));
  }
  out.sort((a, b) => b.avg.compareTo(a.avg));
  return out;
}
