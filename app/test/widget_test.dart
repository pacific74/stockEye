import 'package:flutter_test/flutter_test.dart';
import 'package:stockeye/api.dart';

void main() {
  test('빈 값도 안전하게 변환', () {
    expect(asMap(null), isEmpty);
    expect(asList(null), isEmpty);
    expect(asList([{'a': 1}]).first['a'], 1);
  });
}
