# 地形入力と被覆の検証

Issue [#313 GSI DEM・標高KMLの入力検証](https://github.com/Yuto-24/NavMate/issues/313) の入力境界。
`web/src/terrain.ts` と `terrainTransport.ts` は、評価領域に必要な画素・標高・欠損・出典を返す。
`terrainKml.ts` は、別途確認した地形点KMLを検証する。
NAV LOG、Route、Project保存、気象にはまだ接続していない。
SEA算式、C'k Point間の左右3 NM領域、手動値、表示は後続の #314 / #315 で扱う。

## GSI DEM10B

- 正本は国土地理院の `dem_png/14/{x}/{y}.png`。TXT版は2024年10月以降更新停止のため使用しない。
- 256×256、8 bit RGB PNG。RGBを24 bit符号付きcmとして復号し、mへ変換する。
  `(128, 0, 0)` は欠損で `null` を返す。0 m、負標高と区別する。
- XYZ Web Mercator、xは東向き、yは南向き。入力座標は経度・緯度（度）の順。
- 標高はGSIが公開する標高値。日本の標高は原則TP（東京湾平均海面）だが、離島独自の基準がある。
  タイル自体は画素ごとの基準・測量時点・改定年度を含まない。全画素を特定年度のTPに変換済みとは扱わない。
- DEM10Bの原資料は約10 m格子だが、z14の画素は周囲の標高点を平滑化した値。
  全画素取得は実地形の絶対最高点や運航安全性の保証ではない。人工構造物を含まない。
- 主な整備対象は日本。日本国内でも水部・境界・未整備域に欠損や不確かな値がある。
  地域名やHTTP 200だけで完全被覆と判定しない。

出典・現行仕様（2026-11-09確認）:
[地理院タイル一覧](https://cyberjapandata.gsi.go.jp/development/ichiran.html)、
[PNG標高タイル仕様](https://maps.gsi.go.jp/development/demtile.html)、
[標高タイルの作成方法と制約](https://maps.gsi.go.jp/development/hyokochi.html)、
[日本の測地系](https://www.gsi.go.jp/sokuchikijun/datum-main.html)、
[基盤地図情報FAQ](https://www.gsi.go.jp/kiban/faq.html)。

## Local-firstでの取得

ブラウザからGSIへHTTPSで直接取得する。サーバー、Worker、気象配信への追加は不要。
credentialsを送らず、redirectを許可しない。固定ホスト・z14・整数タイル座標に限定する。
HTTP 404は `missing`、通信/HTTPエラーは `not-acquired`、不正PNGは `invalid`。
PNGの寸法、RGB形式、chunk境界・CRC・終端を検証する。色補正metadataや透明色を拒否し、
画像を拡縮せず、色変換なしで復号する。ブラウザAPI非対応も不正入力として未確定を維持する。

1応答512 KiB、1要求10秒、領域取得は既定60秒のAbortSignalを渡す。
領域は外接矩形で64タイル以内、頂点128個以内。上限超過は `invalid-input` であり、
小さく切り詰めて完全被覆にしない。広域の分割・全体集約は呼出側の責任になる。
source instanceごとに検証済みPNGを最大16枚・24時間までメモリ内に保持する。
永続キャッシュ、Project保存、オフライン継続保証は追加しない。
再取得時にはHTTPキャッシュを再検証し、メモリキャッシュ利用時は元の取得時刻を保持する。

各タイルにはURL、取得時刻、SHA-256、出典、単位、水平・鉛直基準を付ける。
SHA-256は取得内容を識別するもので、GSIが保証する版番号や完全性証明ではない。
後続の表示には国土地理院への出典リンクと制約を引き継ぐ。

## 領域と結果の契約

`planTerrainCoverage(region)` は取得前の状態を返す。
`acquireTerrainCoverage(region, load, signal?)` はタイル取得後の状態を返す。
`region` は始点を末尾に重複させない、自己交差のない単一polygon。
辺はWeb Mercator上の直線であり、大圏・測地線の飛行経路ではない。
穴・日付変更線越え・極域をサポートせず、無効入力として返す。
左右3 NMの測地的な領域の構築・必要な分割は #314 で行う。

polygon内部または境界と接する**画素の閉じた範囲**をすべて選択する。
境界の外側に中心がある画素も含むため、被覆判定は保守的になる。
境界の欠損を除外したり、離散的な点サンプルだけで領域の完全性を主張したりしない。

```ts
const source = new GsiDemSource();
const coverage = await acquireTerrainCoverage(region,
  (x, y, signal) => source.tile(x, y, signal));
```

- `complete`: 選択された全画素に有効な標高がある。実地形の最高点を保証しない。
- `incomplete`: 未取得、欠損、不正のいずれかがある。有効な部分の値も保持する。
- `invalid-input`: 領域が不正または処理上限超過。取得を開始しない。

`counts` は必要/有効/欠損/未取得/不正の画素数を区別する。
各tileの `pixels` は256×256の行優先index、`input.elevations` はmまたは `null`。
後続計算は `pixels` に含まれる値だけを評価し、`incomplete` の部分最大値を確定SEAにしない。
例外・失敗の結果も呼出元に返すだけで、既存RouteやLocal保存を変更しない。

## 地形点KML

`parseTerrainKml(text, evidence?)` は、Route用Importとは独立した、plain KMLの入力境界。
このIssueではファイル選択UIや既存のRoute用Importに接続しない。
KMLのPoint高度だけから、地表か飛行高度か障害物頂部かを推定しない。
次の出典確認を呼出側から渡した場合だけ、有効な地形点を返す。

| evidenceの項目 | 採用条件 |
| --- | --- |
| `source` | 作成元・資料の識別子がある |
| `meaning` | 当該ファイルの点が地表標高であると確認した `terrain` |
| `verticalReference` | 実際に格納された数値の標高基準が `TP` |
| `demCompatibilityEvidence` | 全点の地域・標高基準・測量/改定時点を、使用するDEMと照合した根拠がある |

これらはKML内の自己申告やファイル名から自動生成しない。
`evidence` は呼出側が資料を確認して渡す契約であり、文字列があるだけで出典の真偽を認証する機能ではない。
通常のKMLは経度・緯度がWGS84、absolute高度がEGM96基準のmである。
`absolute` や「MSL」だけではTPとの同一性を確認できない。
TP値を格納した資料として明示確認された入力のみ、この境界で比較候補にする。
EGM96・楕円体高・基準不明・DEMとの整合未確認は `unconfirmed` として値を採用しない。
ジオイド変換は実装しない。離島独自基準や異なる成果年度を一律TPとして合算しない。
仕様の根拠は [OGC KMLの座標参照系・altitudeMode](https://docs.ogc.org/is/12-007r2/12-007r2.html)。

対応形式はKML 2.2 namespace（OGCおよび旧Google namespace）の、1 Placemarkに1 Point。
`coordinates` は `longitude,latitude,elevation` の有限数値3項、経緯度は地球上の範囲、
`altitudeMode` は明示された `absolute` が必要。高度の省略を0 mにしない。
Pointの集合として扱い、線・面・経路・MultiGeometryの高度を地形の補間面に変換しない。
相対高度、clamp、gx高度mode、説明HTMLのHeight/Elevationなども採用しない。
KMZは対象外。2 MiB・10,000 Placemarkまでを受け付け、超過を部分取込しない。
DTD/entity・NetworkLinkは拒否し、Icon・Style・説明HTMLの参照先へアクセスしない。

- `absent`: KML無し（`null`）。
- `available` / `partial`: 採用可能な点がある。`partial` は不採用点のindexと理由も返す。
- `empty`: Placemarkがない。
- `invalid`: XML・形式・数値・上限などが不正で、採用可能な点がない。
- `unconfirmed`: 地形点の意味、出典または標高基準・整合の確認が足りない。
- `excluded`: 障害物資料として指定された入力。

出典確認、入力文字列のUTF-8 SHA-256、取込時刻、m単位、座標/標高基準をprovenanceに保持する。
数値の0 mと負標高は有効。不採用値はゼロ補完しない。
`terrainContainsPoint(coverage, point.coordinate)` でDEMと同じpolygon内・境界上の点を選べる。
範囲外の点は最高値候補にしない。
KMLの被覆は常に `points-only`。有効点があっても、その周囲や未取得のDEM領域を被覆したと扱わない。
有効なKML点がない場合は後続計算でDEMのみを使用できるが、DEM自身の不完全被覆は解消しない。

### 提供されたAREA1 KMLの扱い

`AREA1_45_MIYAZAKI_20261029.kml` は145件の障害物Pointを持ち、風車・鉄塔などが含まれる。
説明欄には `Height` / `Elevation`、`OTHER:TP`、`Metric` がある一方、
座標の第3値は `YES` / `NO` で、`altitudeMode` がない。
ユーザーの2026-11-09の確認に従い、障害物を除外する。
説明欄の数値を地表標高へ転用したり、ElevationからHeightを引いて地形点を生成したりしない。
`obstacle-shape.kml` はこの構造を再現した合成fixtureで、提供ファイルそのものは同梱しない。

## 検証

`npm --prefix web run test:application -- terrain-unit.spec.ts` は数値復号、領域境界、凹polygon、
欠損/未取得/不正、通信とキャッシュを検証する。
`npm --prefix web run test:terrain` はChromium/WebKitでPNGの数値復号とKMLの
無し/有効/不正/標高基準未確認/障害物除外、境界・範囲外、外部通信の抑制を検証する。
`dem-signed.png` は独立した合成RGB fixtureであり、GSIの観測値ではない。
UI・レイアウトの変更はなく、Composeの検証は対象外。

実データの限定確認（2026-11-09）:
`dem_png/14/14174/6668.png` はHTTP 200、102,668 bytes、CORS `Access-Control-Allow-Origin: *`。
SHA-256は `c30fad6bc8ca2ce64e4d6cb297425ba507ac0f3bec709bebfc7713387da396b4`。
Python標準ライブラリのzlibとPNG filterの独立復号に対し、Chromium/WebKitで全65,536画素が一致した。
うち2,942画素は欠損。これは1タイルの取得/復号の証拠であり、Route全域の完全被覆、
GSIの更新時点、SEAの正確さ、実運航受入の証拠ではない。
