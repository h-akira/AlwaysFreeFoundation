# AlwaysFreePlatform

OCI の Always Free を最大限に使い、個人開発の複数のプロジェクトを **少ない VM と1つの DB に相乗り** させる共通基盤。コマンド名は `afp`。

- プロジェクトは決められた約束のファイルを置くだけで載せられる。
- 各プロジェクトのリポジトリにタグを push すると、ビルドから本番へのデプロイまで自動で行う。
- VM はステートレス。消えても作り直せば自動で元に戻る。
- 基盤はプロジェクトの中身を知らないので、プロジェクトは非公開のまま載せられる。

> 開発中。まだ動くものはない。

## 文書

前から順に読む。

| 文書 | 内容 |
|---|---|
| [01 目的と方針](docs/01_purpose.md) | なぜこの基盤があるのか、何を優先するのか、向く使い方と向かない使い方 |
| [02 構成と決定](docs/02_architecture.md) | 前提にした無料枠、全体の構成、主な決定と採らなかった案 |
| [03 役割と責任](docs/03_responsibilities.md) | 基盤の管理者とプロジェクトの管理者の分担と境目 |
| [04 基盤を使う](docs/04_using.md) | プロジェクトの管理者向け。基盤に載せるための約束 |

参考資料（それだけで読める独立した資料）:

| 資料 | 内容 |
|---|---|
| [OCI の無料枠](docs/references/oci-free-tier.md) | Always Free の枠・制約・アイドル回収（確かめた日付と出典つき） |
| [MySQL でアプリを書くときの注意](docs/references/mysql-notes.md) | ほかの DB（PostgreSQL など）との違い、日本語の照合順序、HeatWave の版の上がり方 |
| [OCI Bastion](docs/references/oci-bastion.md) | プライベート・サブネットの資源に手元から入る方法（ポート転送） |
| [OCI Resource Manager](docs/references/oci-resource-manager.md) | Terraform を OCI の側で実行するサービスの使い方と癖 |
| [OCI Vault](docs/references/oci-vault.md) | 鍵とシークレットの削除待ちと、それが削除に与える影響 |
| [OCI DevOps](docs/references/oci-devops.md) | VM へのデプロイ（インスタンス・グループ・Run Command）の仕組みと制約 |
