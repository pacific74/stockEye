import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'live.dart';
import 'nextday.dart' show gradeColor, liveColor;
import 'widgets/common.dart';

/// 후보 카드 아래 한 줄: 매수구간 여부 칩 + "지금 사면 목표 +x% · 손절 -y% · 손익비 1:z"
///   가격 = 지금 시세(있으면) 또는 분석일 종가. 목표 = 1차 목표가, 손절 = 손절가 (차트 지지·저항 기준)
class PlanStatus {
  PlanStatus(this.zone, this.color, this.up, this.down);
  final String zone;
  final Color color;
  final double? up; // 가격 → 1차 목표 (%)
  final double? down; // 가격 → 손절 (%, 음수)
  double? get rr => (up == null || down == null || down! >= 0) ? null : up! / -down!;

  static PlanStatus? of(Json c, double? price) {
    final p = asMap(c['plan']);
    double? v(String k) => (p[k] as num?)?.toDouble();
    final px = price ?? v('price');
    final lo = v('entry_low'), hi = v('entry_high'), t1 = v('target1'), st = v('stop');
    if (px == null || px <= 0) return null;
    String zone;
    Color color;
    if (st != null && px <= st) {
      zone = '손절가 아래';
      color = downColor;
    } else if (lo != null && hi != null && px >= lo && px <= hi) {
      zone = '매수구간 안';
      color = Colors.green;
    } else if (hi != null && px > hi && px <= hi * 1.02) {
      zone = '구간 바로 위';
      color = Colors.orange;
    } else if (hi != null && px > hi) {
      zone = '구간 위 (추격 주의)';
      color = Colors.grey;
    } else if (lo != null && px < lo) {
      zone = '구간 아래';
      color = Colors.blueGrey;
    } else {
      zone = '구간 정보 없음';
      color = Colors.grey;
    }
    return PlanStatus(zone, color, t1 == null ? null : (t1 / px - 1) * 100, st == null ? null : (st / px - 1) * 100);
  }
}

Widget planChip(String s, Color color) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.13), borderRadius: BorderRadius.circular(6)),
      child: Text(s, style: TextStyle(fontSize: 11, color: color)),
    );

class PlanLine extends StatelessWidget {
  const PlanLine(
      {super.key,
      required this.c,
      this.price,
      this.live = false,
      this.extraChips = const [],
      this.showPrice = false,
      this.tab,
      this.firstRowReserve = 0});
  final Json c;
  final double? price;
  final bool live; // true = 지금 시세 기준, false = 분석일 종가 기준
  final List<Widget> extraChips;
  final bool showPrice; // (예전) 관심 탭 목록 — 현재가는 이제 카드 오른쪽 위(WatchTile), 매수구간은 상태 칩 옆
  final String? tab; // 어느 탭 종목인지 → 탭별 유형·태그 칩과 확인 가격 줄
  final double firstRowReserve; // 첫 줄 오른쪽 비워 둘 폭 (카드 오른쪽 위 점수와 겹치지 않게)

