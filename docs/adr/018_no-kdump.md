# 018 VM では kdump を使わない

- 決めた日: 2026-11-13

## 背景

Oracle Linux 9 は、カーネルが落ちたときの記録（kdump）のために、起動の引数 `crashkernel=1G-64G:448M,64G-:512M` でメモリを取っておく。OS から見えるメモリが 1 GB 以上なら、448 MB を取る（[Kdump System Memory Requirements](https://docs.oracle.com/en/operating-systems/oracle-linux/9/boot/kdump_system_requirements.html)、[Linux カーネルの文書](https://docs.kernel.org/admin-guide/kdump/kdump.html)。2026-11-13 確認）。

同じイメージから作った 2 台の E2.1.Micro で、OS から見えるメモリが違った（2026-11-13 実測）。1 台は 945 MB で予約されず、もう 1 台は 1 GB に見えて 448 MB 取られ、使えるのは 498 MB だった。どちらになるかは、作るまで分からない。A1 でも、2〜8 GB の arm64 なら 256 MB を取る。

## 決定

- VM の起動のスクリプトで、kdump の service を止め、起動の引数から `crashkernel` を消す。カーネルを更新しても戻らないようにする（`auto_reset_crashkernel no`）。
- 予約が実際にあるときだけ、1 回再起動する。

## 理由

- 1 GB の VM で 448 MB を失うと、Docker・Caddy・アプリが載らない。
- VM はステートレスで、壊れたら作り直す。カーネルが落ちた原因を記録から調べる場面は、まず無い。

## 採らなかった案

| 案 | 理由 |
|---|---|
| 既定のまま | VM によって、使えるメモリが半分になる |
| しきい値を上げる（`crashkernel=2G-64G:448M,...`） | 大きい VM では kdump が残る。ただし 1 GB の VM では、予約が無いので kdump が起動のたびに失敗し続け、中途半端になる |

## 引き換え

- OCI のコンソールや API から診断の割り込みを送って、クラッシュの記録を取ることができなくなる（[Collecting Crash Dumps Using Kdump Utility](https://docs.oracle.com/en-us/iaas/oracle-linux/oci/diagnostics-kdump.htm)）。
- 予約があった VM では、初回の起動で 1 回再起動する。メモリが約 500 MB の状態では、停止のときに initramfs を `/run` に展開するところで `/run` があふれ、停止に約 3 分かかった（実測）。
