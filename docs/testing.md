# テストの責任とCI

PR・main の CI ルーティング（`test.yml` / `scripts/ci_changes.py`）、#458 以降の現行テスト担当境界、Browser E2E の標準入口（`test:e2e`）、テスト配置規則、および過去の性能・shard 計測基準を定めます。

## PR と main の CI

`test.yml` は PR、main / release/1.x / release/2.x への push、手動実行で起動します。
PR は変更影響に応じた**完全な suite 単位**で選択し、push と手動実行は文書変更も含め全検証します。
既存の concurrency とキャンセル条件は維持します。

`release-sources` は常に実行し、変更判定・集約の回帰、文言証跡、VERSION / CHANGELOG と
PR の Release 契約を検証します。PRのrelease契約は、checkoutした合成mergeの第2親が
PR headと一致することを確認し、第1親（実際に検証したbase）と比較します。
このジョブはアプリの依存関係や Docker build を必要としません。

| PR の変更入力 | 必須 suite（release-sources は常時） |
| --- | --- |
| `AGENTS.md`、通常ファイルとして残る `README.md`、`docs/` の文書・証跡のみ | source 検証のみ |
| 通常ファイルとして残る `VERSION` / `CHANGELOG.md` | release-build |
| `web/src/` 内の `.ts` / `.tsx` / `.css` | web、local-browser、account-sync |
| `src/autonavlog/` 内の `.py` | pytest、runtime、web、local-browser、account-sync、static-tooling-install |
| `services/taf-proxy/worker.mjs` | taf-proxy、web、local-browser |
| `services/msm-trigger/worker.ts` / `entrypoint.ts` | msm-trigger |
| テスト、CI、依存関係、ビルド設定、Rules、データ、その他のパス | 全 suite |

Web は画面と共有状態の依存が広いため、保存・NAV LOG・認証・同期の全マトリクスを維持します。
Python はブラウザの計算エンジンと配信ツールにも組み込まれるため、golden / regression を
含む pytest 全体と、それらの利用側の検証を維持します。独立したサービスの実装だけを
限定選択します。現行保証のassertionと必要なbrowser profileを維持し、担当suiteは下表で定めます。
pytestの分配とブラウザの分割方法は後述します。

`docs/` のMarkdown・JSON・テキスト・画像などの通常ファイルはsource検証のみとします。
実行コード、未知の拡張子、実装やテストが参照する一部の資料は全suite対象です。
UI文言証跡は常時実行する `release-sources` で照合します。

`VERSION` / `CHANGELOG.md`と文書・証跡だけのPRは、常時の`release-sources`と`release-build`、
最終集約の`ci-required`を実行します。`release-build`は既存のリリースノートテストと
Web build（生成JSON・TypeScript・Vite）、Python 3.12でのsdist/wheel buildを行い、
生成wheelの版番号とWeb成果物の同梱を確認します。Docker、ブラウザE2E、全pytest、
同期emulator、実MSMは起動しません。PRのRelease契約とVERSION/CHANGELOGの整合性は
従来どおり検査するため、限定分類されたことだけでリリース準備を有効とは扱いません。