  @override
  Widget build(BuildContext context) {
    final s = PlanStatus.of(c, price);
    if (s == null) return const SizedBox.shrink();
    final tags = (c['tags'] is List) ? (c['tags'] as List).map((e) => '$e').toList() : <String>[];
    final p = asMap(c['plan']);
    final lo = p['entry_low'] as num?, hi = p['entry_high'] as num?;
    final zoneTxt = lo != null && hi != null ? '${num0(lo)}~${num0(hi)}' : null;
    final alert = c['market_alert'] as String?;
    final tc = tabChipTexts(c, tab);
    final seen = tc.map((e) => e.$1).toSet();
    final chips = [for (final x in tc) planChip(x.$1, x.$2)];
    final watch = tabWatch(context, c, tab);
    final news = asMap(c['news']);
    final nl = news['level'] as String?;
    final zoneRow = infoBoxes([
      // 최근 3일 뉴스 악재 (심각 = 4개 탭에선 이미 제외, V3·보유는 경고만)
      if (nl == 'neg' || nl == 'severe')
        InfoBox('⚠ 뉴스 ${news['word'] ?? '악재'}${c['news_delta'] is num ? ' ${(c['news_delta'] as num).toStringAsFixed(1)}점' : ''}',
            color: nl == 'severe' ? Colors.red : Colors.orange, bold: true, fill: true),
      planChip(s.zone, s.color),
      // 매수구간 칩 옆에 구간 가격
      if (zoneTxt != null) InfoBox('매수구간 $zoneTxt', color: s.color),
      ...chips,
      ...extraChips,
      for (final tg in tags.where((x) => !seen.contains(x)).take(2)) planChip(strategyLabels[tg] ?? tg, Colors.blueGrey),
    ]);
    final pad = EdgeInsets.only(right: firstRowReserve);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      // 지수·업종 급락 → 매수 주의 (첫 줄)
      if (alert != null)
        Padding(padding: const EdgeInsets.only(top: 3).add(pad), child: InfoBox('⚠ $alert', color: Colors.orange, bold: true, fill: true)),
      const SizedBox(height: 3),
      // 매수구간 상태 + 탭별 유형·태그 (같은 글자는 한 번만) — 경고가 없으면 이 줄이 첫 줄
      alert == null ? Padding(padding: pad, child: zoneRow) : zoneRow,
      if (watch != null) Padding(padding: const EdgeInsets.only(top: 3), child: watch),
      if (s.up != null && s.down != null)
        Padding(
          padding: const EdgeInsets.only(top: 3),
          child: infoBoxes([
            InfoBox('목표 ${pct(s.up)}', color: upColor),
            InfoBox('손절 ${pct(s.down)}', color: downColor),
            if (s.rr != null) InfoBox('손익비 1:${s.rr!.toStringAsFixed(1)}'),
          ]),
        ),
    ]);
  }
}

/// 관심 탭 목록 카드 (V3 · 유망주 · 상승초기 · 추세전환 · 상파 공통)
///   [순위]  종목명 [시장] [84.8점]        현재가 48,300원
///          [업종 급락 주의] / [매수구간 안] [매수구간 47,400~48,800] / [목표] [손절] [손익비]
///   아래 줄들은 카드 오른쪽 끝까지 써서 한 줄에 들어가게
class WatchTile extends StatelessWidget {
  const WatchTile(
      {super.key,
      required this.c,
      required this.leading,
      this.score,
      this.scoreDigits = 1,
      this.price,
      this.tab,
      this.onTap,
      this.extra});
  final Json c;
  final Widget leading;
  final num? score; // 종목명 옆 점수 배지
  final int scoreDigits;
  final double? price; // 지금 시세 (없으면 분석일 종가)
  final String? tab;
  final VoidCallback? onTap;
  final Widget? extra; // 맨 아래 한 줄 더 (메인: 넥스트레이드 시세)

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    // 정규장 밖 넥스트레이드 거래 중(08:00~08:50 · 15:40~20:00)이면 현재가 = NXT 가격 (2026-10-16)
    final lq = Live.last['${c['code']}'];
    final nxt = lq?.nxtOn ?? false;
    final px = nxt ? lq!.overPrice : (price ?? (asMap(c['plan'])['price'] as num?)?.toDouble());
    final livePx = nxt ? lq!.overPrice : price;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            leading,
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                // 종목명 [시장] [점수]  ·····  현재가 [등락률]
                //   종목명은 크게 (2026-10-14: 이름이 '셀…' 처럼 잘려 안 보였음)
                //   좁은 화면(폰): 1줄 = 종목명·시장·점수, 2줄 = 현재가·등락률 / 넓은 화면: 한 줄
                LayoutBuilder(builder: (context, box) {
                  final name = StockName('${c['name']}',
                      market: c['market'] as String?,
                      score: score,
                      scoreDigits: scoreDigits,
                      today: c['today_new'] == true,
                      style: t.titleMedium?.copyWith(fontSize: 17, fontWeight: FontWeight.bold));
                  final priceW = Row(mainAxisSize: MainAxisSize.min, children: [
                    if (px != null)
                      Text.rich(TextSpan(children: [
                        TextSpan(
                            text: nxt ? 'NXT ' : (price != null ? '현재가 ' : '기준가 '),
                            style: t.bodySmall?.copyWith(color: nxt ? Colors.purple.shade200 : Colors.grey)),
                        TextSpan(text: won(px), style: t.bodyMedium?.copyWith(fontWeight: FontWeight.bold)),
                      ])),
                    // 오늘 등락률 (NXT 중이면 정규장 가격 대비 NXT 등락 + 정규장 가격)
                    ChgBadge(nxt ? lq!.nxtRatio : lq?.ratio),
                    if (nxt)
                      Padding(
                        padding: const EdgeInsets.only(left: 4),
                        child: Text('${num0(lq!.price)} 대비', style: t.bodySmall?.copyWith(color: Colors.grey, fontSize: 11)),
                      ),
                  ]);
                  if (box.maxWidth < 520) {
                    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      name,
                      Padding(padding: const EdgeInsets.only(top: 2), child: priceW),
                    ]);
                  }
                  return Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
                    Expanded(child: name),
                    const SizedBox(width: 6),
                    priceW,
                  ]);
                }),
                StockInfoLine('${c['code']}'),
                PlanLine(c: c, price: livePx, live: livePx != null, tab: tab),
                if (extra != null) extra!,
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}


