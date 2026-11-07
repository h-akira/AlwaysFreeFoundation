# OCI の無料枠

OCI（Oracle Cloud Infrastructure）の無料枠を調べた結果。

- **確かめた日**: 2026-11-07（Oracle の公式文書）
- **無料枠は変わる**（2026-06 に A1 の枠が半分になった）。使う前に §6 の出典で確かめ直す。

## 1. 無料枠の種類

| 種類 | 内容 |
|---|---|
| Free Trial | 登録から 30 日間、一定額のクレジットで有料のサービスも試せる |
| **Always Free** | 期限なく無料で使える資源。Free Trial が終わっても残る。有料（PAYG: 従量課金）のアカウントでも使える |

## 2. Always Free の主な資源

| 資源 | 枠 |
|---|---|
| Compute: Ampere A1（`VM.Standard.A1.Flex`、Arm） | 月 1,500 OCPU 時間・9,000 GB 時間 ＝ 常時 **合計 2 OCPU・12 GB**。1台にまとめても、分けてもよい |
| Compute: E2.1.Micro（x86） | **2 台** まで。各 1/8 OCPU・1 GB |
| ブロック・ボリューム | ブートとブロックの **合計 200 GB**。バックアップ 5 個 |
| Object Storage | Always Free だけのアカウントで 20 GB。有料のアカウントでは種類（Standard・Infrequent Access・Archive）ごとに 10 GB。API 5 万回/月 |
| Vault | シークレット 150 個（各 40 版）。ソフトウェアで守る鍵は無制限 |
| MySQL HeatWave | **1 個**（§3） |
| Autonomous Database | 2 個。各 1 OCPU・20 GB・同時 30 セッション（§4） |
| Load Balancer | Flexible 1 個（10 Mbps）。Network Load Balancer 1 個 |
| VCN | 2 個まで（Free Tier のテナンシ） |
| 外向きの転送 | 10 TB/月 |
| Monitoring | 取り込み 5 億点/月・読み出し 10 億点/月 |
| Notifications | メール 1,000 通/月 |
| Email Delivery | 3,000 通/月 |
| Resource Manager | スタック 100 個・同時ジョブ 2 個 |

- Compute と DB は **ホームリージョン** にしか無料で作れない。
- A1 は、リージョンによっては空きが無く "Out of host capacity" で作れないことが多い。可用性ドメインが1つのリージョンでは、他のドメインに逃げることもできない。
- 確かめられなかったもの:
  - **OCIR**（コンテナ・レジストリ）: 「レジストリ自体は無料、保存は Object Storage の料金」とされるが、無料枠に含まれるかは公式に確かめられなかった。
  - **Artifact Registry**: 料金と無料枠を確かめていない。
- **OCI DevOps は Always Free ではない**。パイプラインそのものは無料で、ビルドの実行の分だけ課金される。

## 3. MySQL HeatWave の Always Free

| 項目 | 値 |
|---|---|
| 個数 | テナンシに 1 個（無料・有料のどちらのテナンシでも）。ホームリージョンだけ |
| シェイプ | `MySQL.Free`（1 ECPU・8 GB・1 Gbps）。構成は単体（`MySQL.Free.Standalone`） |
| ストレージ | 50 GB で固定 |
| HeatWave のクラスタ | `HeatWave.Free`（1 ノード・16 GB）を付けられる。分析用 |
| 版 | 作るときに最新。**保守のたびに最新へ上がる** |
| バックアップ | 自動だけ。**保持 1 日** で変えられない。手動バックアップと過去の時点への復元（PITR）はできない |
| 高可用性・リードレプリカ | 無し |
| ネットワーク | VCN のプライベート・サブネットに置く |
| 作成の失敗 | 空きが無いと `OutOfHostCapacity` になることがある |
| サポート | SLA なし。Oracle のサポートの対象外 |

公式文書に見つからなかったこと:

- 使わないと止まる・消されるといった条件（Autonomous Database の「7 日で停止」に当たるもの）
- `max_connections` などの設定の既定値
- 削除防止を有効にできるか

## 4. Autonomous Database の Always Free

| 項目 | 値 |
|---|---|
| 止まる条件 | **7 日使わないと自動で停止**（接続と CPU の使用で測る。SQL を実行する接続が成功すれば測り直し）。止まったまま累計 90 日で削除されうる |
| バックアップ | 手動バックアップ・過去の時点への復元はできない |
| ネットワーク | プライベート・エンドポイントは使えない（公開の口をアクセス制御の一覧で絞る） |
| 手元で動かす | 専用のコンテナ（推奨 4 CPU・8 GB）。一部の機能が無い |
| サポート | SLA なし |

## 5. アイドル回収

Always Free の Compute は、7 日間で次の **すべて** を満たすと回収されうる。

- CPU 使用率（95 パーセンタイル）が 20% 未満
- ネットワーク使用率が 20% 未満
- メモリ使用率が 20% 未満（A1 だけ）

PAYG のアカウントは対象外という情報が多いが（コミュニティの投稿・ブログ）、公式文書では確かめられなかった。

## 6. 出典

- [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)（Compute・ストレージ・DB・ネットワーク・アイドル回収）
- [MySQL HeatWave Service の機能（Always Free）](https://docs.oracle.com/iaas/mysql-database/doc/features-mysql-heatwave-service.html)
- [Always Free の MySQL の DB システムの作成](https://docs.oracle.com/iaas/mysql-database/doc/creating-always-free-db-system.html)
- [Always Free Autonomous Database の制限](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/autonomous-always-free.html)
