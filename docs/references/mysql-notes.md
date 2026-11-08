# MySQL でアプリを書くときの注意

MySQL（OCI の MySQL HeatWave を含む）でアプリを書くときに、ほかの DB、とくに PostgreSQL との違いで気を付けること。

## 1. PostgreSQL との主な違い

| 違い | どうするか |
|---|---|
| `RETURNING` が無い | ID はアプリで作ってから入れ（UUID など）、要るなら読み直す |
| DDL（`CREATE TABLE`・`ALTER TABLE`）がトランザクションに入らない | マイグレーションが途中で失敗すると、そこまでの変更が残る。マイグレーションを小さく分け、実行の前にダンプを取る |
| `ON CONFLICT` が無い | `INSERT ... ON DUPLICATE KEY UPDATE` を使う。制約の名前では指定できず、どの一意キーの衝突でも働く |
| UUID 型・配列の型が無い | UUID は文字列かバイナリ、配列は `JSON` にする |
| `DATETIME` は時差を持たない | UTC で保存し、アプリで変換する |
| `TEXT` の列に、長さを決めずに一意制約や索引を張れない | `VARCHAR(長さ)` にする |
| `ILIKE` が無い | `LIKE` が大文字と小文字を区別するかは、照合順序で決まる（§2） |
| 権限の付与にワイルドカード（`app_%` のような名前）を使えない場合がある | `partial_revokes` が有効だと、`%` や `_` がそのままの文字として扱われる。データベースの名前は完全な形で書く |

## 2. 日本語の照合順序

MySQL 8.0 以降の既定の照合順序 `utf8mb4_0900_ai_ci` は、アクセントと大文字・小文字を区別しない（`ai`: accent insensitive、`ci`: case insensitive）。日本語では濁点・半濁点もアクセントとして扱われるので、**「ハ」「バ」「パ」が同じとみなされる**。

- 一意制約: 「ハート」と「パート」を同じ値とみなし、両方は入らない。
- 検索: 「ハ」で探すと「バ」「パ」も当たる。

区別したいときの候補:

| 照合順序 | 内容 |
|---|---|
| `utf8mb4_0900_as_cs` | アクセントと大文字・小文字を区別する |
| `utf8mb4_ja_0900_as_cs` | 日本語用。アクセントと大文字・小文字を区別する。ひらがなとカタカナは同じとみなす |
| `utf8mb4_ja_0900_as_cs_ks` | 日本語用。上に加えて、ひらがなとカタカナも区別する（`ks`: kana sensitive） |
| `utf8mb4_bin` | バイトの並びで比べる。最も厳密だが、並び順は人の感覚と合わない |

どれが合うかは、アプリの一意制約と検索で実際に試して決める。

## 3. MySQL HeatWave の版

- MySQL HeatWave の Always Free の DB は、作るときに最新の版になり、**保守のたびに最新の版へ上がる**（[oci-free-tier.md](oci-free-tier.md) §3）。
- 最新の版（Innovation の系列）は、版ごとに機能の削除や既定値の変更がありうる。版が上がったら、手元の MySQL を同じ版にしてテストを流し直す。
- いまの版は `SELECT VERSION();` で確かめられる。

## 4. 出典

- [MySQL 8.4 Reference Manual: Unicode Character Sets（照合順序の名前の意味）](https://dev.mysql.com/doc/refman/8.4/en/charset-unicode-sets.html)
- [MySQL 8.4 Reference Manual: Partial Revokes](https://dev.mysql.com/doc/refman/8.4/en/partial-revokes.html)
- [MySQL 8.4 Reference Manual: Statements That Cause an Implicit Commit](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html)
