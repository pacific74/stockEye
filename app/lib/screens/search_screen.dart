import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../recent_search.dart';
import '../widgets/common.dart';
import 'stock_detail_screen.dart';

/// 상단 🔍 종목 검색: 팝업 창, 글자를 칠 때마다 바로 목록 (보유종목 추가와 같은 방식)
///   종목을 누르면 팝업이 닫히고 종목 상세 화면으로
Future<void> showStockSearch(BuildContext context) async {
  final picked = await showDialog<Json>(context: context, builder: (_) => const StockSearchDialog());
  if (picked != null) RecentSearch.add(picked); // 최근 검색 (맨 위로)
  if (picked != null && context.mounted) {
    Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => StockDetailScreen(code: '${picked['code']}', name: '${picked['name']}')));
  }
}

class StockSearchDialog extends StatefulWidget {
  const StockSearchDialog({super.key});

  @override
  State<StockSearchDialog> createState() => _StockSearchDialogState();
}

class _StockSearchDialogState extends State<StockSearchDialog> {
  final _c = TextEditingController();
  Timer? _debounce;
  int _seq = 0; // 늦게 도착한 예전 검색 결과는 버림
  List<Json> _rows = [];
  bool _busy = false;
  String? _error;
  List<Map<String, String>> _recent = []; // 최근 검색 종목 (입력창이 비었을 때 보임)

  @override
  void initState() {
    super.initState();
    RecentSearch.load().then((r) {
      if (mounted) setState(() => _recent = r);
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _c.dispose();
    super.dispose();
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    final q = v.trim();
    if (q.isEmpty) {
      _seq++;
      setState(() {
        _rows = [];
        _busy = false;
        _error = null;
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 250), () => _search(q));
  }

  Future<void> _search(String q) async {
    final my = ++_seq;
    setState(() => _busy = true);
    try {
      final r = await Api.search(q);
      if (!mounted || my != _seq) return;
      setState(() {
        _rows = r;
        _busy = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted || my != _seq) return;
      setState(() {
        _busy = false;
        _error = '검색 실패: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final q = _c.text.trim();
    Widget body;
    if (_error != null) {
      body = Padding(padding: const EdgeInsets.all(16), child: Text(_error!, style: const TextStyle(color: Colors.redAccent)));
    } else if (q.isEmpty && _recent.isNotEmpty) {
      body = ListView(shrinkWrap: true, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 8, 0),
          child: Row(children: [
            Expanded(child: Text('최근 검색', style: t.labelMedium?.copyWith(color: Colors.grey))),
            TextButton(
                onPressed: () {
                  RecentSearch.clear();
                  setState(() => _recent = []);
                },
                child: const Text('전체 삭제')),
          ]),
        ),
        for (final r in _recent)
          ListTile(
            dense: true,
            title: Row(children: [
              Flexible(child: Text(r['name'] ?? '', overflow: TextOverflow.ellipsis)),
              MarketBadge(r['market']?.isEmpty ?? true ? null : r['market']),
            ]),
            subtitle: Text(r['code'] ?? ''),
            trailing: IconButton(
                icon: const Icon(Icons.close, size: 18),
                tooltip: '목록에서 지움',
                onPressed: () {
                  RecentSearch.remove(r['code'] ?? '');
                  setState(() => _recent = _recent.where((x) => x['code'] != r['code']).toList());
                }),
            onTap: () => Navigator.pop(context, <String, dynamic>{'code': r['code'], 'name': r['name'], 'market': r['market']}),
          ),
      ]);
    } else if (q.isEmpty) {
      body = Padding(padding: const EdgeInsets.all(16), child: Text('입력하면 아래에 목록이 나옵니다', style: t.bodySmall));
    } else if (_rows.isEmpty && !_busy) {
      body = Padding(padding: const EdgeInsets.all(16), child: Text('"$q" 에 맞는 종목이 없습니다', style: t.bodySmall));
    } else {
      body = ListView.builder(
        shrinkWrap: true,
        itemCount: _rows.length,
        itemBuilder: (_, i) {
          final r = _rows[i];
          return ListTile(
            dense: true,
            title: Row(children: [
              Flexible(child: Text('${r['name']}', overflow: TextOverflow.ellipsis)),
              MarketBadge(r['market'] as String?),
            ]),
            subtitle: Text('${r['code']}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.pop(context, r),
          );
        },
      );
    }
    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 40),
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420, maxHeight: 520),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
            child: Row(children: [
              Expanded(child: Text('종목 검색', style: t.titleMedium)),
              IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              controller: _c,
              autofocus: true,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: '종목명 또는 코드 (예: 삼성전자 / 005930)',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _busy
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)))
                    : (q.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            onPressed: () {
                              _c.clear();
                              _onChanged('');
                            })),
                border: const OutlineInputBorder(),
              ),
              onChanged: _onChanged,
              onSubmitted: (_) {
                if (_rows.isNotEmpty) Navigator.pop(context, _rows.first); // 엔터 → 첫 번째 종목
              },
            ),
          ),
          const SizedBox(height: 4),
          Flexible(child: body),
          const SizedBox(height: 8),
        ]),
      ),
    );
  }
}
