# 選手交代の運用マニュアル

更新日: 2026-08-13
対象: leader / corder (エージェント間運用)
関連: [roster_change_and_record_policy.md](roster_change_and_record_policy.md)（エントリー変更・個人記録の運用方針=上位方針）

## 目的

大会期間中に頻発する【選手交代】指示を、**正確・高速・再現可能**に反映するための手順書。
「監督が何を言ったか」→「config にどう落とすか」→「個人記録をどう扱うか」→「何を検証して報告するか」を一気通貫で定義する。

## 1. 監督指示の受領フォーマット

監督指示は次の2経路で届く。**両方とも「大学名」「区間」「交代(旧→新)」の3要素を必ず確認する。**

### 1.1 5ch スレッドの【選手交代】投稿（自動検出）

```
【選手交代】
大学名: <大学名>
区間: <N区>
交代: <旧選手>→<新選手>
```

- `process_substitutions.py` が 00:02 / 13:02 に自動検出・適用する
- 適用結果は `logs/substitution_audit.jsonl` に `status=applied` / `review` で記録される
- **`review` になった投稿は leader が trip 等を確認し、corder に手動反映を指示する**（実例: 鳥取大学 2026-08-13、trip 末尾の `.` 差異で mismatch）

### 1.2 leader からの agmsg 指示（手動反映依頼）

```
選手交代を反映してください。大学名: <大学名>、区間: <N区>、交代: <旧>→<新>。
対応結果を返信してください。
```

- メッセージ内の大学名は **config の正式名と一致するまで照合**する（「山梨学院」→「山梨学院大学」等）
- 交代方向 `旧→新` の意味を誤読しない: **「旧選手が外れ、新選手が入る」**
- 5ch の `substitution_audit.jsonl` に同内容の記録があるか確認し、bot 適用済みなら重複反映しない（逆に取消済みなら注意。§7）

## 2. 反映前の現状把握（必ず実施）

1. `git status` / `git log --oneline -3` で作業ツリーと最新コミットを確認（leader 並行作業検出）
2. 対象チームの config 現状を確認:
   ```bash
   python3 -c "
   import json
   d = json.load(open('config/ekiden_data.json'))
   for t in d['teams']:
       if '<大学名の一部>' in t.get('name',''):
           print(t['id'], t['name'])
           print('runners:', t['runners'])
           print('substitutes:', t.get('substitutes', []))
           print('substituted_out:', t.get('substituted_out', []))
   "
   ```
3. 交代対象選手の出走有無を `data/individual_results.json` で確認
   - `records` が空 or キーなし = **未出走** → §3 のみで完了
   - `records` あり = **既出走** → §3 + §4 + §5 を実施（東北大学 f8cc0d3c07 先行例）
4. `data/realtime_report.json` の該当チーム `runner` / `nextRunner` を確認

## 3. 区間指定の反映手順（config/ekiden_data.json）

**対象: 全交代（未出走・既出走とも必須）**

`config/ekiden_data.json` の該当チームを編集する:

1. `runners` 配列の **index = 区間-1** を差し替える（例: 8区 → `runners[7]`）
2. 入る選手を `substitutes` から削除する
3. 外れる選手を `substituted_out` へ移動する（なければ新規追加）
4. 選手形式は **文字列→文字列、dict(station_code)→dict で統一**（形式を変えない）

```jsonc
// 例: 鳥取大学 8区 津和野→境
"runners": [..., "山口（山口）", "境", "智頭", "米子"],   // runners[7] = 境
"substitutes": ["萩", "防府"],                            // 境 を削除
"substituted_out": ["津和野"]                             // 津和野 を追加
```

**state ファイル（ekiden_state.json）はこの時点では触らない。** 次回 realtime 実行で自動反映される。

## 4. 交代前選手の個人記録クリア（既出走時のみ）

交代で外れる選手が**既に出走済み（records あり）**の場合、`data/individual_results.json` の該当選手を空にする:

```jsonc
// 例: 津和野
"津和野": { "totalDistance": 0, "teamId": 9, "records": [], "legSummaries": {} }
```

- 空にするフィールド: `totalDistance` / `records` / `legSummaries`（**3つとも**）
- `teamId` は保持（将来の再登録に備える）
- 選手エントリ自体は削除しない
- 新選手（入る側）のレコードは**用意しない**。次回 realtime 実行が自動で付ける
- 保存は**原子的に行う**（temp ファイル → `os.replace`）。バックアップを /tmp に取ってから作業する

```python
import json, os, tempfile
path = 'data/individual_results.json'
d = json.load(open(path, encoding='utf-8'))
for name in ['<旧選手1>', '<旧選手2>']:
    if name in d:
        d[name] = {"totalDistance": 0, "teamId": d[name].get('teamId'),
                   "records": [], "legSummaries": {}}
fd, tmp = tempfile.mkstemp(dir='data', suffix='.tmp')
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2, ensure_ascii=False); f.write('\n')
os.replace(tmp, path)
```

## 5. realtime_report.json の更新（既出走時のみ）

既出走の交代では `data/realtime_report.json` の該当チーム `runner` を新選手に差し替える:

