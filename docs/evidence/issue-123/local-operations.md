# Issue #123 initial automation tooling validation (2026-09-24)

> **日付付き初期実装検証（2026-09-24）**: #123 自動化ツール導入時点のローカル検証・独立レビュー記録です。現行の運用手順と最新クオータ方針（#281 分離後）は [static_operations.md](../../static_operations.md) を正本とします。

## 再利用可能な境界・レビュー指摘

- **no-new-Run の拒否**: 既存の保持資産のみを再パックして更新日時だけ延長した結果を、新 Run の公開成功として扱わない。
- **TAF の独立性**: TAF Worker の手動配備契約（#145）と `static-production.yml` の自動公開を混ぜない。
- **クオータ集計範囲**: 課金・無料枠の証拠は対象 account / project / owner および現在期間ウィンドウに厳密に一致させる。

## Local evidence (2026-09-24)

- Operational tests cover unknown/non-finite/stale/exhausted quota, wrong account/period,
  paid/billing state, retained payload corruption/traversal, expired catalog restoration,
  freshness warnings, canonical source mismatch after rollback, and retained-only producer
  output rejection. Optional-service quota exhaustion does not stop weather publication.
- Production artifact tests cover inventory/hash/runtime/dirty/expiry/budget rejection.
- Existing version, producer retention, runtime/reference/performance/schema validations
  and Web typecheck are exercised. GitHub workflow syntax is checked with actionlint 1.7.7.
- A real read-only restore from `navmate.pages.dev` recovered four retained assets; a local
  producer run on 2026-09-24 prepared two Runs for the next 24 hours, including
  `20260924090000`. No production catalog was changed.
- Worktree Compose project `autonavlog-wt-2f23dd26`, port 28033, was rebuilt/started without
  deleting a volume. `/healthz` returned `{"status":"ok","version":"1.20.1"}`.

Independent review identified retained-only catalog renewal, unsafe default TAF allowlist
publication, and quota account/window misattribution. The publication wrapper now rejects
no-new-Run results, TAF remains on #145's manual production contract, and quota evidence
is checked against configured account/project/owner and current provider windows.

## 2026-09-24 時点の未実施・残ゲート

本実装検証時点では本番環境・Secret/Variable・scheduler・Pages デプロイは未変更であり、実アカウントの Free/Spark クオータ監査、通知到達、旧期限を跨ぐ 2 回の定期更新、および同一オリジンロールバックは後続の本番承認ゲートとして残された（現行の運用・#281 分離方針は [static_operations.md](../../static_operations.md) を参照）。
