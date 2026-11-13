# Knowledge index

Read [the workflow](README.md) before adding or applying lessons. Search by the task, affected paths, tool, or error; inspect applicability before reuse.

## Existing canonical sources
- [Agent workflow](../agent_workflow.md)
- [Forecast schema 4 → 5 transition](../forecast_schema_transition.md): Issue #423。旧版生成データ、旧タブとの共存、同一端末 Latest 置換の了承範囲、手動公開の証拠と制約。最終v2.3.2候補への適用審査、元報告を保持するWSL helper、remote tag照合、受理済み記録を再生成しない運用。
- [Existing evidence](../evidence/)
- [App publication audit](../app_publication_audit.md): prepare/publish重複、排他、部分失敗、診断境界。2026-11-08のコード・実行証拠に基づく判断と未実装の後続案。
- [Schema #431 Actions prepare/publish](../schema431_actions_prepare.md): 固定toolingを維持した証拠転送、自己Runの識別、planへの個別承認と暗号化記録。30分期限内に公開へ進めるよう、公開経路を先に準備する。2026-11-13に確認した診断欠落、保存案内テストの文言不一致と候補の再審査、privateなcheckoutからDockerコピーへ引き継がれる権限不整合。実運用は別途承認・受入が必要。

- [MAP background imagery](../map_background.md): Issue #243の配信元・出典、倍率と欠損時の表示、端末保存の境界。
- [Terrain inputs](../terrain_inputs.md): Issue #313のDEM10B PNG復号、画素被覆、欠損と標高基準、実タイル確認の限界。

- [WX cloud/RH feasibility](../wx_profile_feasibility.md): Issue #374。指定KML経路のMSM/GSM実GPV、雲高推定の限界、portableの追加コストとAPI境界。2026-11-09確認、Safari実機は未検証。

## Reusable entries

No new lessons have been extracted by this setup. Add an entry only when supported by actual evidence.

| ID / entry | Trigger and scope | Status | Last verified / evidence |
| --- | --- | --- | --- |

Use [TEMPLATE.md](TEMPLATE.md); keep details in their canonical document and link here. Do not turn this index into a transcript or broad file inventory.
