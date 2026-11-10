# 014 VM の OS は Oracle Linux 9

- 決めた日: 2026-11-10

## 背景

VM（E2.1.Micro・1 GB）は Docker を動かすだけで、ステートレスで作り直す前提。候補は Oracle Linux 9 と Ubuntu 24.04。デプロイは DevOps のインスタンス・グループへのデプロイで行う（ADR 016）。

## 決定

- Oracle Linux 9 にする。`afp` は OS の標準の python3.9 で書く。
- dnf のメモリ不足に備え、VM にスワップを置く。

## 理由

- DevOps のインスタンス・グループへのデプロイが、Oracle Linux と CentOS にしか対応していない（[references/oci-devops.md](../references/oci-devops.md)）。
- python3.9 は OS に最初から入っていて、何も足さずに済む（ADR 008）。

## 採らなかった案

| 案 | 理由 |
|---|---|
| Ubuntu 24.04 | apt が軽く、Docker が公式に対応し、python3 も新しいので 1 GB の VM には向く。ただしインスタンス・グループへのデプロイが使えない |
| Oracle Linux 9 に `python3.12` を足す | 新しい構文は使えるが、入れる手順が 1 つ増える |

## 引き換え

- Oracle Linux の dnf は、1 GB でスワップが無いとメモリが尽きて落ちることがある（[Fedora の議論](https://discussion.fedoraproject.org/t/dnf-operations-use-large-amount-of-ram-and-may-fail-in-low-memory-environments/76389)）。
- OCI の上では、Oracle Linux の Premier Support と Ksplice が無料で付く。VM は作り直す前提なので、判断にはあまり効かなかった。
