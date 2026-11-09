# OCI Resource Manager

Terraform を OCI の側で実行するサービス。Terraform の構成（`.tf` のファイル一式）を **スタック** として預け、plan・apply・destroy を **ジョブ** として実行する。state も Resource Manager が預かるので、手元に state を置かなくてよい。

- **確かめた日**: 2026-11-09（Oracle の公式文書と、実際にスタックを作って動かした結果）

## 1. 要点

| 項目 | 内容 |
|---|---|
| スタック | Terraform の構成と変数の値の組。構成は zip のアップロード・Git のリポジトリ・Object Storage などから取る |
| ジョブ | plan・apply・destroy などの1回の実行。ログと結果が残る |
| state | Resource Manager が預かる。CLI で取り出せる（`oci resource-manager stack get-stack-tf-state`） |
| 無料枠 | スタック 100 個・同時ジョブ 2 個（[oci-free-tier.md](oci-free-tier.md) §2） |

## 2. 変数

- スタックの変数は **文字列だけ** を持つ（CLI の `--variables` は、文字列から文字列への対応）。
- Terraform の側で `list(string)` などの型を宣言した変数に、**JSON の文字列**（例: `["192.0.2.10/32"]`）を渡すと、その型として受け取られた（実測）。
- `tenancy_ocid`・`region`・`compartment_ocid`・`current_user_ocid` が自動で入るのは、**コンソールでスタックを作る・直す画面だけ**（公式文書）。CLI で作ったスタックには入らず、宣言しただけで値を渡さないと plan が「No value for required variable」で失敗した（実測）。CLI から使うときは、これらも変数として渡す。

## 3. plan と apply

- apply のジョブには、直前の plan のジョブを指定できる（`--execution-plan-strategy FROM_PLAN_JOB_ID --execution-plan-job-id <plan のジョブ>`）。確かめた plan のとおりに適用される。
- ジョブのログは、ジョブが終わってから `oci resource-manager job get-job-logs-content` でまとめて取れる。
- Terraform の版はスタックごとに指定する。`1.5.x` を指定し、プロバイダ `oracle/oci` v9.12.1・`hashicorp/random` v3.9.1 で動いた（実測）。

## 4. 出典

- [Overview of Resource Manager](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/resourcemanager.htm)（スタック・ジョブ・state）
- [Terraform Configurations for Resource Manager](https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Concepts/terraformconfigresourcemanager_topic-schema.htm)（自動で入る変数）
