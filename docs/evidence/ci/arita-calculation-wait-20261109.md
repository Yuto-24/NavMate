# ARITA回帰の計算表示待ち（Issue #408）

`#350 dedicated ARITA descent needs no altitude input` の初回NAV LOG表示待ちを、
30秒から60秒へ限定して変更する。CIの失敗traceでは、待機期限直後に計算結果が表示されており、
少なくともこの失敗は計算の停止ではない。テスト全体の120秒上限、retryなし、結果・保存／復元の
assertion、CIの2 workersとファイル内の実行順序は維持する。

## 失敗時の証拠

- [PR #402の実行](https://github.com/Yuto-24/NavMate/actions/runs/42494289593)、
  artifact `local-browser-local-failure`（ID `13622379539`）、1440px:
  `0-trace.trace`の初回表示待ちは149974.430–179980.529 msで失敗した。
  その直後のsnapshot（180011.996 ms、`after@call@1847`）には
  `.nav-log-table`と計算完了通知がある。`error-context.md`にも結果の行と保存ボタンがある。
  期限切れから約31 ms後のsnapshotで完了を確認できるため、計算が停止したという解釈には合わない。
  ただし、Workerの返答時刻はこのtraceに記録されておらず、計算完了の正確な時刻は断定できない。
- [PR #403の実行](https://github.com/Yuto-24/NavMate/actions/runs/42491130713)、
  artifact `local-browser-local-failure`（ID `13622082605`）:
  1100pxは138391.035–168399.915 ms、1440pxは182328.875–212341.689 msで同じ待機が失敗した。
  両方の失敗画面は計算中。テスト終了後の処理は記録されていないため、この2件だけでは
  継続と停止を区別できない。
- #402の[同一commit再実行](https://github.com/Yuto-24/NavMate/actions/runs/42494289593/job/128777460509)
  では、元の30秒上限のまま両ARITAケースを含む64件が成功した（既存skip 1件）。

## 待機条件と分離

`playwright.local.config.ts`はexpect 30秒／テスト全体120秒で、retryは設定していない。
CIは`test:local -- --workers=2`を使うが、同一ファイルの2ケースは直列に実行する。
各ケースは新しいBrowserContextとページを使うため、IndexedDBやLocalApplicationの共有はない。
別ファイルの計算とはCPUを共有する。単独で`--grep '#350' --workers=2`を指定しても、
Playwrightの報告は1 workerであり、CI全体と同じ負荷条件にはならない。

FTDを選択し、入力確定とWorker初期化が終わった後に計算を開始している。
CIのbuildにはTAF proxyの設定がなく、初回計算表示待ち区間のnetwork traceに
気象取得要求はない。失敗をPyodideの初期downloadやTAFの応答待ちとする証拠はない。

## ローカル確認

変更前の`d3b2b422`をLocal buildし、実際のPyodideで2件を実行した。
通常速度では2件成功（全体50.3秒）、初回表示待ちは1100pxで10.985秒、1440pxで15.612秒だった。
復元後の既存表示待ちは0.006秒／0.009秒で、今回の失敗箇所ではないため変更しない。
これらはhosted CIの所要時間を保証する値ではない。

CPU競合の診断では1440pxの同じケースを一時コピーし、初回表示待ちだけ60秒にして実行した。
Pythonの`os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})`でPlaywrightとその子プロセスを
1 logical CPUに固定し、同じCPU上に`while True: pass`のPythonプロセスを2個置いた。
負荷プロセスは`finally`でterminate／waitした。計算や応答のモック、sleepによる応答遅延は使っていない。

既存のWorker観測に加え、クリック前に30秒のtimerを設定して、table有無、Worker error、
`localCalculationCount`、最新stateの`calculationIsCurrent`を取得した。
30秒時点ではtableなし、Worker errorなし、計算要求1回、current=falseだった。
同じ1回の要求が47.935秒で表示完了し、既存のフェーズ・降下時間・燃料・保存／復元検証も成功した
（1件、全体約1.5分、retryなし）。これはCPU競合で同種の期限超過が起こる再現であり、
過去のCI runnerのCPU負荷そのものを測った結果ではない。

診断コピーと負荷設定は削除し、通常のCIには持ち込まない。
なお、最初に試したCDPの`Emulation.setCPUThrottlingRate`は3倍設定でも15.126秒で終わり、
Workerの計算を遅くする診断としては使えなかった。

## 修正の境界

60秒は観測された30秒付近の完了に余裕を持たせる有限の上限であり、計算性能の保証値ではない。
共通expect timeoutやテスト全体の上限を広げず、結果が出ない場合は引き続き失敗する。
アプリケーションの計算・保存コード、テスト選択、worker数、retryは変更しない。