```jsonc
"runner": "8境"     // 旧: "8津和野"
```

- 表示形式は `<区間番号><選手名>` を維持
- `nextRunner` は config 変更後の次回 realtime 実行で自動導出されるため、原則そのまま
- 参考: 東北大学 f8cc0d3c07（runner 差し替え・todayDistance 維持の先行例）

## 6. 重複・区間ずれ検証（必ず実施）

### 6.1 config 検証（全チーム）

```python
def nm(e): return e['name'] if isinstance(e, dict) else e
errors = []
for t in d['teams']:
    r = [nm(x) for x in t.get('runners', [])]
    if len(r) != 10: errors.append(f"{t['name']}: runners {len(r)} != 10")
    if len(set(r)) != len(r): errors.append(f"{t['name']}: runners 重複")
    dup = set(r) & set([nm(x) for x in t.get('substitutes', [])])
    if dup: errors.append(f"{t['name']}: runners/substitutes 重複 {dup}")
```

### 6.2 個人記録と state の整合

対象チームの `individual_results` 合計が `ekiden_state.json` の `totalDistance` と一致すること:

```bash
python3 scripts/validate_race_state.py
```

- **exit 0** = 問題なし
- **exit 2** = 警告のみ（他チームの既存 W1 等は許容。**対象チームが新規警告に入っていないこと**を確認）
- **exit 1** = fatal → コミットしない。原因調査

### 6.3 観測所の存在確認

新選手が `amedas_stations.json` に登録済みか確認（見つからなければ次回 realtime で `地点不明` になり距離 0 になる）:

```bash
python3 -c "
import json
st = json.load(open('config/amedas_stations.json'))
for nm in ['<新選手>']:
    print(nm, [s for s in st if s.get('name') == nm])
"
```

## 7. 監督による取消・訂正が出た場合の扱い

**5ch の流れ（実例: 山梨学院大学 2026-08-12〜13）:**

1. post 294: 【選手交代】浜松→飯山 → bot が 13:02 に `applied`
2. post 295: 「>>294 取消でお願いします」→ **監督が交代を取り消し**
3. post 303: 「>>295 反映よろしくお願いします」→ 取消の反映依頼

**対応ルール:**

- `substitution_audit.jsonl` に `status=applied` の記録があっても、**後続の取消投稿（>>294 取消）を確認したら取り消す**
- 取消の反映 = **bot 適用前の状態に復元**する:
  - `runners` を元の選手に戻す
  - 外れていた選手を `substitutes` に戻す（元の位置・形式で）
  - `substituted_out` から復帰選手を削除（空なら `[]`）
- **leader の指示が二転三転した場合は、最新メッセージを正とする**（例: 「取り消し指示は撤回します」→ 反映指示が有効）
- 判断に迷う場合（旧選手の行き先: substitutes vs substituted_out 等）は、**推測せず leader へ確認**するか、報告に明記して確認を促す

## 8. 完了報告テンプレート（leader へ agmsg 返信）

```
【対応結果】<大学名>の<N区>選手交代を反映しました。

■ 反映内容
<大学名> <N区>: <旧>→<新>
- config: runners[<N-1>]=<旧>→<新>、substitutes から削除、substituted_out=[<旧>]

■ 追加修正（既出走の場合）
- data/individual_results.json: <旧> の day<N> 記録をクリア（totalDistance 0, records [], legSummaries {}）
- data/realtime_report.json: runner 表示を <N><新> へ差し替え

■ 検証
- config: 全チーム runners 10人・重複なし OK
- validate_race_state.py: exit <0|2>（<警告状況>・fatal 0）
- 観測所: <新選手>(<code>) アメダス登録あり

■ commit / push
- commit: <hash> / push: <旧>..<新> main→main（origin/main と HEAD 一致確認済み）
```

送信は `~/.agents/skills/agmsg/scripts/send.sh <team> <agent> leader "<本文>"`。
**送信前にユーザーへ確認しない**（ユーザー指示 2026-08-05）。BLOCKED されたら再送・別経路禁止。

## 9. 完了条件チェックリスト

- [ ] 監督指示の3要素（大学名・区間・交代方向）を確認した
- [ ] 交代方向 `旧→新` を誤読していない（旧=外れる、新=入る）
- [ ] `runners[index=N-1]` を差し替えた
- [ ] 入る選手を `substitutes` から削除した
- [ ] 外れる選手を `substituted_out` へ移動した
- [ ] 既出走なら `individual_results` の旧選手 3フィールドを空にした（原子的保存・バックアップ済み）
- [ ] 既出走なら `realtime_report.json` の `runner` を差し替えた
- [ ] config: 全チーム runners 10人・重複なし
- [ ] `validate_race_state.py` が exit 0/2 で、対象チームが新規警告に入っていない
- [ ] 新選手の観測所が `amedas_stations.json` に存在する
- [ ] `git add` は対象ファイルのみ（data/ の bot 自動更新差分を混入させない）
- [ ] commit → push origin main → `git rev-parse HEAD` == `git ls-remote origin main` を確認
- [ ] agmsg で完了報告（テンプレート§8）を送信