push・手動実行・未知差分は`release-build`を含む全suiteを維持します。
全検証時には既存web/pytestと一部buildが重複しますが、今回は分類と必須checkを小さく拡張し、
工程全体の重複整理は[#459](https://github.com/Yuto-24/NavMate/issues/459)で扱います。

複合変更は選択の和集合です。PR の共通祖先から head までを Git で比較し、rename は削除と
追加の両方を評価します。ファイル件数上限はありません。未知パス、空差分、判定エラー、
通常ファイル以外・実行権限の変更、`VERSION` / `CHANGELOG.md`の削除は全検証へ戻ります。
`CHANGELOG.md`はリリース検証へ分類し、`KNOWN_ISSUES.md`は引き続き全suite対象です。
どちらも画面生成の入力なので文書省略の対象外です。判定ジョブの失敗・出力欠落でも各 suite を
起動し、最終集約は判定失敗を成功に変換しません。

`ci-required` は常に完了結果を集約します。判定の成功、全 suite の出力、選択された suite の
success、非選択 suite の skipped を照合し、失敗・キャンセル・必須 suite の skip は失敗にします。
既存チェック名は維持し、summary は実行成功と意図的 skip を区別します。
GitHub 上でマージを制限するには `ci-required` を必須チェックに登録する必要があります。
2026-11-17 に有効な Ruleset `20705217` へ `ci-required` を登録し、main の適用ルールで確認しました。
発行元は GitHub Actions（integration ID `15368`）に限定しています。既存ルールとbypass設定は維持し、
新たな「baseの最新化必須」は追加していません。従来branch protection APIは `Branch not protected`（404）でした。
実測と残る受入条件は [Issue #421 の証跡](evidence/ci/impact-selection-20261110.md) を参照してください。

### PR本文更新によるCIキャンセル

PRのpushと本文編集はどちらもCIを開始し、同じPRの後発実行が先行実行をキャンセルします。
その場合、先行実行のpytest・local-browser・account-sync集約は `RESULT: cancelled` を失敗として扱います。
この赤表示はテスト本体の失敗と区別し、対象SHA・Run・個別ログを確認してください。
本文変更とpushを両方行うときは、検証結果を含む本文を先に更新し、最後にpushします。
これにより、最新コミットのCIを直後の本文編集で中断することを避けます。
必須チェックの判定を緩めたり、中断された実行を成功と扱ったりはしません。

2026-11-21、[PR #478の先行実行](https://github.com/Yuto-24/NavMate/actions/runs/44771724479)で確認しました。
分類検査294件は成功していましたが、その直後にキャンセルされ、3つの集約チェックとci-requiredが失敗しました。
同じSHAの[後発実行](https://github.com/Yuto-24/NavMate/actions/runs/44771757051)とは別の結果です。

判定・集約をアプリ依存なしで検証するコマンド:

```bash
python -m pytest --noconftest tests/integration/check_ci_changes.py \
  tests/integration/check_ci_gate.py tests/unit/test_account_sync_ci.py
```

Release と runtime のソース契約は次で検証できます（アプリ依存は不要）:

```bash
python -m pytest --noconftest tests/integration/check_release_merge.py \
  tests/unit/test_release_ci.py tests/unit/test_supported_runtime_contract.py \
  tests/unit/test_version.py::test_version_is_the_only_release_version_source
```

## Issue #458: 現行保証の担当とLegacy専用テストの廃止

[#458 現行テストの責任整理](https://github.com/Yuto-24/NavMate/issues/458)では、
旧通常利用のためだけの検証を廃止し、現行の保証を小さい境界へ移す。
ブラウザの実Worker/Pyodide、保存・reload、同期SDK/Rules、配布候補の検証は担当を維持する。
以下は2026-11-18時点の対応で、件数はパラメーター展開後の収集結果。

| 保証・対象 | 担当する層とsuite | 実行イベント・維持する境界 |
| --- | --- | --- |
| 数値golden、inbound、KML、Shared facade / Issue #94保存 | Python Unit / Integration、`pytest` | 対象PR・main。実solver、期待値、atomicity、owner隔離を保持。`_LocalFacade`が旧名のfacadeを継承するため、`web`という名前だけでは削除しない |
| Connected KMLの6件 | `test_local_connected_lines.py`のLocal Integration | 対象PR・main。旧`test_web_connected_lines.py`から候補・座標・数値assertionを移し、HTTP session / pollingを外す |
| Localの入力エラー、内部失敗とlast-good / draft | `test_local_calculation.py` | 対象PR・main。Legacy HTTPとの一致比較を、明示的なLocalのcode・message・validation形状・安全性・保存値の検証に変更 |
| TGL、MC丸め、燃料/時間合計、GSI tile構造 | `test:application` | 対象PR・main。forms / display-rounding / fuel-plan-displayと、`web.spec.ts`から抽出したGSI 3件を実行。ブラウザ・サーバー不要 |
| 認証初期化待ち・reload・別account拒否、同期dialogのrefresh失敗・draft guard | `test:sync-component`、24実行 | 対象PR・mainのLocal auth runner。既存HTML harnessと実DOM/dialogを使い、Chromium・iPad WebKit・iPhone WebKitを保持。Firestore / Pythonは不要 |
| 代表的な同期、競合、削除、アカウント切替 | `test:sync`、30実行 | 対象PR・mainの既存6 runners。実SDK、Firestore emulator、Local保存・計算の結合を保持。移管24件との合計は従来の54実行 |
| Clipboard activation / fallback / pending / 確定後制限 | Clipboard suite、20実行 | 対象PR・main。ChromiumとWebKitを保持。Localでも選択していた同一Chromium 4件はClipboard側だけに集約 |
| 通知の期限、独立した失敗保持、retry、focus / scroll | `test:notification`、18件 | 対象PR・mainのLocal auth runner。390 / 1100 / 1440pxと既存入力を保持。account / sync harnessはcomponent、App harnessは実Local Application / Pyodideを使うためLocal assetsが必要 |
| Local FTD / 固定MSM、保存・reload、Worker障害、重要な操作導線 | `test:local`、66件と既存acceptance / focused UX / auth等 | 対象PR・main。数値比較、実Worker、IndexedDB、既存ブラウザ・端末profileを保持。Unitの同じ入力と重複扱いにしない |
| manifest不一致の拒否とreload復旧 | `test:static`の既存caseをLocal shard 1でも選択 | 対象PR・mainではfixture buildの実Workerと保存値復元。配布時は同じcaseを実候補artifactに対して実行 |
| 気象取得失敗の通知とNAV LOG / Last Calculation保持 | `local-weather.spec.ts`の既存cold/warm/evictionフローへ統合 | 対象PR・mainでは固定catalog / NPZと503を使う。外部MSMを取得せず、実Worker・ブラウザcache・保存結果を検証 |
| migration / rescue / 予備API、残存FastAPI runtime | Python・migration / forecast-backup Browser・runtime suite | 対象PR・main。移行本人識別、owner隔離、旧データ、専用BackupJobs、起動・非root・Python 3.12を保持。旧画面の停止や救済期間終了を推測しない |
| Static / Local Updaterの配布候補と運用 | 既存tooling / artifact tests、公開前後・Updater検査 | 配布時。fresh rebuild、実feed・設定・Rules、候補Static E2Eを保持。source CI再利用は[#460](https://github.com/Yuto-24/NavMate/issues/460)の担当 |

### 廃止・移管したアサーション

- `application.spec.ts`のLegacyApplication専用8件を廃止。対象は旧HTTP session生成・retry・
  HTTP error正規化・job polling・tab handle・透明なsession更新。丸めoptionsの混在ケースは
  Localの`true/false`送信を残す。Local失敗時のno-fallback、共有UI契約、durable保存のassertionは維持する。
- `startup.spec.ts`の旧API起動retryを廃止。現行の失敗codeと実Worker再起動・復旧は
  `session.spec.ts`の`#355 startup reload replaces a failed Worker`が担当する。
- `test_calculation_jobs.py`の3件、`test_web_app.py`の旧job重複409 / snapshot prune race、
  `test_local_calculation.py`の旧HTTP丸めjobを廃止。残る予備APIの`BackupJobs`は別実装で、
  その容量・owner・idempotency等は`test_forecast_backup.py`に残る。
- Connected KMLは4候補の名前・順序・距離`124.66 / 151.42 / 112.03 / 129.01`、
  container / segment / join gap、重複除去後4座標、500点受理・501点拒否、fallback、
  小丸の一意性と座標、名前によらないphysical legsとTTL `97.5`をLocalで保持する。
- Local errorは不正UUID・必須項目・壊れたKML/Base64、内部ValidationErrorと機密値の抑制、
  失敗後のfuel `90 / 75`、last-goodの`status`以外の値を維持する。旧HTTPを期待値の生成元にしない。
- GSI 3件は既存の入力と全assertionをそのまま`gsi-airspace-unit.spec.ts`へ移す。
  Polygon / LineString、2D / 有限3D、欠落・重複・不正metadata等を保持し、共通fixtureを
  `helpers/gsiAirspace.ts`に分離する。旧画面の`beforeEach`から独立させるための分離である。

`test_rjfm_inbound_web.py`は実数値とreference読込失敗を同じruntimeで確認するため維持する。
特に破損referenceをruntimeが捕捉して計算を継続する境界は、Local constructorへの単純置換と同じではない。
数値計算の高コストはHTTP wrapperだけを外しても消えない。

残る`web.spec.ts`、`rjfm-inbound.spec.ts`、`information*.spec.ts`、`clipboard-import.spec.ts`は
現行UIの詳細と旧transportが混在する。固有の表示・入力assertionを消さず、明示的な
`test:legacy`に保持する。通常CIでは元から選択されていない比較用suiteであり、
現行の必須保証は上表のLocal / component / Integrationを担当とする。これらのファイル全体を
旧専用と判断したわけではない。今後の個別移管では旧入力・assertionの対応を再確認する。

CI jobの共通準備やPython分配は[#459 PR/mainの重複・分配改善](https://github.com/Yuto-24/NavMate/issues/459)で扱う。
今回の件数減少やnative実行時間だけからHosted CIの短縮率を主張しない。

### Browser検証の実行入口

`test:e2e`は`test:local`の別名で、通常CIと同じ選択を使う。既定のPlaywright configもLocal向けとし、
Composeの自動起動を廃止する。Local suiteは配信済みbuildを使い、harness suiteは既存Viteを起動する。

```bash
AUTONAVLOG_TEST_FIXTURES=1 VITE_FORECAST_BACKUP_URL= npm --prefix web run build:local
python -m http.server 4174 --bind 127.0.0.1 --directory web/dist-local
# 別terminalで実行。reference用Pythonはアプリの依存を導入した3.12を指定する。
AUTONAVLOG_LOCAL_URL=http://127.0.0.1:4174 AUTONAVLOG_REFERENCE_PYTHON=python3 npm --prefix web run test:e2e
npm --prefix web run test:sync-component
npm --prefix web run test:notification
```

`test:local:full`はLocal configの全ケースを収集する手動の拡張確認。
固定MSMの取得失敗ケースは予備API未設定のbuildで実行する。catalogの503はWorkerの
`WEATHER_DISCOVERY_FAILED`となり、予備API未設定の通知を表示する。Pythonの予報準備で
発生する`FORECAST_PREPARE_FAILED`とは異なる。通知と計算終了を待ってからNAV LOGと
Last Calculationの保持を確認する。
移管前の混在UIを調べる場合だけ、既存の[Worktree手順](development_worktrees.md)で隔離した
Legacy runtimeを用意し、`AUTONAVLOG_WEB_URL=<隔離URL> npm --prefix web run test:legacy`を使う。
`test:legacy`自体はComposeを起動せず、通常PR/mainやStatic公開の成功条件には使わない。

## テストを追加する場所

検証したい仕様を先に決め、その仕様を失敗させられる最も小さい境界を使います。
ディレクトリ名だけで速さを判断しません。数値solverのunit testも高コストです。

- `tests/unit/`: 計算式、丸め、表示投影、入力検証、探索予算、保存adapterのatomicityなど。
  表示テストでは必要なdomain modelを直接構築し、fixture作成だけの
  `CalculationService.calculate()`は使いません。tmp_pathで本物の保存adapterを検証する
  既存テストもこの層にあります。mutableなProjectやsessionを広いfixture scopeで共有しません。
- `tests/integration/`: 計算serviceと性能・気象adapterの接続、RCA/EOC分割、結果の集計、
  facadeと保存・readinessの連携。主要golden、距離・時刻・燃料、既知バグの再発防止は
  実際の計算経路を通します。表示だけの詳細値はunitへ寄せます。
- HTTP integration: status code、cookie、JSON変換、job、owner境界、API経由の復元と
  代表的な計算フローを保証します。同じ入力の正常計算を準備だけのために重複させる場合は、
  同一フローへアサーションを統合できるか確認します。異なる入力条件や失敗経路は残します。
- `tests/contract/`: WeatherProviderとのrequest ID、run固定、単位、型、provenanceの変換境界。
  MSM契約テストはstub clientを使い、実MSMの取得可否を保証するものではありません。
  実データの受入れは[real_msm_acceptance.md](real_msm_acceptance.md)を参照してください。

探索上限などの制御テストでは、下位の距離探索を「実行可能・収束済み」の結果で置換し、
回数上限と失敗時の数値抑制を検証できます。返すべき失敗結果そのものをstubしてはいけません。
風・境界・DME・収束の実数値回帰をそのstubへ置き換えないでください。

Issue番号付きのテストは、名前だけを理由に削除・改名しません。
`test_issue_43_golden.py`は数値回帰、Issue #94の2ファイルは永続化の異なる境界の仕様です。
統合時は旧テストの入力・アサーションの行き先をレビューで確認します。

## EOCの高度連続性とsnap時間差（Issue #470）

EOCの不整合を調べるときは、前段の高度変更が未完了なのか、snapだけによる時間差なのかを
分けます。仕様は[計算規則](calculation_rules.md#descent--eoc)を正本とします。

- 前Legの計画高度だけでなく、RCA以後の実効CRUISEのGS・時間で到達高度を追跡します。
  DESCENTのGSで前段の高度変更時間を判定すると、手入力TASやphase別の風で誤判定します。
  `test_calculation.py`の`issue_470`ケースは67.3秒対120秒、到達時間の境界、複数Leg、保存後の
  共通プロファイルを検証します。#73の現在Leg優先は、高度変更が完了するケースで維持します。
- 既存Goldenの7,500→2,800 ftにも同じ問題があり、#470ではEOCが玉名より手前へ移ります。
  `test_issue_43_golden.py`は移動後のZone順・CP正横・CAS・表示集計を検証します。
- 0.4 NMの前方snapにより504秒の計画が492秒になるケースはNAV LOGの成功を維持します。
  `test_eoc_integration_snap_threshold_preserves_profile_metadata`と`test_vertical_profile.py`で、
  保存されたsnap位置と時間差の一致、30秒の境界、描画の減速60秒、旧結果の無補正を検証します。
  この描画上の許容値は運用上の近似で、実際の旋回軌跡や機体性能を検証したものではありません。

## 同じ条件で比較する

Dockerのtest stageがサポートするCI検査環境です（[README](../README.md)）。
開発用Python環境で計測する場合も、前後でPython、依存関係、coverageオプション、
実行順とCPU負荷を揃えます。並列の重い検査は避けてください。

```bash
pytest --cov=autonavlog --cov-report=term --cov-report=json:/tmp/coverage.json \
  --durations=30 --junitxml=/tmp/pytest.xml
```

変更前後のJSON/XMLは別名で保持します。総時間だけでなく遅いテスト、
モジュール別時間、失敗・skip、実行されたsource行の差を比較します。
coverageの丸め表示だけでは低下を見落とすため、covered_linesとmissing_linesも確認します。
件数の減少やunitへの移動だけを成果としません。

GitHub Actionsのpytest jobにはDocker build、ruff、mypy、pytest、データ・schema検証、
package buildが含まれます。job全体、`docker run` step、pytest自身のログ時間を区別し、
異なるマシンのローカル時間と直接比較しません。hosted CIは実際の完了状態を記録します。

## Issue #142 の棚卸し（2026-09-09・歴史的記録）

基準はmain `a32a649`。WSL Ubuntu / Python 3.12.3 / pytest 8.4.2 /
pytest-cov 6.3.0、coverage付きの逐次実行で754件が331.44秒で成功しました。
unit 578件、integration 173件、contract 3件です。

上位のcall時間は次の通りです。

- inbound solverの非grid最適解とcoarse scan比較: 77.06秒。
- 同solverの予報風: 56.60秒。
- 同solverの方位上限290度・下限250度: 52.09秒・49.10秒。
- 本番参照を使うinbound HTTP数値回帰: 37.78秒。
- 方位探索予算をcoarse gridで使い切るケース: 10.32秒。

最初の5件（約272.63秒）は数値回帰として維持します。
`tests/unit/test_rjfm_inbound_guidance.py`全体が約259.44秒を占め、
通常の計算integrationを機械的に削る方針は取りません。

優先調査箇所の判断:

- `test_calculation.py`: 58件・計1.49秒。集計2件はフル計算で作ったSectionResultの
  距離・時間を上書きしていました。`unit/test_navlog_display.py`へ移し、
  型付きの最小入力を直接作ります。RCA/EOC、manual override、気象反復、goldenは維持します。
- `test_web_app.py`: 26件・計8.59秒。FTD正常計算とlast-good復元が同じ入力で重複。
  `test_ftd_calculation_and_last_good_restore_without_cookie_or_server_session`へ
  全アサーションを統合し、1回の実計算でprovider選択、JSON、cookieなし・再起動復元を確認します。
  owner分離、job競合、入力validation、失敗時draft保持などは別のAPI契約として残します。
- Issue #94: 保存adapterの27件は計0.61秒、facadeの18件は計3.93秒。
  Latest置換、破損marker、書込失敗は見かけ上重なりますが、adapterはファイル・atomicity、
  facadeはsession commit・owner・readinessとの連携を保証します。
  HTTP復元もcookieやアプリ再構築を通す代表ケースとして残します。
- `test_release_ci.py`: 25件・計0.02秒。`test_release_preparation.py`: 28件・計0.18秒。
  前者はdiff分類・fragment要否、後者は実ファイル書換え・check無変更・rollbackを保証し、
  同じ仕様の重複としては扱いません。
- 方位探索予算テスト: 数値距離探索を分離し、9回のcoarse評価で停止すること、
  実行可能な候補があっても未収束なら数値を返さないことを直接検証します。
  実距離探索・幾何・予報風と本番参照の回帰は残します。

上記モジュールの合計はJUnitのsetup/call/teardown時間、上位一覧はpytestのcall時間です。
テスト・文書だけの整理のため、Release: not-required契約に従い、VERSION更新はありません。

変更前のhosted CIは[mainのrun 34330643488](https://github.com/Yuto-24/AutoNavLog/actions/runs/34330643488)。
pytest自身は754件・594.46秒、docker run stepは616秒、pytest jobは674秒でした。

変更後は753件・321.46秒で成功し、単発の同条件比較では9.98秒（3.01%）短縮しました。
探索予算テストは10.324秒→0.011秒、集計2件は合計0.039秒→0.002秒、
統合したFTD HTTPフローは合計0.899秒→0.399秒でした（JUnit時間）。
件数差の1件はHTTP統合によるもので、元のアサーションは維持しています。
複数回の統計的ベンチマークではなく、他の数値探索時間には実行ごとの揺れがあります。

coverageは前後とも10,144 / 11,334行（89.5006%、表示90%）、missing 1,190行。
全sourceファイルのexecuted_lines集合を比較し、失われた行・追加行とも0でした。
branch coverageや実データの正しさまでこの数値だけで証明するものではないため、
主要golden・数値回帰も削除せず全suiteで実行しています。

## Issue #154: inbound solver の関数 profile（2026-09-11・歴史的記録）

基準はmain `aab2dab`（#142 / #151と#152のRelease契約移行を含む）。
Python 3.12.3 / pytest 8.4.2 / pytest-cov 6.3.0 / coverage 7.15.4 /
GeographicLib 2.1、同じWSL host・依存関係で逐次実行しました。
重い検査を並行実行せず、coverage付き全suiteの時間と、coverageなしの段階タイマーを
分離しています。関数時間は計測オーバーヘッドを含み、性能比較の秒数とは別です。

### 支配的な処理

対象5件の段階タイマーによる累積時間（秒、変更前→変更後）。親子関数の時間は重複するため加算しません。

- 非grid解とcoarse scan: solver 25.477 → 18.410、route metrics 23.140 → 16.052、
  区間距離15.334 → 8.183、clearance 4.960 → 4.993、
  sampling 1.875 → 1.896、DME再構築1.846 → 1.874、
  風補正0.060 → 0.060。方位66件・距離2,574件。
- 予報風: solver 18.727 → 13.494、route metrics 17.041 → 11.770、
  区間距離11.229 → 5.972、clearance 3.689 → 3.649、
  sampling 1.391 → 1.408、DME再構築1.340 → 1.373、
  風補正0.063 → 0.064。方位54件・距離1,937件。
- 下限250度: solver 16.212 → 11.635、route metrics 14.731 → 10.143、
  区間距離9.737 → 5.165、clearance 3.160 → 3.148、
  sampling 1.196 → 1.201、DME再構築1.177 → 1.196、
  風補正0.039 → 0.038。方位42件・距離1,649件。
- 上限290度: solver 17.249 → 12.353、route metrics 15.667 → 10.775、
  区間距離10.370 → 5.482、clearance 3.363 → 3.350、
  sampling 1.268 → 1.279、DME再構築1.266 → 1.266、
  風補正0.041 → 0.041。方位45件・距離1,762件。
- 本番参照HTTP: solver 10.080 → 9.102、route metrics 7.983 → 6.997、
  区間距離2.316 → 1.447、clearance 2.116 → 2.043、
  sampling 2.466 → 2.415、DME再構築1.736 → 1.744、
  風補正0.053 → 0.052。方位39件・距離1,889件。

非gridケースは本探索1回（方位57件・距離2,239件）と独立したcoarse比較9回です。
変更前の本探索22.096秒、coarse比較計3.381秒。HTTPは自動1,500 ft計画のNO_SOLUTION
（1.024→1.002秒）と手動2,500 ft計画のAVAILABLE（9.056→8.100秒）の2 solveです。
HTTP call全体は10.569→9.601秒、solver以外のAPI・計画更新・polling等は約0.49→0.50秒。
HTTPテストの削除やstub化で解消する問題ではなく、両計画の実計算とstatus/JSON/数値を残します。
samplingの段階タイマーは候補経路の生成が対象で、request入口の直接route検査はsolver総時間に含みます。

全15 solveで、入力・全出力field・各段階の呼出し回数・評価したbearing/distanceの順序hashが
前後完全一致しました。各段階の累積時間がその呼出しのsolver時間以下であることも確認済みです。
段階計測はcoverageなしで5件が88.40→65.65秒。coverage付き全suiteとは別の実測です。

主因は、方位→距離→raw/rounded経路→最大0.5 NM区間という反復により、
`_route_distances`が膨大な回数の`geodesic_leg`を呼ぶことです。初期の合成ケースcProfileでは
非grid本探索だけで約38万回の`geodesic_leg`を実行していました。
距離だけを使うのに、毎回WGS84 inverseの後でLineを構築し、Positionで中点も算出して破棄します。
段階タイマーでは合成4件の区間距離再計算はsolver時間の約60%、変更後は約44%です。

### 変更判断と維持する保証

`_route_distances`だけを既存の距離・初期方位用WGS84 inverse関数へ変更します。
同じinverseの`s12 / 1852`を使い、中点のLine/Positionと不要な結果object構築だけを省きます。
中点が必要な通常の`geodesic_leg`やroute samplingは変更しません。

- 方位の5度coarse grid、直接方位候補・近傍細分化、最大64評価、0.001度収束、
  距離17 seed・最大96評価・0.001 NM収束、DME丸め、最大240 NMを維持。
  予算を使い切ったときのCONVERGENCE_FAILUREと数値抑制も維持します。
- samplingを粗くせず、各chordのinverse・0.5 NM制約・240 NM制約・local domain検証・
  numeric guard・境界接触/交差/clearanceを維持。
  sampling距離を理論上の等分値で代用せず、実際の座標間距離を検証し続けます。
- bearing/distanceの同一候補は既に探索内dictで再評価を避けています。
  coarse比較の独立9 solveは非grid最適解に対するoracleなので残します。
  解の検出を弱める探索予算削減や早期打切りは採用しません。
- immutableなpolygon準備は再利用候補ですが、合成ケースでは0.05〜0.09秒、
  HTTPでも約0.25秒で支配的ではありません。今回はcacheを追加しません。
  同じ丸めDMEでもraw距離によって二分探索のbracketが変わり、最終座標は必ずしも同一では
  ありません。DME値だけをkeyにした丸め結果cacheは同値性を保証できません。
  requestを跨ぐcacheも風・高度・boundary/revisionの取り違えやメモリ保持を増やすため不要です。

### 再現する方法

同じcheckoutでpackage metadataも整合させてください（例: `uv pip install --python .venv/bin/python --no-deps -e .`）。
今回の初回試行は古い1.7.0 metadataによるversion testだけが失敗し、数値回帰は成功しました。
その試行を正式な成功baselineとせず、metadataを現行ソースに合わせて取り直しています。

全suiteは上記「同じ条件で比較する」のcoverage/JUnitコマンドをbefore/afterの別名で実行します。
profilingは別プロセスで次のように実行します。outputは新しいdirectoryを指定します。
比較する両revisionで同じ計測スクリプトを使用してください。今回の再計測では、変更前の
幾何module全文を`git show aab2dab:src/autonavlog/application/rjfm_inbound_geometry.py`で読み、
一時プロセス内でmodule namespaceへロードしてから同じスクリプトを実行しました。
他のsolver/test/依存は同一で、worktreeのソースは書き戻していません。

```bash
.venv/bin/python scripts/profile_rjfm_inbound.py --output /tmp/inbound-profile-before
```

`solutions.json`でtest/request/resultとsolver時間、段階ごとのcalls/seconds、
評価したbearing/distance列のSHA-256を確認できます。`test-times.json`はpytest call全体です。
元の関数を実行するwrapperのタイマー・カウンターをthread-localに保持し、HTTP workerでも
外側solverと各段階を同じthreadで計測します。各段階は親子で重複するため加算しません。
計測器の多重設定・solverの再入はエラーにし、終了後にinstrumentationを解除します。
前後でtest/request/result・各段階の呼出し回数・evaluation_traceを完全一致で比較します。
計測時間そのものをテストの合否条件にはしません。

初回のcProfileは合成4件のボトルネック発見に役立ちましたが、HTTP workerのprofileに
非再帰solverが再入扱いになる異常があり、独立レビューで指摘されました。
そのHTTP関数内訳を採用せず、最終的な5件の比較は上記タイマーで取り直しています。

### coverage付き全suiteの比較

成功baselineは731件・316.24秒、変更後は736件・261.00秒で、55.24秒（17.47%）短縮。
単発の同一host比較であり、安定した短縮率の保証ではありません。
対象5件のJUnit時間（setup/call/teardownの合計）は次のとおりです。

- 非grid解とcoarse比較: 76.100 → 61.009秒。
- 予報風: 56.208 → 44.385秒。
- 下限250度: 48.315 → 38.172秒。
- 上限290度: 51.758 → 40.808秒。
- 本番参照HTTP: 37.983 → 35.413秒。

coverageは前後とも10,144 / 11,334行（89.5006%）、missing 1,190行。
幾何moduleも235 / 248行・missing 13行で同一です。変更による行番号移動を対応付けて
全sourceのexecuted_linesを比較し、変更していない行のcoverage欠落は0でした。
新しい距離取得呼出しも実行されています。branch coverageや実データの正しさそのものを
この比率だけで証明するものではありません。
既存golden・数値回帰・toleranceは維持し、追加5件はゼロ長・半NM・RJFM周辺・緯度上限/下限で
旧WGS84距離との完全一致と中点計算がないことを確認します。

### 同PRでのRouteNodeRole整理

通常のルート作成・OMARU追加は`ROUTE_POINT`を使い、`TURN_POINT`を生成する本番経路はありませんでした。
削除前にこの環境の保存領域を読み取り確認し、稼働volumeのJSON 490件、他の保存volume 4つの
JSON計133件、ローカル保存フォルダのJSON 149件で、role/point_roleに該当する実例は0件でした。
他環境や外部に持ち出したデータまで調査したという意味ではありません。
この結果と削除方針に基づきenum/schema/設計書から除去し、互換変換やmigrationは追加しません。
専用のroleテストはなく、参照していたgolden・EOC・性能補間・参照データ保存テストは別仕様の
保証なので、入力roleだけを`ROUTE_POINT`へ置き換え、数値assertを維持します。
上記の性能比較はこの整理より前の測定であり、enum削除による高速化を主張するものではありません。

## Destination TAF Proxy (#145)

`npm --prefix services/taf-proxy ci`後に`npm --prefix services/taf-proxy test`と
`npm --prefix services/taf-proxy run check`を実行する。Node unitに加え、公式workerdで
module export、CORS、cache、native rate binding、redirect拒否を検証する。
Miniflareの`dispatchFetch()`応答は到着直後に本文を一度だけ読み、status / headers / 読み取った本文を
検証用の値として返す。未読Responseを`Promise.all`で集めてから順に読むと、Miniflareが共有する
Undici側の元ResponseのGCでstreamがcancelされ、最初のJSON読取でも`Body is unusable`になり得る。
CIでは`MINIFLARE_ASSERT_BODIES_CONSUMED=true`で即時読取を検査する。並列100件の応答内容と
上流呼出回数の検証を減らしたり、例外を無視したりして回避しない。
`npm --prefix web run test:application`はBrowser network adapterのquota / timeout / size検査も含む。
Python `tests/integration/test_local_calculation.py`はTAFの成否による航法値不変を確認する。

Static Browser回帰は`VITE_TAF_PROXY_URL=https://taf.example/taf npm --prefix web run build:local`で
buildし、静的配信後に`npm --prefix web run test:taf`を実行する（必要なら`AUTONAVLOG_LOCAL_URL`）。
このsuiteはProxy通信をfixtureへ置換し、成功→quota→timeout→停止→reload→復旧と
IndexedDB Project / Last Calculation保持を確認する。通常の`test:local`はTAF未設定buildで実行する。
実upstream smoke、Free tier見積りと本番release gateは[TAF Proxy運用](taf_proxy.md)を参照する。

## Browser CI runners

`local-browser-tests`と`account-sync-tests`は`ubuntu-24.04`を明示し、`ubuntu-latest`のOS移行で
Playwrightの依存導入が急に変わらないようにする。`local-browser-tests`の25分上限、認証・Local保存・
計算・NAV LOG・ブラウザ受入・TAFの検証と、`account-sync-tests`の20分上限、Firestore Rules・同期・
移行の検証は維持する。両jobはブラウザ入り公式コンテナを使用し、runnerごとのbrowser/OS追加導入は行わない。
キャンセル時はcheck annotationと失敗stepを確認する。imageや依存の取得でtimeoutした場合、
後続のテストは未実行であり、テスト失敗やconcurrencyによる中止とは区別する。

### Browser worker count

現行の分割と保証は[Independent CI shards](#independent-ci-shards)を参照する。
Local regression、NAV LOG scroll、browser acceptance、focused UX、ClipboardはCI引数で
`--workers=2`を指定し、ファイル内順序を保つ。認証・同期component・通知は同じauth runner、acceptanceは
NAV LOG scroll→browser acceptance→TAFの順序で実行する。
認証、TAF、Firestore Rules、storage-upgrade、migrationは従来のworker設定を保つ。

同期の各deviceは2分割し、CIでは`--fully-parallel --workers=1 --shard=N/2`を使用する。
各runnerのemulatorは独立し、ランダムsubjectとcontextによる分離も維持する。
Firestore Rules→storage-upgrade→migrationはcontracts runnerで全対象を順番に実行する。
共有開発は別runnerで、起動前にrelease notesを生成する。
`web`でLocalと同期のexact-once分配を検査し、各集約checkは全matrix entryの成功を要求する。
失敗・skip・cancelした群を成功扱いにしない。retry、timeout、既存assertionは維持する。
ローカルのPlaywright configの既定値は1 workerのままとする。

旧構成の比較は[同期worker計測](evidence/ci/account-sync-workers-20261101.md)と
[project分割](evidence/ci/account-sync-project-shards-20261101.md)に残す。

`#350` ARITA回帰の初回NAV LOG表示待ちは、[Issue #408のtrace調査](evidence/ci/arita-calculation-wait-20261109.md)
に基づき60秒とする。共通expectの30秒、テスト全体の120秒、retryなしは維持する。

同期テストの初回ログインは、テスト用`authTest`の存在だけでなく、初期画面の
「アカウント」ボタン表示を待つ。この表示は匿名Applicationのworker bootstrap完了後で、
実際の利用者が認証操作を始められる時点に対応する。初期化前のVite再読込とログインが
重なった失敗を[PR #326のCI](https://github.com/Yuto-24/AutoNavLog/actions/runs/41266357658/job/124729915595)で確認した。
認証は1回だけ実行し、認証エラーは伝播させる。初期UI前の再読込と認証失敗を回帰テストで検査し、
ログイン後の期待accountとの一致確認も維持する。任意の時点で起こる再読込を防ぐ保証ではない。
初期化待ちの回帰2件を3ブラウザに追加した時点では計39件だった。上記の時間比較は追加前の33件に限る。
現在のSDK E2Eとbrowser componentの分担は[Issue #458の対応表](#issue-458-現行保証の担当とlegacy専用テストの廃止)を参照する。

2026-10-29、main `3ea6481d9fb02f7893edc3adb89c57d30e7dd40b`の同一Local artifactで、
1 worker、次に2 workersを逐次計測した。WSL / Node 24.19.0 / Python 3.12.3 /
Playwright 1.62.1、`CI=1`、子プロセスとHTTP serverを含め`taskset -c 0-3`で4 logical CPUsに
固定した。重い別検査はこの計測と同時に起動していない。時間は各コマンドの起動から終了までのwall time。

| Suite | Tests | 1 worker | 2 workers |
| --- | ---: | ---: | ---: |
| `test:local`の既存CI選択 | 21 | 216.5 s | 124.4 s |
| `playwright.navlog-scroll.config.ts` | 3 | 23.9 s | 15.7 s |
| `playwright.browser-acceptance.config.ts` | 6 | 95.7 s | 56.0 s |
| 合計 | 30 | 336.1 s | 196.1 s |

両方で同じfile/title/projectの30件がretry 0で成功し、skip、unexpected、flakyは0件。
ソース・依存・ビルド・実行順を固定し、worker数以外にはreport/outputの保存先だけを分けた。
合計140.1秒（41.7%）短縮した1組のローカル観測であり、hosted CI全体の短縮率や
異なるrunnerの性能を保証する値ではない。比較元mainの
[run 40789264289](https://github.com/Yuto-24/AutoNavLog/actions/runs/40789264289)では、
この3群のPlaywright報告時間は約620秒、`local-browser` job全体は1057秒だった。
依存導入・認証・TAFは今回の短縮対象外で、hosted CIの成否と実時間はPRで別途確認する。

再計測時は`AUTONAVLOG_TEST_FIXTURES=1 npm --prefix web run build:local`を一度だけ実行し、
同じ`web/dist-local`を専用HTTP serverで配信する。`AUTONAVLOG_LOCAL_URL`と
`AUTONAVLOG_REFERENCE_PYTHON`を両方のrunで揃え、上記3コマンドにそれぞれ
`--workers=1` / `--workers=2`を渡す（`npm run test:local`では引数の前に`--`を置く）。
`--reporter=line,json`とrun/suite別の`PLAYWRIGHT_JSON_OUTPUT_FILE`、`--output`を指定すると、
実行されたfile/title/project、result/retry、suite時間を機械的に比較できる。
テスト数・結果が一致しない観測を短縮の根拠にしない。

### Browser-job pip cache

`local-browser-tests` と `account-sync-tests` は `actions/cache@v4` で
`PIP_CACHE_DIR` の HTTP 応答・built wheel を保存する。venv / site-packages は保存しない。
コンテナ内では setup-python の pip cache が要求する `lsb_release` がないため、
cache を独立した step で管理する。OS ライブラリの追加導入で回避しない。

key は runner OS / architecture、Playwright image 版、解決した Python 版、
pyproject / vendor wheel / test.yml の hash。cache hit 時も同じ pip install を実行し、
現在の checkout をビルド・導入する。cache miss / eviction は通常取得に戻り、成功 job で保存する。
依存は完全には固定していないため、cache は lockfile やオフライン導入の代わりにはならない。

2026-10-29、同じcheckoutと既存installコマンドを使い、WSL / CPython 3.12.3 /
pip 24.0の新規venvで逐次計測した。専用`PIP_CACHE_DIR`でcold 41.71秒、warm 17.21秒、
別の空cacheでの消失再現43.33秒。3環境の52 package（pipを含む）の名前・版が一致した。
最終wheel payload処理開始からアプリwheel build開始までの区間は空cache 10.737秒、
warm 0.257秒。warmでは外部wheelの再取得0件、cache容量は約107 MiBだった。
同一パス・同一アプリ版のfixtureでソースを変更し、古いapp wheelがcacheに存在する状態でも
新しいmarkerが導入された。実checkoutのcold/warmログでもアプリwheelは毎回ビルドされた。

再計測時は新規venvと専用cacheを使い、次の既存コマンドを同じソースで実行する。
`PIP_LOG`をrun別に指定すると取得区間の時刻を確認できる。

```bash
python -m pip install "setuptools>=69" wheel vendor/jma_gpv_weather-0.6.0-py3-none-any.whl ".[test]"
```

cold/warmの`pip list --format=json`、wheel取得ログ、アプリbuildログを照合する。
GitHub側ではsetup-pythonのrestoreとpost saveを含めて測る。上記ローカル値にはActionsの
転送・圧縮コストを含まない。通常時のhosted downloadは約2秒の既存観測もあるため、
この比較からhosted CIの平均短縮や、過去の遅延の再発頻度は主張しない。
採用目的は約100 MBの外部wheel再取得への依存を減らすことである。


### Independent CI shards

`local-browser-tests` runs the existing Local regression selection on four runners using
Playwright's file-level `--shard=N/4`. Tests within a file remain ordered, and each runner
keeps `--workers=2`. New selected tests are assigned by Playwright, without a file allowlist.
Terrain, static storage notice, manifest mismatch/reload and forecast-backup tests run once, on Local shard 1.
The auth runner also runs sync component and notification suites; `acceptance` retains scroll, all browser/device acceptance projects
and TAF. `focused-ux` and `clipboard` keep their existing configurations and two workers.
Each runner owns its build directory, including the TAF-specific rebuild. The auth runner uses
its suite-owned Vite harnesses and does not start the unused port 4174 static server.
Local asset preparation remains necessary for notification tests using the real Worker.

Account Sync retains Chromium, iPad WebKit and iPhone WebKit. Each project uses two isolated
runners with `--fully-parallel --workers=1 --shard=N/2`: individual tests are distributed,
but each runner executes sequentially with its own Firestore emulator. The existing tests
use fresh browser contexts and unique account IDs, with no shared before/after-all state.
Only `contracts` starts the migration HTTP harness. Device sync uses Local/Pyodide and Firestore,
so it does not start that server. Rules, storage upgrade and migration stay together in `contracts`; shared development runs
once in its own Auth/Firestore emulator runner. Sync helper/dialog assertions run separately in
`test:sync-component` with the same three device projects, without an emulator.
Local developer commands without a shard keep their previous behavior.

The `web` job compares real Playwright collection before and after sharding: Local's existing
npm grep selection and all sync projects must each occur exactly once. It also checks the
workflow matrices. The `local-browser` and `account-sync` aggregate names are unchanged and
fail unless every matrix entry succeeds. `ci-required` still requires every selected suite,
including `web`; moving collection checks there avoids an npm install after sync finishes.

`pytest-tests` uses two independent Docker test-stage runners. Lint, typing,
release/data/schema validation and package build run once in `run_ci_checks.sh` on shard 1.
Shard 2 uses its `pytest` argument; the aggregate requires both runners, so a shared-check failure
cannot pass the Python gate. The default invocation still runs every shared check and all tests.
Both runners keep their own Docker build, Python 3.12, installed package, generated `static`
and source `public` assets. Image transfer is not introduced: its transfer/storage cost is not
measured, and both environments must test the current installed package.
Release-source validation and release-build remain independent: they cover PR body/base contracts
and the Node 24 release package, whereas Docker builds use their existing Node 22 environment.
The pytest plugin partitions the complete collected test list by file, using measured file
durations and longest-first balancing. New files are included automatically; tests within each
file retain collection order. Local runs without `CI_PYTEST_SHARD` still run the complete suite.
The timing file controls balance, not membership: no allowlist can silently omit new tests.

The `pytest` aggregate checks that both shards collected the same complete test list and that
their selected lists cover it exactly once. Both coverage files are mandatory and are combined
before the complete report is produced. Coverage combines map installed-package paths inside Docker back to `src/autonavlog` in
the checkout; the Docker tests still exercise the installed package. A failing, missing, or cancelled shard cannot
make either aggregate green. PR selection is applied to complete suites as described above; branch pushes run all suites.

This reduces elapsed time by using more simultaneous standard runners, not by reducing test
coverage. Queue time, cold dependency downloads, and runner variation can still exceed ten
minutes. Account Sync runs in separate project and contracts runners as described above.
The complete workflow combines all three partitions; use hosted timings to assess Issue #421’s five-minute performance goal. Timing evidence
and the refresh procedure are in [the shard evidence](evidence/ci/independent-shards-20261101.md).

### Playwright の準備

Local browser と Account Sync は、`web/package.json` / lockfile と同じ Playwright 版の
公式 `mcr.microsoft.com/playwright:v1.62.1-noble` job container を使用します。
ブラウザと OS ライブラリは同梱済みで、各 job の `playwright install --with-deps` を省きます。
Node、Python、Java、npm / pip の導入と現在の checkout のビルドは引き続き実行します。
版の不一致は source 検証で検出します。更新時には package / lockfile と image を揃えてください。
ローカル向けのブラウザ導入スクリプトはそのまま利用できます。

公式 image の説明は [Playwright Docker](https://playwright.dev/docs/docker) を参照してください。
コンテナ取得と npm / pip / Firebase emulator の外部取得は残ります。コンテナ利用だけから
高速化を断定せず、Hosted Run の Initialize containers、依存導入、テスト本体を分けて比較します。

#### 多数のassertionによるPlaywrightの記録負荷

2026-11-23（JST）、[PR #494のiPad WebKitテスト](https://github.com/Yuto-24/NavMate/actions/runs/45041039018/job/137265396511)で、
NAV LOGの格子検証を27回繰り返す `#412` テストが180秒の上限に達しました。
traceには54,622件のassertionがあり、個別assertionの失敗はありませんでした。
起動は約10秒で完了していました。
同じ1,957件の検証でも、1回目は約1.17秒、26回目は約12.13秒を要しました。

Playwright 1.62.1では、明示的な親stepがないassertionを記録する際に、既存stepを再帰的に検索します。
このテストでは格子検証1回ごとに `test.step()` で親を設定し、検索の累積を避けます。
全セルの検証、画面幅・スクロール位置、許容値、180秒の上限は変更しません。

同じhelperへ合成gridを渡す比較では、54,423件の検証が53.0秒から18.7秒になりました。
2pxの位置ずれを与えると、従来どおり1pxの許容値を超えて失敗することも確認しました。
この比較はブラウザを使わず、記録処理と失敗の伝播を検証したものです。

この知見は当該traceとPlaywright 1.62.1の実装に基づく観測です。
別のtimeoutへ適用する前に、起動・操作待ちとassertionの記録時間を切り分けてください。
修正後のHosted CI成功を示すものではありません。

#### スクロール中の位置測定と時計の停止

2026-11-22、[PR #489のCI](https://github.com/Yuto-24/NavMate/actions/runs/44998138669)で、
既存ブラウザテストの2つの同期問題を確認しました。

- `navlog-scroll.spec.ts` のiPhone WebKitでは、`Date.now() + 200` の取得完了から
  `clock.pauseAt()` の開始まで約600 msかかり、停止先が過去になって失敗しました。
  固定時刻から時計を開始し、テストの制限時間より十分先の固定時刻で停止します。
  トーストの表示・再計算・期限の検証中は停止を保ち、`runFor()`で必要な時間だけ進めます。
- `sea.spec.ts` の1440 pxでは、再計算直後に個別の `boundingBox()` で取得したMAPと
  操作パネルの上端に22 pxの差が出ました。自動スクロール中の `Promise.all()` は
  同じ時点の座標取得を保証しません。既存の `expectPlanningLayout` と同じく、
  1回の `page.evaluate()` 内で比較対象を測り、位置・順序の許容範囲は維持します。

この記録はテストの同期方法に関する観測です。修正後のHosted CI成功を示すものではありません。

#### 再利用イメージの Python Reference と Local wheel

既存イメージを使う場合も、Reference を実行する Python に現行 checkout のパッケージを
インストールしてください。`PYTHONPATH` の差し替えだけでは不十分です。
`src/autonavlog/version.py` は `importlib.metadata.version("autonavlog")` を参照し、
その版番号は計算入力 fingerprint に含まれます。Reference の版番号、root `VERSION`、
ブラウザへ配布する Local wheel の版を照合します。

2026-11-18 の Issue #418 検証では、再利用イメージに残った 2.3.2 の metadata と
Local wheel 2.5.0 の不一致により、保存した MSM Advisory が NAV LOG には表示されても
準備状況の `.issue-advisory` に現れず、`local-weather.spec.ts` のテストが失敗しました。
現行 wheel を Reference 側にもインストールすると、アプリ・テストの変更なしで同ケースが成功しました。
同じ古い検証環境で変更前 UI も失敗したことだけから、既存不具合とは判断できません。
開始時 main の [CI Run 44263317171](https://github.com/Yuto-24/NavMate/actions/runs/44263317171)
では当該ケースを含む Local suite が成功しています。

### 地形入力（GSI DEM10B / 地形点 KML）の検証

- `npm --prefix web run test:application -- terrain-unit.spec.ts`：PNG 復号、領域境界、凹 polygon、欠損・未取得・不正入力、通信およびキャッシュ契約を検証します（`dem-signed.png` は独立した合成 RGB fixture です）。
- `npm --prefix web run test:terrain`：Chromium / WebKit 上で PNG 数値復号、KML の有効・不正・標高基準未確認・障害物除外、境界判定、外部通信抑止を検証します。
- 実データ限定確認（2026-11-09）：`dem_png/14/14174/6668.png`（HTTP 200、102,668 bytes、CORS `Access-Control-Allow-Origin: *`、SHA-256 `c30fad6bc8ca2ce64e4d6cb297425ba507ac0f3bec709bebfc7713387da396b4`）について、Python 標準ライブラリの独立復号と Chromium / WebKit で全 65,536 画素（うち欠損 2,942 画素）の一致を確認済み。これは 1 タイルの取得・復号確認であり、経路全域の被覆や SEA の正確さを保証するものではありません。仕様は [terrain_inputs.md](terrain_inputs.md) を参照してください。

#### SEA取得とLocal開発サーバーの切り分け（Issue #314）

2026-11-21、SEAの固定DEMブラウザ試験で次を確認しました。

- DEM要求が一度も送信されず未確定になる場合は、取得クラスの既定fetch呼出しも調べます。
  ブラウザ標準fetchをクラスのメンバーとして直接呼ぶと、receiverが変わり
  `Illegal invocation`で通信前に失敗しました。既定fetchをラッパーで呼ぶ修正を行い、
  `terrain-browser.spec.ts`で実リクエストの発生と404の欠損分類をChromium/WebKitで検証しています。
  注入した偽fetchだけではこの問題を検出できません。
- Local wheelとmanifestを生成し直した後、起動済みViteが古いmanifestハッシュを保持し、
  正常な整合性チェックによって起動が止まる場合がありました。生成物の一致を確認し、
  開発サーバーを再起動した後に失敗ケースだけを再実行します。整合性検証は無効化しません。
- `sea.spec.ts`は1100 px/1440 pxの操作領域位置、手動値の保存・再計算、固定DEM、
  低い手動値の警告、地形KML入力と診断一覧の非表示、診断情報の保持を検証します。外部GSIの経路全域被覆や
  実機・本番での受入を証明するものではありません。
- 2026-11-22、#485の本表統合では、同名CPでもsectionと投影終点で各SEAを対応させます。RCA/EOCの計算境界は
  SEAを分割しません。最終VISUAL_ARRIVALは既存の計算子行を省く一方でSEAはCPで分割されるため、
  TOとSEAだけの行を補います。`sea-display.spec.ts`と`sea.spec.ts`が通常区間・最終進入の複数CPと
  個別値の再読込を検証します。#315では自動値のみ表示し、旧手動値は保存互換性として検証します。
- 自動SEAの対応範囲は取得時だけでなく、更新入力・保存レコードの採用時にも検証します。
  緯度・距離・日付変更線・零長区間の不適合では自動値を未確定とし、手動値は保持します。
- 地形KMLの取込UIを廃止したため、ファイル読込中の取込・解除操作を検査する旧caseは廃止します。
  内部のKML入力契約は`test:terrain`、保存済み地形点の計算は`test_sea.py`で検証します。
  `notification-layout.spec.ts`ではProject切替時に取得済みProjectへ戻し、
  古い取得の完了が新しい取得の進行表示を消さないことを検証します。
- JSON出力は計算済み状態のSEAを画面の区間・自動値と照合します。未再計算の入力変更後を
  検証するときは自動保存の反映も待ち、フォームの即時表示と保存済み状態を混同しません。
  PNG通知の配置検査はPNG文言で絞り、同じ領域にあるSEAの取得中表示を誤検出しないようにします。
- 開発用HTML harnessを使うテストは、そのページを配信するVite付きsuiteへ置きます。
  2026-11-22に確認した[PR #482のCI失敗](https://github.com/Yuto-24/NavMate/actions/runs/44911160660/job/136867138319)では、
  Local suiteが`dist-local`を静的配信する一方、SEAの競合テストがビルドに含まれない
  `notification-harness`へアクセスして起動待ちになりました。該当テストを既存の
  `test:notification`へ移し、製品buildにテストページを追加せずCIの実行対象を維持します。
  Local suiteの再現には、開発サーバーではなくCIと同じ静的配信を使用します。
- CSPの通信可否はViteだけでは確かめられません。2026-11-21のPR #482修正では、隔離Composeの
  FastAPIが配信するCSP下でDEM宛fetchが発生し、CSP違反がないことをChromiumで確認しました。
  応答は固定fixtureであり、GSI実データの受入とは分けて扱います。

#### SEA診断情報の確認と再利用

画面から地形KML入力と診断一覧を削除しても、次の保存・取得経路は維持します。
表示方針と情報の用途は[区間別SEA](sea.md#診断情報の保持と再利用)を正本とします。

| 保存場所・参照先 | 内容 |
| --- | --- |
| `Project.metadata.sea.policy` | 評価方式の識別子 |
| `Project.metadata.sea.records[intervalKey].terrain` | `complete`、`maximum_m`、`required` / `valid` / `missing` / `not_acquired` / `invalid`、`provenance` |
| 各`terrain.provenance` | 検証できたタイルの`url`、`acquiredAt`、`sha256`、`source`、`unit`、`horizontalReference`、`verticalReference` |
| `Project.metadata.sea.records[intervalKey]` | 上記地形情報に加え、`manual_ft`と保存済みKMLの区間最高値`kml_maximum_m` |
| `Project.metadata.sea.kml` | 旧画面で取り込んだ地形点、採否、確認根拠・出典。KMLのXML原文は保存しない |
| `WebState.sea` | 現経路の区間識別・座標、地形情報、自動値・手動値・表示値・警告、KML出典の抜粋。保存データから`sea_plan()`で生成する |

永続データの正本はProjectのmetadataです。SEA更新は通常のProject保存を通り、画面非表示にしても
再読込で失われません。区間形状が変われば対応しないrecordは除外され、再取得では現在の記録が
更新されます。取得履歴を蓄積するログではありません。

現行のNAV LOG JSON出力からも確認できます。計算が最新でSEA状態が存在する場合、
`web/src/navLogExport.ts`はトップレベルの`sea`へ`WebState.sea`を出力します。
これは`outcome`内の項目ではありません。未再計算の入力変更後には含まれず、
KMLの全点やProject全体のバックアップにもなりません。

調査では、対象区間の`key`を対応させ、`terrain`の被覆・画素数と`automatic_ft` / `manual_ft` /
`value_ft` / `warning`を確認します。再取得前後を比較したい場合は更新前の出力も残し、
タイルのURL・取得日時・ハッシュを照合します。将来の不具合報告機能では、この既存データから
対象区間分を抽出できます。報告用の収集・送信機能は未実装です。現行JSONには経路座標なども含むため、
そのまま匿名化済みの報告データとして扱わず、報告に不要なProject・個人・気象情報は含めない設計にします。

再利用時には次の限界を保ちます。

- `web/src/sea.ts`は部分領域を順に評価し、不完全被覆でその区間の残りを打ち切ります。
  画素数は検査済み部分領域の加算で、未検査領域を含みません。部分領域間で重なる画素もあるため、
  一意な面積や区間全体の取得率へそのまま換算しません。
- 保存する`provenance`は復号・検証できたタイルの情報です。失敗タイルごとのHTTP状態・理由、
  PNG原本、全画素標高、検査済み領域のポリゴン一覧はProjectへ保存しません。
- SHA-256は取得した内容の識別に使います。GSIの正式な版番号・完全性証明ではなく、
  ハッシュだけから原タイルを復元したり、当時の取得失敗を再現したりはできません。

## AIP地図参照データ（Issue #311）

`npm --prefix web run prepare:local` は既存のLocal wheel/data生成後、
`scripts/reference/build_aip_runtime.py` を実行する。Python 3.12と `.[test]` の
固定版pyshp・Shapelyを使用し、ブラウザ/PyodideやLegacy runtimeには追加しない。
`web/public-local/reference/aip/` の25 GeoJSON・照合記録・manifestは生成物でありGitへ登録しない。
再生成は `prepare:local` から行うと旧生成物を除去できる。

`tests/unit/test_aip_runtime.py` は実原本3 ZIPの検証、全件のgeometry検査、再生成のバイト一致、
欠損高度・未知条件の保持、進入管制空域の形式間差、KS4の非重複、計算fingerprintの不変性を確認する。
離陸飛行経路の非ゼロZ座標と欠損Mを原本順のXY・部分境界とともに保持することも照合する。
破損原本・不正/空/重複geometry・未知CRSを拒否する合成入力も含む。
`npm --prefix web run test:static-artifact` は欠落・改変・アプリとの版数差・件数差を拒否する。
Python suiteを選択する提出前検証は通常どおりDocker test stageの全検査を実行する。

EFF20261029の注意点は[正規化・照合記録](reference/aip_map_geodata_20261029.md#形式間照合eff20261029原本2026-11-21確認)
を参照する。特にKMLの件数差は一律の重複除去では解消できず、Hiroshima・Sapporoには
水平形状差もある。照合記録の原本内indexは0始まりで、緯度経度の一致比較許容値は1e-9度。
比較許容値は出力geometryの丸めや航空上の境界誤差を意味しない。
生成物は出典内位置と元属性を保持し、計算用KS4-3の境界・誤差モデルは置換しない。
