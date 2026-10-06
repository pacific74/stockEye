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
  switch (v) {
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
