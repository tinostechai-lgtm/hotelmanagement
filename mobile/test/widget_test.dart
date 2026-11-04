import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:servora/brand/logo.dart';

void main() {
  testWidgets('Animated Servora logo renders and completes', (tester) async {
    var done = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Center(child: AnimatedServoraLogo(onCompleted: () => done = true))),
    ));
    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    expect(done, isTrue);
    expect(find.text('Servora'), findsOneWidget);
  });
}
