# #335 Legacy移行案内の文言確認

Legacy移行案内・Accountダイアログ・関連エラーの文言は、Gemini／agyの修正版と
最終確認結果を逐語反映する。既存文言や仕様了承を理由に確認を省略しない。
機能テスト・独立レビュー・公開可否とは別の確認記録である。

## 実行記録

親タスクから受領した実行証跡に基づく。対象は変更前HEAD
`560956e37fd4e4f1d9f689e4906013f646fd25ac`。

- 環境・指定：WSL、agy 1.4.12、`--model gemini-3.8-flash-medium`、plan／sandbox／print。
- 修正版：2026-11-01 09:17:41–09:18:19 UTC。
- 最終確認：同日09:19:10–09:19:29 UTC。
- 両実行ともexit 0、SUCCESS、stderr空。応答に独立したバックエンドmodel IDはなく、
  確認できたのは指定modelである。
- 元artifact：Ubuntuタスク `01a1902f-b448-7112-a009-db24629e80c4` の
  `pr335-gemini-wording/`。認証情報や個人データは本記録に含めない。

| 証跡 | SHA-256 |
| --- | --- |
| revision.prompt | `90b444ca377c8d85f2923051461c9b44849f7050f41181e2cccdf00db9478f62` |
| revision output | `88439a1b4bcaf6dcc0a20c11914208d0c4e773ac844abe17ab4a70955d048e08` |
| final confirmation prompt | `ed603e43d207e8fb9dfeb954f8e8ffba02889987f816fddaf3dea14876b73490` |
| final confirmation output | `52975fd0a89e42b7c37d0051d349faf6193512025ca8cf785a8cabaf128cc99e` |
| final JSON | `3b6ce5d040b0d7e35aeb1acda19b54195ba1f5517f1f6532ff8d6a1d427df430` |

## 反映範囲と意味の保持

- `LegacyAccountControl.tsx`：告知見出し、2026年12月目途・確定日未定の説明、Google紐付けと
  初回ログインの順序、Account見出し・閉じる名称、状態・主操作・今回のみの継続操作。
- `legacyMigration.ts`：認証準備、設定取得、紐付け状態取得、移行要求、紐付けPOST、
  POST timeout、移行中断のフォールバック。進捗の確定文言は既存と一致するため保持。
- `firebaseAuthProvider.ts`：ポップアップ拒否・Googleログイン失敗の2文は確定値と一致し、変更なし。

設定GET・状態GETの失敗を「未設定」と断定しない。POSTの30秒期限は結果不明として伝え、
サーバーで紐付けが成立していないとは断定しない。明示dismissの中断は非表示のまま保持する。
サーバーの具体的な`body.error.message`と移行の`status.error`は維持する。
移行終端状態の中断文変更は、新しい取消機能を追加するものではない。

確定文言の反映後のブラウザー確認と独立差分レビューはPRに別記する。
本記録は本番公開・実Google同意画面・物理Safariの確認完了を示さない。
関連：[PR #335 Legacy起動時の移行案内](https://github.com/Yuto-24/AutoNavLog/pull/335)、
[Issue #336 UI文言確認の共通手順](https://github.com/Yuto-24/AutoNavLog/issues/336)。

## 2026-11-09: 起動案内の短縮

利用者のフィードバックに従い、起動案内だけを短縮した。新サービス名と画面・URLの移行、
Google紐付けを先に説明し、紐付け後に同じアカウントでのログインとブックマークを案内する。
「確定日未定」と移行中の説明を起動案内から外し、退出を「今回はスキップ」に変更した。
通常のAccountダイアログ、認証・移行処理、終了時期の目安は保持する。

- agy 1.5.3、指定モデル `gemini-3.8-flash-medium`、plan / sandbox / JSON出力。
- exit 0、status SUCCESS、1 turn。応答に独立したバックエンドモデルIDはない。
- 会話ID: `9d32b1a4-2455-4fa4-8d77-35831ad80e2c`。
- prompt.txt SHA-256: `559bf533c21adbabd32ce812229d227d1993a1c70118172d07831eeb3ed61a1b`。
- response.json SHA-256: `0f0ced13ba7ca52b3965f14a2c9c5133e3a2b673c55ac4fc81b0b4cd5193823b`。

確定文言（逐語反映。段落配置のみ状態に応じて切り替える）:

```json
{
  "title": "新サービス「NavMate」への移行",
  "announcement": "本画面は2026年12月を目途に提供を終了し、新サービス「NavMate」へ画面・URLを移行します。",
  "instruction": "今後はGoogleアカウント連携を利用します。まずは現在のデータをGoogleアカウントに紐づけてください。",
  "afterLink": "新サービスへ移動し、同じGoogleアカウントでログインしてください。",
  "bookmark": "移動後は新URLのブックマークをお願いします。",
  "primaryButton": "Googleアカウントを紐づける",
  "linkedStatus": "Googleアカウントに紐づけ済みです",
  "destinationButton": "NavMateを開く",
  "skipButton": "今回はスキップ"
}
```
