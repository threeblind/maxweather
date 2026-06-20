# 区間最高記録軍団 区間状態管理・日跨ぎ対応 詳細設計

作成日: 2026-06-21  
対象: `scripts/generate_report.py`、`data/ekiden_state.json`、`data/realtime_report.json`、`data/runner_locations.json`、`app_16.js`

## 1. 目的

速報マップの「区間最高記録軍団」が、日付を跨いだ後も直前区間の記録を加算し続ける問題を解消する。

区間最高記録軍団は、正規チームの現在区間とは独立して、次の情報から自身の現在区間を一意に決定する。

- スタート地点からの総合距離
- `ekiden_data.leg_boundaries`
- 区間ごとの歴代最高記録

フロントエンドによる区間推測を正とせず、バッチが確定した `currentLeg` をすべての出力へ明示する。

## 2. 現状と問題点

### 2.1 現状のデータ名

プロジェクト内では区間番号に複数の名前が使われている。

| 場所 | フィールド | 意味 |
|---|---|---|
| `data/ekiden_state.json` | `currentLeg` | 日次確定時点の保存区間 |
| `generate_report.py` の計算結果 | `currentLegNumber` | 計算開始時点の区間 |
| `generate_report.py` の計算結果 | `newCurrentLeg` | 今回計算後の区間 |
| `realtime_report.json` | `currentLeg` | 現在は `currentLegNumber` を出力 |
| `runner_locations.json` | 区間フィールドなし | 距離・座標のみ |
| `app_16.js` | `runner.current_leg` | フォールバック用だが通常データには存在しない |

`current_leg` を持っていないという指摘は、特に `runner_locations.json` について正しい。ただし根本原因は、バッチ内部に遷移後の `newCurrentLeg` が存在しても、速報ファイルへ遷移前の `currentLegNumber` を出力していることである。

### 2.2 現在の誤った処理

1. シャドーの処理開始時に `shadow_state.currentLeg` を読む。
2. 同じ区間に正規チームがいれば、その区間の記録を `todayDistance` に設定する。
3. `totalDistance + todayDistance` を計算する。
4. 正規チームが次区間へ進んだ場合だけ、シャドーの `newCurrentLeg` を増やす。
5. `realtime_report.json` には遷移前の `currentLegNumber` を書く。
6. `runner_locations.json` には区間番号を書かない。
7. 画面側が総合距離から区間を推測する。

このため、総合距離117kmで実際には2区に入っていても、バッチ上は1区・走者は梁川のままになり得る。

### 2.3 本日の同距離加算が起きる理由

1区の記録は38.967km/日である。現在の保存状態が `currentLeg: 1` のままなので、翌日も1区の梁川の38.967km/日を選択する。

本来、総合距離が1区境界100kmを超えた時点で、次回計算は2区の佐野・38.800km/日を使用しなければならない。

## 3. 確定仕様

### 3.1 基本原則

- 区間最高記録軍団の現在区間は総合距離から決定する。
- 正規チームの `currentLeg` はシャドーの区間判定に使用しない。
- 正規チームは、シャドーを走行させるかどうかの開始条件にのみ使用できる。
- 区間番号の正本はバッチ計算結果とする。
- JSONの公開フィールド名は既存形式に合わせて `currentLeg` とする。
- JavaScript内部で必要なら読み込み時に `current_leg` へ正規化してよいが、同じJSON内に両方は持たせない。

### 3.2 距離と区間の関係

境界値は `ekiden_data.leg_boundaries` を使用する。

```text
[100, 210, 310, 399, 522, 639, 735, 841, 942, 1055]
```

判定規則:

- `0 <= totalDistance < 100` → 1区
- `100 <= totalDistance < 210` → 2区
- `210 <= totalDistance < 310` → 3区
- 以下同様
- `totalDistance >= 1055` → ゴール

境界ちょうどは次区間とする。浮動小数点誤差を考慮し、比較時は既存の許容値または小数第1位への丸めを統一して使用する。

### 3.3 日次走行距離

その日の走行開始時点の総合距離に対応する区間の歴代最高記録を使用する。

例:

- 前日確定総合距離: 117.0km
- 117.0kmは2区
- 本日の走者: 佐野
- 本日の基準記録: 38.800km/日
- 本日計算後総合距離: 155.8km

同じ梁川の38.967kmを再利用してはならない。

### 3.4 1日の途中で区間境界を超える場合

現行データは区間記録を「km/日」として持っているため、1回の計算で使用する記録は走行開始時点の1区間分とする。

その日の距離加算後に境界を超えた場合:

- 総合距離は超過分を含めて保持する。
- `currentLeg` は計算後総合距離から次区間へ更新する。
- `runner` は計算後の現在区間の走者へ更新する。
- `todayDistance` はその日に実際に加算した値のままとする。
- 同じ実行内で次区間の記録を追加加算しない。

例: 1区を80.0km地点から開始し38.967km加算した場合、総合距離は119.0km、計算後区間は2区、表示走者は佐野とする。

### 3.5 走行開始・待機条件

シャドーを大会初日から無条件に走らせない既存仕様を維持する場合、次の条件とする。

- 正規チームに走行中チームが1校以上ある → シャドー走行
- 全正規チームが開始前または全校ゴール済み → シャドー待機または終了

「正規チームがシャドーと同じ区間にいること」は条件にしない。これを条件にすると、日跨ぎや先行時にシャドーが停止・巻き戻りする。

## 4. 実装設計

### 4.1 共通関数の追加

`scripts/generate_report.py` に距離から区間を決定する純粋関数を追加する。

```python
def determine_leg_from_total_distance(total_distance, leg_boundaries):
    """総合距離に対応する1始まりの区間番号を返す。ゴール時は len(boundaries) + 1。"""
```

要件:

- 数値でない距離、負数、空境界は明示的にエラーまたは安全な初期値へ処理する。
- 境界ちょうどは次区間。
- 正規チームとシャドーで同じ判定規則を再利用可能にする。

### 4.2 シャドー計算処理の変更

Step 2の開始時に、保存された `currentLeg` を信用せず、保存総合距離から開始区間を再計算する。

処理順:

1. `start_total_distance = shadow_state['totalDistance']`
2. `start_leg = determine_leg_from_total_distance(...)`
3. `shadow_team_data.runners[start_leg - 1]` から当日の記録を取得
4. 走行条件を満たす場合だけ `todayDistance` に記録を設定
5. `new_total_distance` を計算
6. `new_leg = determine_leg_from_total_distance(new_total_distance, boundaries)`
7. `new_leg` に対応する表示走者を決定
8. 計算結果へ遷移前と遷移後を明確に格納

推奨する内部構造:

```python
{
    "currentLegNumber": start_leg,
    "newCurrentLeg": new_leg,
    "runner": display_runner_name,
    "distanceRunner": distance_runner_name,
    "todayDistance": today_distance,
    "totalDistance": new_total_distance
}
```

`distanceRunner` はログ・検証用であり、公開JSONに必須ではない。境界を跨いだ日に「距離を作った走者」と「現在表示する走者」が異なるため、内部で区別すると誤実装を防げる。

### 4.3 正規チーム依存のワープ処理を削除

以下の考え方を廃止する。

- 正規チームが次区間へ入ったらシャドーも進める
- 次区間トップの総合距離へシャドーをワープさせる

シャドーは歴代記録を比較対象として走る仮想チームであり、正規チームの距離へ合わせると、歴代記録から算出した総合距離ではなくなる。

互換上ワープを残す必要がある場合でも、少なくとも区間番号はワープ前後の総合距離から再計算し、正規チームの区間番号を直接代入しないこと。ただし本設計ではワープ削除を推奨する。

### 4.4 速報JSONの修正

`save_realtime_report()` と `save_snapshot()` のシャドー出力では、遷移前の `currentLegNumber` ではなく、計算後の `newCurrentLeg` を `currentLeg` として出力する。

```json
{
  "id": 99,
  "name": "区間記録連合",
  "currentLeg": 2,
  "runner": "佐野",
  "todayDistance": 38.967,
  "totalDistance": 117.0,
  "is_shadow_confederation": true
}
```

注意: 上記例の `todayDistance` は1区の梁川がその日に作った距離、`runner` は計算後地点の現在走者である。混乱を避けるなら、公開JSONに次を追加してもよい。

```json
"distanceRunner": "梁川"
```

ただし画面で使用しないなら追加は任意とする。

### 4.5 `runner_locations.json` の修正

シャドーを含む全レコードへ `current_leg` を追加する。

```json
{
  "rank": null,
  "team_name": "区間記録連合",
  "runner_name": "佐野",
  "total_distance_km": 117.0,
  "current_leg": 2,
  "latitude": 0,
  "longitude": 0,
  "is_shadow_confederation": true
}
```

生成時は `newCurrentLeg` を使用する。`currentLegNumber` を使用してはならない。

### 4.6 `ekiden_state.json` の保存

