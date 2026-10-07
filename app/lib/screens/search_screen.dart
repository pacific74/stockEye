import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets/nav.dart';
import 'stock_detail_screen.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  List<Json> _rows = [];
  String? _error;

  Future<void> _search(String q) async {
    if (q.trim().isEmpty) return;
    try {
      final r = await Api.search(q.trim());
      setState(() {
        _rows = r;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      bottomNavigationBar: const MainNavBar(),
      appBar: AppBar(
        title: TextField(
          autofocus: true,
          decoration: const InputDecoration(hintText: '종목명 또는 코드', border: InputBorder.none),
          onSubmitted: _search,
        ),
      ),
      body: _error != null
          ? Center(child: Text(_error!))
          : ListView(
              children: _rows
                  .map((r) => ListTile(
                        title: Text('${r['name']}'),
                        subtitle: Text('${r['code']}  ${r['market'] ?? ''}'),
                        onTap: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                                builder: (_) => StockDetailScreen(code: r['code'] as String, name: r['name'] as String))),
                      ))
                  .toList(),
            ),
    );
  }
}
