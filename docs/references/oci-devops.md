# OCI DevOps: VM へのデプロイ

OCI DevOps は、ビルドとデプロイのパイプラインを動かすサービス。AWS の CodePipeline・CodeBuild・CodeDeploy を 1 つにしたものに当たる。ここでは、Compute の VM にデプロイする仕組みをまとめる。

- **確かめた日**: 2026-11-10（Oracle の公式文書。まだ動かしていない）

## 1. 仕組み

| OCI | AWS で近いもの | 内容 |
|---|---|---|
| インスタンス・グループへのデプロイ | CodeDeploy（EC2 へのデプロイ） | デプロイのパイプラインの段の 1 つ。対象の VM の集まり（インスタンス・グループの環境）に、決めたコマンドを順に実行させる |
| デプロイの構成のファイル | `appspec.yml` | YAML。`version: 1.0`・`component: deployment`。`files`（成果物をどこに置くか）と `steps`（実行するコマンド）を書く |
| Oracle Cloud Agent | SSM のエージェント・CodeDeploy のエージェント | OCI のイメージに入っているエージェント。プラグインで機能を足す |
| Run Command（Compute Instance Run Command のプラグイン） | SSM の Run Command | VM でコマンドを実行させる。DevOps のデプロイはこれを使う。CLI からも直接呼べる（`oci instance-agent command create`） |

## 2. 制約

- **対応する OS は Oracle Linux と CentOS だけ**（"DevOps only supports instance group deployments to Oracle Linux and CentOS."）。
- VM で Run Command のプラグインを有効にし、動いている必要がある。有効にしてから効くまで最大 10 分。
- デプロイの構成のファイルは、DevOps の成果物として直接書ける（inline）か、Artifact Registry に置く。それ以外の成果物は inline にできない。
- `steps` のコマンドは、既定では `ocarun` というユーザで動く。ステップごとに `runAs` で別のユーザ（`root` など）を指定できる。時間の上限も決められる（`timeoutInSeconds`）。
- 複数行のコマンドは、既定では途中で失敗しても止まらない。止めるには `set -e` を書く。
- `onFailure` に失敗したときの片付けを書けるが、段の結果（失敗）は変わらない。
- 権限: デプロイのパイプラインに、VM でコマンドを実行させる IAM の権限が要る。
- Run Command そのものの制限（同時に動くのは既定で 2 つ・受け取って残せるのは 5 つまで）と、命令を取りに来る間隔（既定で約 4 分）は [oci-run-command.md](oci-run-command.md)。インスタンス・グループへのデプロイでも同じ間隔で待つのかは未確認。

## 3. 未確認

- 成果物を Artifact Registry に置かず、デプロイの構成のファイルだけを inline で書いて動くか（コマンドが自分で成果物を取りに行く形）。
- インスタンス・グループへのデプロイに料金がかかるか。

## 4. 出典

- [Deploying to an Instance Group](https://docs.oracle.com/en-us/iaas/Content/devops/using/deploy_instancegroups.htm)（対応する OS・プラグイン・成果物）
- [Deployment Configuration File](https://docs.oracle.com/en-us/iaas/Content/devops/using/deployment_specs.htm)（構成のファイルの書き方・`ocarun`・`set -e`）
- [Running Commands on an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm)（Run Command）
