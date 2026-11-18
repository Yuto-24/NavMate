# MSM artifact ownership handoff — 2026-10-27

## 結論と原因

[Static production run 40427467953](https://github.com/Yuto-24/AutoNavLog/actions/runs/40427467953)（Run `20261026210000`）では、build・artifact 検査・Production Browser E2E 10 件すべてが成功した後、ホスト側の `freshness.py` が `app/web/dist-static/weather/msm/freshness.json` 作成時に `PermissionError: [Errno 13]` で失敗した。

- **原因**: ビルドコンテナ（`USER` 未指定で UID/GID `0:0` 実行）が writable bind mount 上に root 所有で `weather/msm` と `release.json` を作成したため、nonroot の Actions ホスト側 `freshness.py` が書き込みできず権限失敗した（失敗 Run のログには `id`/`stat` が残っておらず、当時の正確な UID/GID と mode bits は復元できない）。
- **対処**: 認証情報なしのビルドコンテナへホストの数値 UID/GID を渡し、build/E2E 成功後に対象（`release.json`、`weather/msm`、存在時の `weather/msm/freshness.json`）のみへ非再帰 `chown --no-dereference` を適用する。payload やチェックアウト全体の権限・モードは変更しない。
- **検証境界**: `tests/integration/check_static_artifact_handoff.py` は、実 build イメージを用い、回帰テストの再現条件として root 所有（`0:0`）`0755`/`0644` と実行ホストの非 root UID/GID（`os.getuid()` / `os.getgid()`）を設定して再現・修正確認した検証であり（特定実行で `1000:1000` 等を観測した場合はその実行結果として区別する）、失敗 Run 当時の実測 mode の証明や実上流 MSM / NPZ 公開の代替証拠ではない。

## 実施記録と制約（2026-10-27）

The failed run did not log `id`/`stat`; its exact runner numeric UID/GID and historical mode bits cannot be recovered from that log. The regression records those values explicitly instead of hardcoding a presumed GitHub runner UID.

`test_static_publication_gate.py` additionally verifies that the independent gate accepts the extended inventory and rejects unrecorded/missing files, incorrect hashes/sizes and modified hint bytes. The PR CI runs the Docker/nonroot test in the existing `static-tooling-install` job.

Approved application selection, six-hour catalog lifetime, complete new Run preflight, producer `--expected-run`, immediate pre-upload Run verification, independent candidate checks and isolated static upload are unchanged.
