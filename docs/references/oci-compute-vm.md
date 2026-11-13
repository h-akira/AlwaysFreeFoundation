# OCI の Compute の VM（Oracle Linux 9）

OCI の公式のイメージ（Oracle Linux 9）で、小さな VM（E2.1.Micro と A1）を作ったときに分かったこと。

- **確かめた日**: 2026-11-13（実際に VM を作って測った結果と、Oracle の公式文書）
- 「実測」と書いたものは、イメージ `Oracle-Linux-9.8-2026.10.30-0`（amd64）と `Oracle-Linux-9.8-aarch64-2026.10.30-0`（arm64）で測った。イメージや時期が違えば変わりうる。

## 1. 形（shape）と見えるメモリ

| 形 | CPU の種類 | 実測 |
|---|---|---|
| `VM.Standard.E2.1.Micro`（1/8 OCPU・1 GB） | amd64（AMD EPYC） | OS から見えるメモリは、VM によって 945 MB のことも 1 GB のこともあった（§2 の kdump の予約を左右する） |
| `VM.Standard.A1.Flex`（1 OCPU・6 GB で作った） | arm64（Ampere） | 5,898 MB。`nproc` は 1 |

- 公式のイメージは、最初からスワップを持っている（実測で 497〜944 MB。見えるメモリと同じくらい）。
- 何もしていない状態（Docker は動いていて、コンテナは無い）の空き（`available`）は、E2.1.Micro で約 440 MB、A1（6 GB）で約 5 GB だった（実測）。大きいのは dockerd（約 61 MB）・firewalld（約 43 MB）・containerd（約 37 MB）・Oracle Cloud Agent とプラグイン（合わせて約 79 MB）。

## 2. kdump のメモリの予約

- Oracle Linux 9 の起動の引数には、既定で `crashkernel=1G-64G:448M,64G-:512M` がある。カーネルが落ちたときの記録（kdump）のために、OS から見えるメモリが 1〜64 GB なら 448 MB を取っておく（x86_64 の場合。arm64 は 2〜8 GB で 256 MB）。範囲の下限より少なければ、何も取らない。
- E2.1.Micro では、見えるメモリが 1 GB の VM で 448 MB が取られ、使えるのは 498 MB になった。945 MB の VM では取られなかった（実測）。
- `/etc/kdump.conf` に `auto_reset_crashkernel yes` があり、カーネルを更新すると、この予約は既定の値に戻される（実測で設定を確認。挙動は公式の文書で確かめていない）。
- 予約をやめるには、起動の引数から `crashkernel` を消して（`grubby --update-kernel=ALL --remove-args=crashkernel`）、再起動する。予約されているかは `/sys/kernel/kexec_crash_size`（0 なら無し）で分かる（実測）。
- 使えるメモリが約 500 MB の状態で再起動すると、停止のときに initramfs を `/run`（メモリの上の tmpfs）に展開するところで `/run` があふれ、停止に約 3 分かかった。止まりはしなかった（実測）。
- kdump を止めると、コンソールや API から診断の割り込みを送ってクラッシュの記録を取ることはできなくなる。

## 3. dnf

- 公式のイメージは、最初から多くのリポジトリが有効になっている（`ol9_baseos_latest`・`ol9_appstream`・`ol9_addons`・`ol9_UEKR8`・`ol9_ksplice`・`ol9_oci_included`）。dnf は、`install` のたびに有効なリポジトリすべてのメタデータ（どのパッケージがあり、何に依存するかの一覧）を落とし、依存の解決用に変換する（キャッシュが古ければ）。
- メタデータの大きさ（実測・amd64）: `ol9_oci_included` 189 MB・`ol9_baseos_latest` 169 MB・`ol9_appstream` 115 MB・`ol9_UEKR8` 71 MB・`ol9_ksplice` 37 MB。
- E2.1.Micro（スワップあり）で Docker を入れた時間（実測）:
  - 全リポジトリを有効のまま: 約 21 分。うちメタデータの変換が約 13 分（`ol9_oci_included` だけで約 9 分）、`container-selinux` の後処理が約 4 分。スワップを最大 1.5 GB 使った。
  - `--disablerepo='*' --enablerepo=<要るものだけ>` と `--setopt=tsflags=nodocs` にすると: 約 10 分（メタデータの変換は約 3 分）。