/// 뉴스 제목 호재(+1)·악재(-1)·중립(0) — 서버 engine/news.py 키워드와 같은 목록
int newsTone(String title) {
  const neg = ['유상증자', '전환사채', '신주인수권부사채', '교환사채', '횡령', '배임', '소송', '감자', '불성실공시', '관리종목',
      '거래정지', '감사의견', '상장적격성', '회생', '부도', '최대주주변경', '투자주의', '투자경고', '투자위험', '상장폐지'];
  const pos = ['공급계약', '수주', '자기주식취득', '자사주', '무상증자', '특허', '기술이전', '흑자전환', '주식소각'];
  final t = title.replaceAll(' ', '');
  if (neg.any(t.contains)) return -1;
  if (pos.any(t.contains)) return 1;
  return 0;
}

/// 탭별 유형·태그·경고 칩 글자와 색 (관심 목록 · 메인 금일 관심주 · 종목 상세 공통)
List<(String, Color)> tabChipTexts(Json c, String? tab) {
  final out = <(String, Color)>[];
  if (tab == 'nextday') {
    final v = asMap(c['nextday']);
    if (v.isEmpty) return out;
    if (v['type'] != null) out.add(('${v['type']}', gradeColor(v['grade'] as String?)));
    for (final tg in (v['tags'] as List? ?? const [])) {
      out.add(('$tg', Colors.orange));
    }
  } else if (tab == 'uplimit') {
    final v = asMap(c['uplimit']);
    if (v.isEmpty) return out;
    if (v['label'] != null) out.add(('${v['label']}', Colors.red));
    for (final w in (v['warnings'] as List? ?? const []).take(2)) {
      out.add(('$w'.split(' — ').first, Colors.orange));
    }
    final live = asMap(v['live']);
    if (live.isNotEmpty) out.add(('${live['status']}', Colors.teal));
  }
  // 같은 글자 한 번만
  final seen = <String>{};
  return [for (final x in out) if (seen.add(x.$1)) x];
}

/// 탭별 확인 가격 줄: 유망주 = 종가·돌파·지지·추격 금지 (장중이면 지금 상태), 상파 = 지지 가격
Widget? tabWatch(BuildContext context, Json c, String? tab) {
  final t = Theme.of(context).textTheme;
  if (tab == 'nextday') {
    final v = asMap(c['nextday']);
    final w = asMap(v['watch']), live = asMap(v['live']);
    String p(num? x) => x == null ? '-' : '${x >= 0 ? '+' : ''}${x.toStringAsFixed(1)}%';
    if (live.isNotEmpty) {
      return Text('${live['time']} 지금 ${num0(live['price'] as num?)} (${p(live['chg'] as num?)}) · 시초 갭 ${p(live['gap'] as num?)} · ${live['status']}',
          style: t.bodySmall?.copyWith(color: liveColor(live['status'] as String?), fontWeight: FontWeight.w600));
    }
    if (w.isEmpty) return null;
    return infoBoxes([
      InfoBox('종가 ${num0(w['close'] as num?)}'),
      InfoBox('돌파 ${num0(w['breakout'] as num?)}', color: upColor),
      InfoBox('지지 ${num0(w['support'] as num?)}', color: downColor),
      InfoBox('추격 금지 ${num0(w['no_chase'] as num?)}↑', color: Colors.orange),
    ]);
  }
  if (tab == 'uplimit') {
    final w = asMap(asMap(c['uplimit'])['watch']);
    if (w['support'] == null) return null;
    return infoBoxes([InfoBox('지지 ${num0(w['support'] as num?)} (${w['support_label'] ?? '상한가 당일 저가'})', color: downColor)]);
  }
  return null;
}
