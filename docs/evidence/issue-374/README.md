# #374 実GPV検証の再現手順

結論・資料出典・採用/不採用の理由は[技術検証報告](../../wx_profile_feasibility.md)が正本。
このディレクトリのコード・NPZ試作は製品から使用しない。

- `results.json`: 入力4ファイルのURL/SHA-256/サイズ、全messageの要素・面・時間・格子inventory、資源測定、閾値感度。OS情報は実行環境、Runは2026-09-12 00 UTC。
- `profile.csv`: ユーザー指定KML経路、49地点×12面×2出発×2モデル。NAと地表下の状態を分ける。小数桁数は計算再現用で、物理的精度を意味しない。
- `profile.png`: matplotlibによるRH断面。製品UIの試作・承認済みUI文言ではない。
- `reproduce.py`: 原GRIBの検査、現行public codecの往復、追加試作NPZ、route sampling、測定。private helperはbundled 0.6.0に固定した調査用の再利用であり、後続のアプリAPIにしない。
- `test_reproduce.py`: 双線形/時間補間、NaN、欠けた時刻/面、coverage外、経路順序の5テスト。

GRIBと生成NPZは一時領域に置き、リポジトリへ含めない。公開元は京都大学RISHのGPVアーカイブ、データ作成元は気象庁。
検証済みのchecksumに一致する入力が得られない場合、今回と同じ事例の再現成功とは扱わない。

## 実行

Python 3.12と`vendor/jma_gpv_weather-0.6.0-py3-none-any.whl`のデスクトップ依存環境を使う。
今回のNumPyは2.5.2、pygribは2.1.8。図だけmatplotlibを追加した一時環境を使用した。
実行前にcheckoutに対応したwheelを利用していることを確認する。

```sh
python -m pip install vendor/jma_gpv_weather-0.6.0-py3-none-any.whl pygrib matplotlib
```

原データを保存済みのhashに照合して取得する（約176 MiB）。以下はリポジトリrootで実行する。

```python
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

raw = Path('/tmp/navmate-374-raw')
raw.mkdir(exist_ok=True)
results = json.loads(Path('docs/evidence/issue-374/results.json').read_text())
for model in ('MSM', 'GSM'):
    for source in results[model]['sources']:
        path = raw / source['url'].rsplit('/', 1)[1]
        if not path.exists():
            with urlopen(source['url'], timeout=180) as response:
                payload = response.read(source['bytes'] + 1)
            assert len(payload) == source['bytes']
            assert hashlib.sha256(payload).hexdigest() == source['sha256']
            path.write_bytes(payload)
        assert path.stat().st_size == source['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
```

```sh
python docs/evidence/issue-374/test_reproduce.py
MPLCONFIGDIR=/tmp/navmate-374-mpl python docs/evidence/issue-374/reproduce.py \
  --raw /tmp/navmate-374-raw --output /tmp/navmate-374-reproduced --plot
```

Linuxの`/proc/self/status`を使う測定のため、他OSではその部分を同等の実測へ置換する必要がある。
図は`--plot`を省略できる。速度・RSS・プラットフォーム文字列は環境依存。
入力hash、inventory、profile値、閾値集計とbaseline fingerprintは同一入力/依存で照合できる。
NPZの圧縮bytes/hashはNumPy・zlibの差でも変わり得る。

## 検証範囲

0.6.0のpublic codecで圧縮/検証/再読込し、既存の風・気温・HGTを含む全record配列のfingerprintが不変であることを確認した。
pressure RHを既存codecへ加えると拒否されることも確認した。これを成功する新codecの実装とは扱わない。
実GRIB内の対象範囲にはNaN欠測がなかったため、欠測時の振る舞いは小さい人工格子を使うテストで検証した。
観測精度の検証、本番Feed変更、実機Safari、製品画面、Docker Composeは本調査の実測対象に含めていない。
