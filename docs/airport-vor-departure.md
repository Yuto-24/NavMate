# 出発位置の VOR Tracking Mode

VOR Tracking Mode は、登録済み14空港の出発位置を対応する VOR の座標へ切り替える。
空港敷地外の対応局も含む。地図上で VOR を選ぶ必要はない。
到着位置や NAV LOG の VOR/DME 列の選局とは独立している。

## 変更するもの・保持するもの

- 変更するもの：先頭経路点の座標・表示名・出典、および第1 Physical LegのVAR・MC・MHの磁気基準。MAP作成とKML取込の両方に適用する。
- 保持するもの：出発空港ID、空港標高、離陸・上昇条件、到着点と到着処理。
- 開始位置の0.5 NM検証は、通常時は空港基準点、VOR Tracking Mode時は採用したVOR座標と比較する。
- モード変更後は再計算が必要。採用局の座標・出典も計算入力のfingerprintに含める。

## 対応局と根拠

[転記値と出典記録](evidence/airport-vor-departure.json)を参照。
実行時の明示対応表は `src/autonavlog/domain/airport_vor.py` にある。
近さから対応局を推定しない。鹿児島はKGE、岡山はOYE、高松はKTEのVOR座標を用いる。
KTEのDME座標はVOR座標と異なるため用いない。

根拠は提供されたAIP AD 2.19の14原本。PDFのページ番号、有効日、SHA-256を記録した。
PDF原本や非公開の保管先IDはリポジトリへ含めない。
これはライブNOTAM、局の供用状態、受信可能性を確認する機能ではない。

## 保存形式

Project本体のschemaは変更しない。`metadata.ui_state` はversion 8とし、
`departure_vor` に採用時の局ID・座標・出典を保存する。
version 3〜7のProjectは従来どおり読み込み、VOR未選択として扱う。
旧作業中セッションのモード項目欠落もAIRPORTへ移行し、未完の入力を保持する。

再読込や他の計画入力の更新では採用済みの局情報を保持する。
通常モードへ戻して再度VOR Tracking Modeを選ぶと、その時点の対応表を採用する。

## 第1 Legの磁気基準

第1 Physical Legの全Calculation Zoneは、出発局の公示Declinationを西正のVARとして
採用する。TCとWCAは従来のWGS84経路・風計算を維持する。詳細は
[計算規約](calculation_rules.md)を参照。任意のVOR/DME列の選局は影響しない。

公示偏差と出典の手で保守する原本は
`src/autonavlog/nav/data/vor_stations.json`だけとする。WebはこのJSONを直接importし、
Pythonはwheelに同梱した同じJSONを`importlib.resources`で読む。
Dockerのfrontend buildもこの原本を入力とする。Local/Pyodideのwheelには通常の
package dataとして含めるため、別の転記・生成手順は不要。

`stations`は従来のVOR/DME一覧、`departure_only_stations`は一覧に出さない出発専用局。
OYEは後者で管理する。Python側の検索表は実行時にこの原本から組み立てる。
座標の出典と偏差の出典の改訂日は異なる場合があるため、それぞれの出典を保持する。
今回の一本化では既存13局とOYEの採用値・出典を変えない。最新AIPの再調査ではない。
既存VOR/DME一覧にないOYEは、保存済み`RJOB__AD2_20260806.pdf`のp.7、
AD 2.19（ページ有効日2025-03-20）で`VOR (8°W/2016) OYE`、
座標`344501.38N/1335006.20E`を2026-11-15に確認した。
偏差は8°Wを採用し、年変化を加算しない。VOR/DME選局一覧は変更しない。

保存済みProjectの局ID・座標を対応表と照合して偏差を解決する。未知の局・座標や
偏差欠落では第1 LegのMC/MHを正常値として出さず、計算をブロックする。
偏差規則・値・出典をVORモードだけの計算fingerprintに加えるため、旧計算は再計算が
必要になる。Projectの保存schemaとAIRPORTモードのfingerprintは変更しない。
