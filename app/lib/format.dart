import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

final _won = NumberFormat('#,###');

String won(num? v) => v == null ? '-' : '${_won.format(v)}원';
String num0(num? v) => v == null ? '-' : _won.format(v);
String pct(num? v, {bool sign = true}) =>
    v == null ? '-' : '${sign && v > 0 ? '+' : ''}${v.toStringAsFixed(1)}%';
String stars(int n) => '★' * n + '☆' * (5 - n);

const Color upColor = Color(0xFFD32F2F); // 한국식: 상승 빨강
const Color downColor = Color(0xFF1565C0); // 하락 파랑

Color verdictColor(String v) {
  if (v.startsWith('과열') || v.startsWith('업종 약세') || v.startsWith('시장 하락장')) return Colors.orange;
  switch (v) {
    case '매수 신호':
      return upColor;
    case '강력 후보':
      return Colors.deepOrange;
    case '매수 후보':
      return Colors.green;
    case '매수 차단':
      return Colors.redAccent;
    case '매수 고려':
      return upColor;
    case '눌림 대기':
      return Colors.orange;
    case '관심':
      return Colors.teal;
    default:
      return Colors.grey;
  }
}
