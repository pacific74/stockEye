import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'widgets/common.dart';

/// 통계 > 시장·업종 (2026-10-14): 당일단타 매수 → 청산 구간의 시장·업종 흐름과 결과의 관계
///   저녁 배치 "당일매매 시장·업종 기록" 이 매일 쌓음 (system_status 'intraday_ctx' · 최근 40거래일)
///   목적: 시장 필터(시장이 빠질 때 진입 보류 등)·진입 시간을 숫자로 정하기 — 30~50건 쌓인 뒤 판단
///   시장 = ETF 1분봉 (코스피 KODEX200 · 코스닥 KODEX코스닥150) · 업종 = KRX 업종 전체 시가총액 가중 (그 종목 제외)
class IntradayCtxTab extends StatefulWidget {
  const IntradayCtxTab({super.key});
  @override
  State<IntradayCtxTab> createState() => _IntradayCtxTabState();
}

class _IntradayCtxTabState extends State<IntradayCtxTab> with AutomaticKeepAliveClientMixin {
  late Future<List<Json>> _f = _load();
  static Future<List<Json>> _load() => Future.wait([Api.statusKey('intraday_ctx'), Api.statusKey('closingbet_nxt')]);

  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final t = Theme.of(context).textTheme;
    return RefreshIndicator(
      onRefresh: () async => setState(() => _f = _load()),
      child: FutureBuilder<List<Json>>(
        future: _f,
        builder: (context, snap) {
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final d = snap.data![0];
          final nx = snap.data![1]; // 종가배팅 × NXT (애프터·프리마켓)
          final st = asMap(d['stats']);
          final all = asMap(st['all']);
          final rows = asList(d['rows']).reversed.toList(); // 최근 것 위
          return ListView(padding: const EdgeInsets.fromLTRB(12, 10, 12, 32), children: [
            Text('당일단타 × 시장·업종', style: t.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 2),
            Text(
                '매수부터 이익실현·손절까지 같은 구간의 시장(ETF)·업종(업종 전체 시가총액 가중) 흐름과 결과를 매일 저녁 쌓아요. '
                '30~50건 모이면 "시장이 빠질 때 진입 보류", "진입 시간 제한" 같은 조건을 숫자로 정해요.',
                style: t.bodySmall?.copyWith(color: Colors.grey)),
            const SizedBox(height: 8),
            if ((all['n'] ?? 0) == 0)
              const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('아직 기록이 없어요. 당일단타 결과가 나온 날 저녁 배치부터 쌓여요.')))
            else ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: '최근 ${d['days'] ?? 0}거래일 · 끝난 ${all['n']}건   ', style: t.titleSmall),
                    TextSpan(text: '승률 ${all['win']}%   ', style: t.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
                    TextSpan(
                        text: '평균 ${_p(all['pnl'])}',
                        style: t.titleSmall?.copyWith(color: ((all['pnl'] as num?) ?? 0) >= 0 ? upColor : downColor)),
                    TextSpan(text: '   (비용 0.25% 뺀 손익 · ${d['updated'] ?? ''} 갱신)', style: t.bodySmall?.copyWith(color: Colors.grey)),
                  ])),
                ),
              ),
              _grid(context, [
                for (final g in asList(st['groups']))
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${g['title']}', style: t.titleSmall),
                        const SizedBox(height: 4),
                        StatTable(header: const ['구간', '건수', '승률', '평균 손익', '합계'], boldFirst: false, firstFlex: 2, rows: [
                          for (final r in asList(g['rows']))
                            [
                              StatCell('${r['label']}'),
                              StatCell('${r['n'] ?? 0}'),
                              StatCell((r['n'] ?? 0) == 0 ? '-' : '${r['win']}%'),
                              pnlCell(r['pnl'] as num?, bold: true),
                              pnlCell(r['sum'] as num?, d: 1),
                            ],
                        ]),
                      ]),
                    ),
                  ),
              ]),
              const SizedBox(height: 8),
              Text('건별 기록 (최근 순)', style: t.titleSmall),
              const SizedBox(height: 4),
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(8, 6, 8, 6),
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SizedBox(
                      width: 980,
                      child: StatTable(
                        boldFirst: false,
                        firstFlex: 2.6,
                        header: const ['날짜 · 종목', '진입~청산', '결과', '손익', '시장', '업종', '종목−시장', '진입전30분 시장', '진입전10분', '시장 상관', '업종'],
                        rows: [
                          for (final r in rows.take(200))
                            [
                              StatCell('${'${r['date'] ?? ''}'.length >= 10 ? '${r['date']}'.substring(5) : ''} ${r['name'] ?? ''}'),
                              StatCell('${r['entry'] ?? ''}~${r['exit'] ?? ''}'),
                              StatCell('${r['result'] ?? ''}',
                                  color: r['result'] == '이익실현' ? upColor : (r['result'] == '손절' ? downColor : null)),
                              pnlCell(r['pnl'] as num?, bold: true),
                              pnlCell(r['mkt'] as num?),
                              pnlCell(r['sec'] as num?),
                              pnlCell(r['vs_mkt'] as num?),
                              pnlCell(r['mkt_pre30'] as num?),
                              pnlCell(r['mkt_pre10'] as num?),
                              StatCell(r['corr_mkt'] == null ? '-' : (r['corr_mkt'] as num).toStringAsFixed(2)),
                              StatCell('${r['sector'] ?? '-'}'),
                            ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              _cbNxt(context, nx),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                    '시장 = 코스피 KODEX200 · 코스닥 KODEX코스닥150 1분봉 · 업종 = KRX 업종(시총 상위 90%, 그 종목 제외) · '
                    '상관 = 보유 중 1분 수익률이 시장과 같이 움직인 정도 (1 = 똑같이) · 날을 넘긴 상한가포착·종가배팅은 아직 빠져 있음',
                    style: t.bodySmall?.copyWith(color: Colors.grey)),
              ),
            ],
          ]);
        },
      ),
    );
  }

  /// 종가배팅 × NXT: 산 날 저녁 애프터마켓(종가 대비) · 다음 날 아침 프리마켓(전일 종가 대비) 구간별 결과
  Widget _cbNxt(BuildContext context, Json nx) {
    final t = Theme.of(context).textTheme;
    final st = asMap(nx['stats']);
    final all = asMap(st['all']);
    final rows = asList(nx['rows']).reversed.toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('종가배팅 × 넥스트레이드(NXT)', style: t.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
      Text('산 날 저녁 애프터마켓(15:30~20:00) 가격과 다음 날 프리마켓(08:00~08:50) 가격이 결과와 관계있는지 — '
          '관계가 보이면 저녁·08시대 조기 매도 규칙을 넣어요',
          style: t.bodySmall?.copyWith(color: Colors.grey)),
      const SizedBox(height: 6),
      if ((all['n'] ?? 0) == 0)
        const Padding(padding: EdgeInsets.all(16), child: Text('아직 기록이 없어요. 종가배팅을 산 다음 날 저녁부터 쌓여요.'))
      else ...[
        Text('끝난 ${all['n']}건 · 승률 ${all['win']}% · 평균 ${_p(all['pnl'])}', style: t.titleSmall),
        _grid(context, [
          for (final g in asList(st['groups']))
            Card(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${g['title']}', style: t.titleSmall),
                  StatTable(header: const ['구간', '건수', '승률', '평균 손익', '합계'], boldFirst: false, firstFlex: 2, rows: [
                    for (final r in asList(g['rows']))
                      [
                        StatCell('${r['label']}'),
                        StatCell('${r['n'] ?? 0}'),
                        StatCell((r['n'] ?? 0) == 0 ? '-' : '${r['win']}%'),
                        pnlCell(r['pnl'] as num?, bold: true),
                        pnlCell(r['sum'] as num?, d: 1),
                      ],
                  ]),
                ]),
              ),
            ),
        ]),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: StatTable(boldFirst: false, firstFlex: 2.4, header: const ['날짜 · 종목', '매수', '결과', '손익', '애프터', '다음날 프리'], rows: [
              for (final r in rows.take(60))
                [
                  StatCell('${'${r['date'] ?? ''}'.length >= 10 ? '${r['date']}'.substring(5) : ''} ${r['name'] ?? ''}'),
                  StatCell('${r['buy_time'] ?? '-'}'),
                  StatCell('${r['result'] ?? ''}',
                      color: r['result'] == '이익실현' ? upColor : (r['result'] == '손절' ? downColor : null)),
                  pnlCell(r['pnl'] as num?, bold: true),
                  pnlCell(r['after'] as num?),
                  pnlCell(r['pre'] as num?),
                ],
            ]),
          ),
        ),
      ],
    ]);
  }

  static String _p(dynamic v) => v == null ? '-' : '${(v as num) >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%';

  /// 넓은 화면: 통계 카드를 옆으로 (약 420 폭) · 좁으면 한 줄에 하나
  Widget _grid(BuildContext context, List<Widget> cards) => LayoutBuilder(builder: (context, c) {
        final n = ((c.maxWidth + 8) / 428).floor().clamp(1, 4);
        if (n == 1) return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: cards);
        final w = (c.maxWidth - 8 * (n - 1)) / n;
        return Wrap(spacing: 8, children: [for (final x in cards) SizedBox(width: w, child: x)]);
      });
}
