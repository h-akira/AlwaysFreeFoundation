# 003 Compute の VM の上で Docker を動かす

- 決めた日: 2026-11-09 以前（記録: 2026-11-10）

## 背景

コンテナを動かす場所の候補は、Compute の VM・OKE（Kubernetes）・Container Instances・Functions。無料枠の VM で確実に作れるのは E2.1.Micro（1/8 OCPU・1 GB）の 2 台で、A1 はリージョンによって空きが無く作れないことが多い（[references/oci-free-tier.md](../references/oci-free-tier.md)）。

## 決定

- OCI Compute の VM（E2.1.Micro）の上で Docker を使う。A1 を前提にしない。
- VM の種類は Terraform の変数で替えられるようにする。A1 を自動で取り直し続ける仕組みは作らない。

## 理由

- 無料か少額で、1 OCPU 未満を使えるのが Compute だけだった。
- VM をステートレスにすれば、コンテナ系のサービスの利点（VM の面倒を見なくてよい）の大半は得られる。

## 採らなかった案

| 案 | 理由 |
|---|---|
| OKE（Kubernetes） | 無料で済ませるには A1 をノードにするしかない。1 GB の VM では Kubernetes 自体が重い。仕組みも大幅に複雑になる |
| Container Instances | x86 の無料枠が無く、最小 1 OCPU で 1 OCPU 未満が使えない。A1 が取れないと常に有料になる。中身の変更はインスタンスの再起動で反映されるので、1 つに詰めると証明書が再起動のたびに消える。手元の compose と形がずれる |
| Functions | 常時動く Web アプリには向かない |
| 既製の PaaS（Dokku・Coolify など）・Nomad | 部品が増え、1 GB の VM には重い |
