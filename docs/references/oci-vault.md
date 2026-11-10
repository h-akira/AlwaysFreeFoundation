# OCI Vault（KMS とシークレット）

OCI Vault は、暗号の鍵とシークレット（パスワードなどの秘密の値）を預かるサービス。AWS の KMS と Secrets Manager を 1 つにしたものに当たる。Vault（鍵の入れ物）の中に鍵を作り、シークレットはその鍵で暗号化して Vault に置く。

- **確かめた日**: 2026-11-10（Oracle の公式文書と、実際に作って消した結果）

## 1. 消すと「削除待ち」になる

Vault・鍵・シークレットは、消してもすぐには消えない。**削除待ち**（`PENDING_DELETION`）になって決めた日まで残り、その間は取り消せる。AWS の KMS の鍵の削除待ちと同じ考え方。

| もの | 削除待ちの期間 | 既定 |
|---|---|---|
| Vault（中の鍵もいっしょに削除待ちになる） | 7〜30 日 | 30 日 |
| 鍵 | 7〜30 日 | 30 日 |
| シークレット | 1〜30 日 | 30 日 |

- 出典: [Deleting a Vault](https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Tasks/managingvaults_topic-To_delete_a_vault.htm)・[Deleting a Key](https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Tasks/managingkeys_topic-To_delete_a_key.htm)・[Deleting a Secret](https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Tasks/managingsecrets_topic-To_delete_a_secret.htm)・CLI の [vault schedule-deletion](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/kms/management/vault/schedule-deletion.html)（`--time-of-deletion` は 7〜30 日後。省けば 30 日後）
- シークレットの文書には、取り消しの説明に「7 日の待ち」とも書かれていて、1〜30 日の記述と食い違う。

## 2. 削除待ちの Vault はコンパートメントの削除を止める

- Terraform の destroy で、シークレット・鍵・Vault は削除待ちになった時点で「消えた」として次に進んだ。最後のコンパートメントの削除だけが失敗した（`expected DELETED, but ACTIVE`）（実測 2026-11-09）。
- 削除待ちの Vault はコンパートメントの中に残る。中身の残るコンパートメントは消せない。
- 削除待ちの Vault も、Vault の一覧（`oci kms management vault list`）に `PENDING_DELETION` として出てくる（実測）。名前で探すときは、状態でも絞る。

## 3. 未確認

- 削除待ちのシークレットがある間、同じ名前のシークレットを同じ Vault に作れるか。
- 削除待ちの Vault が、Vault の個数の上限に数えられるか。上限の値も。
