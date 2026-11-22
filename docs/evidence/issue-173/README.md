# #173 DESCENT時間整合性とGoogle Earth受入資料

2026-11-23時点で、DESCENT時間の過不足を拒否する修正を行い、受入用KMLを用意しました。
**Google Earthでの実表示は未確認です。実表示の受入が終わるまで[#173 3D KML出力](https://github.com/Yuto-24/NavMate/issues/173)はCloseしません。**
これらは合成FTD検証用の計画です。

## 修正と検証の境界

保存済みの垂直降下480秒・減速60秒に対してDESCENT区間が600秒あると、従来は水平部分が120秒になりました。
最新mainの`069d096aba2b994c58077176ae255da57fffac9d`で追加した回帰テストは、超過側4件が失敗し、不足側4件が成功しました。
共通Vertical Profileで過不足を同じ許容差で検査する修正により、保存値にない水平部分の出力を防ぎます。

不整合な結果でもLast CalculationとNAV LOGは保持し、明示的な再計算まで3D出力を不可にします。
[#472 EOC高度連続性](https://github.com/Yuto-24/NavMate/pull/472)で確定した、根拠のあるsnap時間差を30秒以内に限って描画補正する例外は維持します。
RJFM帰路も距離÷GSで時計を置き換えず、保存された運用時間を使用します。仕様は[Platform Capability](../../platform_capabilities.md#3d-kml-エクスポートgoogle-earth-用にエクスポート)と[計算規則](../../calculation_rules.md#descent--eoc)を参照してください。

## ローカル検証結果

生成元SHAの実装をDocker test stageで検証し、全pytestは3,824件成功・1件スキップでした。
root実行でスキップされた権限テスト1件は非rootで補完実行し成功しています。
Ruff・mypy・release・データ/schema検査・wheel/sdistビルドも成功しました。
Web型検査、Local静的ビルド、Platform／KML unit 8件、KML保存・stale・再読込を含むブラウザ回帰1件が成功しています。
同封ZIPのprofileからKML3件を再生成し、byte単位で一致することも確認しました。
Hosted CI、CodeRabbit、Google Earth実表示、本番公開の結果を示すものではありません。

## 受入ファイルと期待値

生成元コミットSHA、ファイルSHA-256、EOC・LEVEL OFF・到着点の座標／MSL高度／経過秒は[manifest.json](acceptance/manifest.json)に記録します。
[sources.zip](acceptance/sources.zip)には各ケースのLast Calculationと共通プロファイルを格納しています。
KMLは製品の既存serializerで生成し、XMLの全経路座標・マーカー座標・高度モードを共通プロファイルと照合します。

| KML | EOC→降下終点 | 垂直降下 | 水平減速 | 確認する特徴 |
| --- | --- | --- | --- | --- |
| [通常FTD](acceptance/general-ftd.kml) | 7,500→2,500 ft MSL | 300秒 | 60秒 | CLIMB、RCA、EOC、LEVEL OFF、地上CP、RJFS標高6 ftへの到着 |
| [RJFM帰路500 fpm](acceptance/rjfm-return-500.kml) | 4,500→1,500 ft MSL | 360秒 | 0秒 | 実UMK→ARITA、RJFM標高19 ftへの到着 |
| [RJFM帰路1,000 fpm](acceptance/rjfm-return-1000.kml) | 4,500→1,500 ft MSL | 180秒 | 0秒 | 同じ物理経路で運用時間が異なる |

## Google Earthで確認すること

1. 3つのKMLを開き、飛行経路がMSL高度を持つ立体経路として表示されることを確認します。KMLの高度値はftを0.3048倍したmです。
2. フォルダー内のCLIMB / CRUISE / DESCENT / VISUAL ARRIVALと、RCA / EOC / LEVEL OFFの位置を確認します。境界点の高度・経過秒はmanifestの期待値と照合します。
3. 通常FTDの「MSM CORE CP」が地上の目印として表示され、上空の飛行経路・計算境界と区別できることを確認します。CPの経過秒と高度は上空の正横点を表します。
4. RJFM帰路が実UMK→ARITA→RJFMを通り、参考案内用の西側延長が追加されていないことを確認します。ARITAで降下を終え、そのままVISUAL ARRIVALへ接続します。
5. Earthの版・確認日・対象SHA・各項目の結果と必要な画面証跡を記録します。不一致があれば#173へ残します。

数値・XMLの検証成功だけでは、この実表示確認を完了扱いにしません。

## 再生成と照合（開発者向け）

manifestの生成元SHAをcheckoutし、Dockerのtest stageとNode 22を使用します。
Pythonパッケージの版はcheckoutのVERSIONと揃えます。以下はリポジトリrootからのコマンドです。

```sh
PYTHONPATH=.:src python docs/evidence/issue-173/generate.py /tmp/navmate-173-acceptance
node docs/evidence/issue-173/export.mjs /tmp/navmate-173-acceptance
python docs/evidence/issue-173/verify.py /tmp/navmate-173-acceptance "$(git rev-parse HEAD)"
```

新規計算ではUUIDと作成時刻が変わるため、再生成ファイルのbyte一致は要求しません。
同封snapshotを使う場合は再計算せず、共通projectionを生成して同封profileと比較できます。
`sources.zip`を展開して`export.mjs`を実行すると、同封profileから同じKMLを生成できます。
`verify.py`はKML構造・座標・既知の降下時間を検査し、期待値とハッシュを記録します。

文書草稿はGemini 4 Neon Highで作成し、最終文面は実装・生成結果に合わせて修正しています。
GPT-6.1 Solが最終文面・生成処理・ZIP内データ・KML・manifestを読み取り専用で照合し、必須修正なしと確認しました。
