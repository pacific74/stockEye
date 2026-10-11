import 'package:flutter/material.dart';

import 'api.dart';
import 'format.dart';
import 'plan_line.dart';
import 'screens/stock_detail_screen.dart';
import 'widgets/common.dart';

/// 추세전환 (실험 탭 · 관찰용) — 바닥에서 20일선이 수평 → 상승으로 도는 종목, 100점 (소수점 점수)
///   ① 하락·바닥 15 ② 바닥 횡보 25 ③ 이평 전환 35 ④ 초기 반등 15 ⑤ 거래량·변동성 10
///   70점 이상 후보 · 80점 이상 우선 관찰 · 매매 규칙 없음 (V3 기준 전략과 별개)

/// 실험 탭 설정: 후보 dict 의 필드 · 항목 순서 · 이름 · 기준 설명
/// 점수 항목 설명 (종목 상세의 점수표 아래에 작게)
const partDescs = {
  // V3
  'vola15': '하루 평균 변동폭이 작을수록 높음',
  'fin25': '수익성·성장성·부채 등 재무가 좋을수록 높음',
  'pos20': '20·60일선이나 지지선 근처로 조정받았을수록 높음',
  'trend5': '60일선 위 · 60일선 상승 · 20일선이 60일선 위',
  'vol5': '최근 5일 거래량이 평소와 비슷하면 높음 (2배 넘게 급증하면 0)',
  'value5': '20일 평균 거래대금이 클수록 높음',
  'flow10': '최근 외국인·기관 순매수가 많을수록 높음',
  'news15': '최근 공시의 호재·악재 (악재일수록 낮음)',
  // 익일유망주
  'trendA': '종가와 20일선 위치 · 20/60일선 방향 · 20일 고점 대비 위치',
  'volB': '오늘·5일 거래량과 거래대금이 평소보다 늘었는지 (대량 거래에 약한 종가면 감점)',
  'priceC': '종가가 하루 범위 위쪽인지 · 20일 고점/박스 상단에 가까운지 · 윗꼬리·장대음봉 없는지',
  'movD': '하루 변동폭(ATR)이 적당한지 · 좁은 범위 뒤 확장 조짐',
  'rsE': '오늘·5일 수익률이 코스피/코스닥 지수보다 강한지',
  'newsF': '최근 공시의 호재·악재 (뉴스 기사는 미반영)',
  // 상승초기
  'trend25': '종가가 20일선 위로 회복 · 20일선 상승 전환 · 5일선 > 20일선',
  'mom20': '5·20일 수익률과 20일 저점 대비 반등 폭 (너무 크면 감점)',
  'mid20': '60일선 기울기 · 20일선이 60일선보다 강해지는 중인지',
  'vol20': '거래량 증가 · 상승일 거래량 우위 · 거래대금 규모',
  'risk15': 'ATR·RSI·20일선 이격으로 본 과열 여부 (과열이면 감점)',
  // 추세전환
  'bottom15': '60일 고점 대비 하락 폭 (30~40% 하락이 만점, 너무 크면 감점)',
  'base25': '최근 20일 횡보 폭 · 저점 유지 · 바닥권에 머문 기간',
  'ma35': '20일선 하락이 멈추고 상승으로 도는지 · 60일선 하락 멈춤',
  'rebound15': '20일선 근처 회복 · 5일 소폭 상승 · 양봉 마감',
  'volume10': '변동폭·거래량이 줄었다가 상승일 거래량이 많아지는지',
  // 상파
  'limit20': '상한가 종가 유지 여부 · 종가 위치 · 그날 거래대금',
  'vol25': 'B: 거래량 감소율과 거래대금 유지 / A: 평소 대비 거래량',
  'pull20': 'B: 음봉 크기·종가 위치·상한가일 저가 지지 / A: 종가 강도',
  'liq15': '20일 평균 거래대금 (클수록 높음)',
  'trend10': '20·60일선 추세 · 20일 수익률',
  'risk10': '공시 위험 (위험할수록 감점)',
};

class ExpKind {
  const ExpKind(this.field, this.title, this.parts, this.note);
  final String field, title, note;
  final List<String> parts;
}

const reversalKind = ExpKind('reversal', '추세전환', ['bottom15', 'base25', 'ma35', 'rebound15', 'volume10'],
    '기준 사이를 직선으로 이어 소수점까지 계산 · 70점 이상 후보 · 80점 이상 우선 관찰 · 관찰용 (매매 규칙 없음)');

