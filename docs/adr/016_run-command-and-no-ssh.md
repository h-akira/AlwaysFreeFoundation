# 016 `afp deploy` は Run Command で実行させ、VM への ssh は保守のときだけ Bastion で通す

- 決めた日: 2026-11-10

## 背景

ビルドしたものを VM でデプロイするには、VM で `afp deploy` を実行させる仕組みが要る。DevOps からの自動のデプロイと、DevOps が使えないときの手元からのデプロイの両方に要る。最初は、手元からは ssh で呼ぶことにしていた。

## 決定

- DevOps の **インスタンス・グループへのデプロイ** を使う（AWS の CodeDeploy に当たる）。VM の中の Oracle Cloud Agent の Run Command のプラグインが、`afp deploy <プロジェクト> <版>` を実行する（[references/oci-devops.md](../references/oci-devops.md)）。
- DevOps が使えないときは、手元から同じ Run Command を直接呼ぶ。
- VM への ssh は保守のときだけにし、Bastion のポート転送で通す。22 番は外に開けない。

## 理由

- マネージドな仕組みがあり、同じ働きの OCI のサービスを使うという方針に合う。
- 自動と手元で、同じ仕組みを使える。
- デプロイに ssh を使わなければ、ssh は保守のときだけでまれになる。まれなら、Bastion のセッションを作る数十秒の待ちは気にならない。

## 採らなかった案

| 案 | 理由 |
|---|---|
| ssh で `afp deploy` を呼ぶ | 22 番を外に開けるか、デプロイのたびに Bastion のセッションを待つ必要がある。DevOps から ssh させるには鍵を DevOps に預けることになる |
| VM が Object Storage を定期的に見に行き、版が変わったらデプロイする | 外から入る口は要らないが、反映が遅れ、見に行く分の呼び出しと負荷がかかる |
| DevOps の汎用のシェルの段から、CLI で Run Command を呼ぶ | Ubuntu でも動くが、マネージドの利点（デプロイの成否の見え方など）の一部しか得られない |
| 22 番を管理者の IP にだけ開ける | ssh はまれなので、常に開いた入口を残すほどの利点が無い |