`save_ekiden_state()` は現在も `newCurrentLeg` を `currentLeg` として保存しているため、基本方針は正しい。ただしシャドーの `newCurrentLeg` 自体を距離から算出するよう修正する。

保存前に次の整合性検証を入れる。

```text
saved currentLeg == determine_leg_from_total_distance(saved totalDistance)
```

不一致の場合は警告だけで継続せず、シャドーについては距離由来の区間へ補正して保存する。

### 4.7 フロントエンドの扱い

`app_16.js` は次の優先順位で区間を決定する。

1. `runner.current_leg`
2. `realtime_report.json` の該当シャドー `currentLeg`
3. 総合距離からの推定
4. すべて失敗した場合はポップアップを表示しない

ただし1と2が総合距離からの推定結果と異なる場合は、誤った走者を表示しないため、距離由来の結果を採用し、開発者向けに警告を出す。

現在の距離推定ロジックは安全弁として残すが、通常運用ではJSONの `current_leg` と一致することを前提とする。

## 5. 既存データ移行

現在のシャドー状態は `currentLeg: 1`、`totalDistance: 117.0` で不整合になっている。

修正リリース時に一度だけ、次の補正を行う。

1. `data/ekiden_state.json` のシャドーを取得
2. `totalDistance` から区間を再計算
3. 117.0kmなら `currentLeg` を2へ更新
4. 距離自体は変更しない

過去の `realtime_report`、スナップショット、履歴は原則書き換えない。現在状態だけ補正する。

移行処理は専用スクリプト化するか、読み込み時の自己修復として実装する。自己修復の場合は、補正した事実をログへ必ず出す。

## 6. 受け入れ条件

### 6.1 必須ケース

1. 総合距離99.9km → 1区・梁川
2. 総合距離100.0km → 2区・佐野
3. 総合距離117.0km → 2区・佐野
4. 117.0kmから翌日計算 → 2区記録38.800kmを加算
5. 計算後155.8km → `currentLeg: 2`、走者: 佐野
6. 210.0km到達 → 3区・伊勢崎
7. 日付変更後も区間が1へ戻らない
8. 正規チームが1区でも、シャドーが2区なら2区のまま走行する
9. `ekiden_state.json`、`realtime_report.json`、`runner_locations.json` の区間が一致する
10. 画面ポップアップに、区間番号・走者・記録・総合距離が同じ区間の組として表示される

### 6.2 回帰確認

- シャドーが総合順位・日間順位へ混入しない
- 個人記録・区間賞へ混入しない
- 通常チームの区間遷移に影響しない
- ゴール距離1055kmを超えてマーカーがコース外へ出ない
- `--realtime` を同じ状態で複数回実行しても、確定状態を保存しない既存仕様により距離が多重加算されない
- `--commit` 後の翌日初回速報で、前日の区間と距離を正しく引き継ぐ

## 7. テスト方針

距離境界判定を純粋関数に切り出し、最低限以下を自動テストする。

```text
-1, 0, 99.9, 100, 100.1, 209.9, 210, 1054.9, 1055
```

加えて、シャドー状態だけを一時JSONへ用意し、`--realtime` 相当と `--commit` 相当の連続実行を確認する。

重要な確認順:

1. 前日確定状態117.0km・誤った1区を読み込む
2. 読み込みまたは計算開始時に2区へ自己修復される
3. 2区記録38.800kmが選ばれる
4. 速報JSONへ `currentLeg: 2` が出る
5. 位置JSONへ `current_leg: 2` が出る
6. フロントが佐野・第2区・38.800km/日を表示する

## 8. 実装時の禁止事項

- `currentLeg` がない場合に常に1区へフォールバックしない
- シャドーの区間を正規チームの最小・最大区間へ強制的に合わせない
- 次区間トップの距離へ無条件にワープしない
- フロントだけで問題を隠さない
- `currentLegNumber` と `newCurrentLeg` を同じ意味として扱わない
- 区間境界の判定をPythonとJavaScriptで異なる比較条件にしない

## 9. 担当者向け実装順序

1. 距離から区間を返す共通関数を追加し、境界テストを作成
2. シャドーStep 2を距離基準の状態遷移へ変更
3. 正規チーム依存の区間遷移・ワープを削除
4. `save_realtime_report()` とスナップショットを `newCurrentLeg` 出力へ変更
5. `runner_locations.json` に `current_leg` を追加
6. 現在状態117.0kmを2区へ移行
7. フロントの区間取得優先順位と整合性チェックを実装
8. 日跨ぎシナリオをテスト
9. 実データを生成し、3ファイルと速報マップの表示が一致することを確認

