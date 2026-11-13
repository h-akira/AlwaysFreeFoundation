# OCI の Run Command

VM の中の Oracle Cloud Agent（OCI のイメージに入っているエージェント）の Run Command のプラグインに、コマンドを実行させる仕組み。AWS の SSM の Run Command に当たる。OCI DevOps のインスタンス・グループへのデプロイも、これを使う（[oci-devops.md](oci-devops.md)）。

- **確かめた日**: 2026-11-13（Oracle の公式文書と、CLI から実際に呼んだ結果）

## 1. 呼び方

```sh
oci instance-agent command create --compartment-id <コンパートメント> \
  --target '{"instanceId":"<VM の OCID>"}' --timeout-in-seconds 900 \
  --content '{"source":{"sourceType":"TEXT","text":"<スクリプト>"},"output":{"outputType":"TEXT"}}'
oci instance-agent command-execution get --command-id <命令の OCID> --instance-id <VM の OCID>
```

- 結果の `lifecycle-state` は、成功で `SUCCEEDED`、終了コードが 0 でなければ `FAILED`。`content.exit-code` に終了コード、`content.text` に出力が入る（`exit 3` で `FAILED`・exit-code 3 になった。実測）。

## 2. VM の側

- コマンドは `ocarun` というユーザで動く（実測）。root で動かすものは、`/etc/sudoers.d/` で `ocarun` に許す。許していないコマンドの `sudo` は断られた（実測）。
- VM（の dynamic group）に、命令を受ける権限が要る:
  `Allow dynamic-group <名前> to use instance-agent-command-execution-family in compartment <名前> where request.instance.id = target.instance.id`
- dynamic group を先に作ってから VM を作ると、VM はすぐに命令を取りに来る。VM を作ってから dynamic group に入れると、取りに来るまで最大 30 分かかる（公式文書）。

## 3. 届くまでの時間

- プラグインは、**決まった間隔で命令を取りに来る**。間隔は VM の中の `/etc/oracle-cloud-agent/plugins/runcommand/config.yml` の `pollCommandInterval` で、既定は `'4m'`（実測）。プラグインのログ（`/var/log/oracle-cloud-agent/plugins/runcommand/runcommand.log`）でも、取りに来て実行したあと、次を約 3.5〜4 分後に決めていた。公式文書には、この間隔の記述が無い。
- そのため、送ってから結果が返るまで、中身が数秒のコマンドでも 176〜268 秒かかった（E2.1.Micro・A1 とも。実測）。

## 4. 制限（公式文書）

| 項目 | 値 |
|---|---|
| 同時に動くスクリプト | 既定で 2 つ（`config.yml` の `commandExecutionMaxWorkers`） |
| 受け取ってまだ消えていないスクリプト | 5 つまで |
| スクリプトの大きさ（テキストで渡すとき） | 4 KB まで。大きいものは Object Storage に置く |
| 返る出力（テキストのとき） | 最後の 1 KB だけ。全部が要るなら Object Storage に出す |
| 時間切れ | 既定 1 時間・最長 24 時間。時計は、プラグインがコマンドを始めたときから動く |
| 記録が残る期間 | テキストのものは 7 日。Object Storage に置いたものは消すまで |
| 取り消し | できる限り試すだけ。終わったもの・期限切れのものは取り消せない |

## 5. 出典

- [Running Commands on an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm)（権限・dynamic group の 30 分・制限）
- [Oracle Cloud Agent](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/manage-plugins.htm)