- A1（1 OCPU・6 GB）では、Docker を入れるのに約 4 分、続けて OCI CLI に約 2 分だった（実測）。
- `dnf-makecache.timer` が、メタデータの更新を裏で定期的に走らせる。
- 入れたパッケージのリポジトリ（実測）:
  - Docker（`docker-ce` など）: Docker の RHEL 向けのリポジトリ（`docker-ce-stable`）。依存は `ol9_baseos_latest`・`ol9_appstream` で足りた。amd64・arm64 の両方にある。
  - OCI CLI（`python39-oci-cli`）: `ol9_oci_included`。依存は `ol9_baseos_latest`・`ol9_appstream` で足りた。

## 4. ネットワーク

- **firewalld** は既定で動いていて、許しているのは `ssh` と `dhcpv6-client` だけ。それでも、Docker のコンテナが公開したポート（`-p 80:8080` など）には外から届いた（実測）。
- **VCN の DNS** は、メタデータと同じ `169.254.169.254` の 53 番にある（[DNS in Your Virtual Cloud Network](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/dns.htm)）。Docker の `DOCKER-USER` で「`169.254.169.254` の udp/tcp 53 は通す → `169.254.0.0/16` は落とす」とすると、コンテナから名前は引けて、メタデータには届かなかった（実測）。
- メタデータの v2 の口（`http://169.254.169.254/opc/v2/`）は、ヘッダ `Authorization: Bearer Oracle` が要る。古い v1 の口は、インスタンスの設定（`are_legacy_imds_endpoints_disabled`）で止められる。
- 公開 IP を付けない VM で作り、あとから予約済みの公開 IP を付けると、付くまでの間（作ってから 1 分ほど）は外へ出られない（実測。インターネット・ゲートウェイの経路だけで、NAT ゲートウェイは無い構成）。

## 5. Oracle Cloud Agent のプラグイン

公式のイメージの VM で、何も指定せずに動いていたプラグイン（実測。`oci instance-agent plugin list`）:

| プラグイン | 状態 |
|---|---|
| Compute Instance Monitoring | 動いている |
| Cloud Guard Workload Protection | 動いている（Cloud Guard の Instance Security のエージェントを入れて更新するためのもの。料金は [oci-free-tier.md](oci-free-tier.md) §2） |
| Compute Instance Run Command | 指定して有効にした（[oci-run-command.md](oci-run-command.md)） |
| Vulnerability Scanning・OS Management Hub Agent・Management Agent・Bastion・Block Volume Management など | 止まっている |

- プラグインの有効・無効を変えてから効くまで、最大 10 分（公式文書）。

## 6. A1 の空き

- 「容量の報告」（Compute Capacity Report。`oci compute compute-capacity-report create`）で、指定した形と大きさの VM をいまその可用性ドメインに作れるかを、何も作らずに問い合わせられる。結果は `AVAILABLE` など。その時点の様子で、作れることを約束はしない。
- 2026-11-13 には、A1 の 1・2・4 OCPU のどれも `AVAILABLE` で、1 OCPU・6 GB の VM が 35 秒で `RUNNING` になった（実測）。A1 は、時期によっては "Out of host capacity" で作れない（[oci-free-tier.md](oci-free-tier.md) §2）。
- A1 では、アイドル回収の条件にメモリの使用率も加わる（[oci-free-tier.md](oci-free-tier.md) §5）。

## 7. 出典

- [Kdump System Memory Requirements（Oracle Linux 9）](https://docs.oracle.com/en/operating-systems/oracle-linux/9/boot/kdump_system_requirements.html)（予約の大きさ）
- [Kdump Memory Reservation（Oracle Linux 9）](https://docs.oracle.com/en/operating-systems/oracle-linux/9/boot/kdump-memory_reservation.html)
- [Collecting Crash Dumps Using Kdump Utility（OCI）](https://docs.oracle.com/en-us/iaas/oracle-linux/oci/diagnostics-kdump.htm)（診断の割り込みに kdump が要る）
- [Documentation for Kdump（Linux カーネル）](https://docs.kernel.org/admin-guide/kdump/kdump.html)（`crashkernel` の範囲の書き方）
- [Oracle Cloud Agent](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/manage-plugins.htm)（プラグイン）
- [DNS in Your Virtual Cloud Network](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/dns.htm)