/// 상한가 파동 V1: A 상한가 도달·종가 / B 상한가 다음 날 거래량 감소 음봉 (B1~B4)
const uplimitKind = ExpKind('uplimit', '상파', ['limit20', 'vol25', 'pull20', 'liq15', 'trend10', 'risk10'],
    '정렬용 보조 점수 (80점 이상이어도 점수만으로 매수하지 않음) · 관찰용 · 다음 날 지지·거래량 확인');

/// 상승초기형 V1: 20일선 회복 + 단기 상승 시작
const earlyKind = ExpKind('early', '상승초기', ['trend25', 'mom20', 'mid20', 'vol20', 'risk15'],
    '기준 사이를 직선으로 이어 소수점까지 계산 · 80↑ 우선 관찰 · 70~79 관찰 후보 · 60~69 보류 · 관찰용 (매매 규칙 없음)');

const reversalParts = ['bottom15', 'base25', 'ma35', 'rebound15', 'volume10'];

Color reversalColor(num? s) => s == null
    ? Colors.grey
    : s >= 80
        ? Colors.deepPurple
        : s >= 70
            ? Colors.indigo
            : Colors.blueGrey;

/// 목록 한 줄: 총점(소수점) · 판정 · 5개 항목
class ReversalTile extends StatelessWidget {
  const ReversalTile({super.key, required this.c, required this.rank, this.kind = reversalKind, this.price});
  final Json c;
  final int rank;
  final ExpKind kind;
  final double? price;

  @override
  Widget build(BuildContext context) {
    final v = asMap(c[kind.field]);
    final score = v['score'] as num?;
    final col = reversalColor(score);
    return WatchTile(
      c: c,
      price: price,
      tab: kind.field,
      leading: CircleAvatar(child: Text('$rank')),
      score: Text(score == null ? '-' : '${score.toStringAsFixed(1)}점',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: col)),
      onTap: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => StockDetailScreen(code: '${c['code']}', name: '${c['name']}', source: kind.field))),
    );
  }
}

/// 종목 상세: 추세전환 점수 5개 항목 막대 + 세부 14개 (펼쳐 보기)
class ReversalScore extends StatelessWidget {
  const ReversalScore({super.key, required this.v, this.kind = reversalKind, this.detail = false});
  final Json v;
  final ExpKind kind;
  final bool detail; // 종목 상세: 제목 줄 없이 항목별 점수 + 항목 설명

  Widget _bar(String label, num? got, num max, {bool small = false}) => Padding(
        padding: EdgeInsets.symmetric(vertical: small ? 1 : 3),
        child: Row(children: [
          SizedBox(width: small ? 128 : 96, child: Text(label, style: TextStyle(fontSize: small ? 12 : null))),
          Expanded(
            child: LinearProgressIndicator(
              value: got == null ? 0 : (got / max).clamp(0, 1).toDouble(),
              minHeight: small ? 5 : 8,
              color: small ? Colors.indigo.shade200 : Colors.indigo,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
        ]),
      );

  static String excl(Json v) {
    final ex = v['excluded'];
    return (ex is List && ex.isNotEmpty) ? ' (제외: ${ex.join(', ')})' : ' (매수 차단·1차 필터로 목록 제외)';
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final parts = asMap(v['parts']), labels = asMap(v['labels']), maxes = asMap(v['maxes']);
    final subs = asList(v['subs']);
    final score = v['score'] as num?;
    final col = reversalColor(score);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (!detail)
        Text('${kind.title} ${score == null ? '-' : score.toStringAsFixed(1)}점 · ${v['label'] ?? ''}'
            '${v['eligible'] == true ? '' : excl(v)}',
            style: t.bodySmall?.copyWith(fontWeight: FontWeight.w600, color: col)),
      for (final k in kind.parts) ...[
        _bar('${labels[k] ?? k}', parts[k] as num?, (maxes[k] as num?) ?? 1),
        if (detail && partDescs[k] != null)
          Padding(
            padding: const EdgeInsets.only(left: 2, bottom: 4),
            child: Text(partDescs[k]!, style: t.bodySmall?.copyWith(color: Colors.grey)),
          ),
      ],
      if (subs.isNotEmpty)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            dense: true,
            title: Text('세부 항목 ${subs.length}개', style: t.bodySmall),
            children: [
              for (final s in subs) _bar('${s['label']}', s['score'] as num?, (s['max'] as num?) ?? 1, small: true),
            ],
          ),
        ),
      Text('${kind.note} ${v['version'] ?? ''}',
          style: t.bodySmall),
    ]);
  }
}
