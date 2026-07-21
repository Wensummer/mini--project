"""图计算 —— NetworkX，只做 SQL 真做不了的事

★ 为什么是 NetworkX 而不是 Neo4j：
  1. 方案 §6.3 的八条图约束里，**只有 C5（股权环）用到变长路径** `-[:投资*1..6]->`。
     其余七条 Cypher 单跳即 JOIN：C1 是 GROUP BY、C8 甚至一条边都没有（纯自连接）。
     「Cypher 表达力够写图约束」反过来说也成立 —— SQL 也够。它不构成上图数据库的理由。
  2. 图在本项目里是**派生视图，不是第二个真相源**：
     PostgreSQL 的 investment / position_hold 本来就是边表。
  3. 1000 家（乃至 10 万家）NetworkX 内存里几十毫秒跑完。
     Neo4j 的价值在千万级节点与交互式探索，两者本项目都不沾；
     且 Neo4j 社区版的图算法库（GDS）是阉割的，多数算法只在企业版。
  4. NetworkX 无需部署 —— 没有服务、没有端口、没有守护进程、没有同步逻辑，
     Demo 现场少一个能挂的组件。

架构（标签库仍是唯一出口，图不破坏这条）：
    PostgreSQL（权威源）→ NetworkX（内存图：穿透/社区）→ 写回 beneficial_owner + 标签库

本脚本做两件 SQL 真做不了的事：
  1. 受益所有人穿透 —— 沿股权链**累乘持股比例**，找 >=25% 的自然人。
     递归 CTE 理论上能做，但要处理多路径汇合、环剪枝、比例累乘，会写成个怪物。
  2. 社区发现（Louvain）—— SQL 根本做不了。对应中观层「关联企业集群」。

用法：.venv/bin/python scripts/graph.py
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import networkx as nx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

DSN = "postgresql://postgres:x@localhost:55432/reg"

# 《受益所有人信息管理办法》：持股/表决权 25% 以上的自然人为受益所有人。
# ★ 这个 25% 不是拍的 —— 它来自法条，是本项目里少数几个有硬依据的数字之一。
BO_THRESHOLD = Decimal("0.25")
MAX_DEPTH = 6              # 穿透深度上限，与 R-BG-05 的 max_depth 保持一致


def build_graph(cur) -> nx.DiGraph:
    """从 PostgreSQL 构图。investment 本来就是边表 —— 图是派生的，不是另存一份。"""
    G = nx.DiGraph()

    cur.execute("SELECT ent_id, ent_name, reg_capital FROM enterprise")
    for r in cur.fetchall():
        G.add_node(r["ent_id"], kind="enterprise",
                   name=r["ent_name"], capital=r["reg_capital"])

    cur.execute("SELECT person_id FROM person")
    for r in cur.fetchall():
        G.add_node(r["person_id"], kind="person")

    # 持股比例是**导出**的，不是存的：认缴额 ÷ 被投资企业注册资本。
    # （矩阵B：出资比例字段仅 4/9 省采集 —— 存的靠不住，算的才靠得住）
    cur.execute("""
        SELECT i.investee_ent_id, i.investor_type,
               COALESCE(i.investor_person_id, i.investor_ent_id) AS investor_id,
               i.subscribed_amount, e.reg_capital
        FROM investment i JOIN enterprise e ON e.ent_id = i.investee_ent_id
    """)
    for r in cur.fetchall():
        ratio = Decimal(r["subscribed_amount"]) / Decimal(r["reg_capital"])
        G.add_edge(r["investor_id"], r["investee_ent_id"], ratio=ratio)
    return G


def penetrate(G: nx.DiGraph, target: str) -> dict[str, tuple[Decimal, list]]:
    """穿透：沿股权链向上累乘，汇总到自然人。

    ★ 这是 SQL 真做不了的那件事：
      - 多路径汇合要相加（同一人经两条链持股 → 比例累加）
      - 环要剪枝（我们注入了股权环，不剪会无限递归）
      - 每一跳要乘
    """
    result: dict[str, Decimal] = defaultdict(Decimal)
    paths: dict[str, list] = {}

    def dfs(node: str, acc: Decimal, depth: int, visited: frozenset, trail: list):
        if depth > MAX_DEPTH:
            return
        for pred in G.predecessors(node):
            if pred in visited:          # 环，剪掉
                continue
            r = acc * G[pred][node]["ratio"]
            t = [pred] + trail
            if G.nodes[pred]["kind"] == "person":
                result[pred] += r
                # 保留贡献最大的那条路径作为证据
                if pred not in paths or r > result[pred] - r:
                    paths[pred] = t
            else:
                dfs(pred, r, depth + 1, visited | {pred}, t)

    dfs(target, Decimal(1), 0, frozenset({target}), [target])
    return {p: (r, paths.get(p, [])) for p, r in result.items() if r >= BO_THRESHOLD}


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        G = build_graph(cur)
        ents = [n for n, d in G.nodes(data=True) if d["kind"] == "enterprise"]
        print(f"图：{G.number_of_nodes()} 节点 / {G.number_of_edges()} 边 "
              f"（企业 {len(ents)}，自然人 {G.number_of_nodes()-len(ents)}）\n")

        # ---------- 1. 受益所有人穿透 ----------
        cur.execute("TRUNCATE beneficial_owner")
        rows, deep = [], 0
        for e in ents:
            for pid, (ratio, path) in penetrate(G, e).items():
                depth = len(path) - 1
                deep = max(deep, depth)
                rows.append((e, pid, min(ratio, Decimal(1)), "computed",
                             Json({"path": path, "ratio": str(ratio)}), depth))
        cur.executemany(
            "INSERT INTO beneficial_owner (ent_id, person_id, ratio, source, path, max_depth)"
            " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
        conn.commit()

        cur.execute("SELECT COUNT(*) c FROM beneficial_owner WHERE source='computed'")
        n_comp = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM beneficial_owner WHERE source='declared'")
        n_decl = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM beneficial_owner WHERE max_depth > 1")
        n_indirect = cur.fetchone()["c"]

        print("【1】受益所有人穿透（持股 ≥25%，阈值来自《受益所有人信息管理办法》—— 有法条依据，不是拍的）")
        print(f"     穿透算出 {n_comp} 条，其中 {n_indirect} 条是**间接持股**（穿透深度 >1，SQL 做不出来）")
        print(f"     最大穿透深度 {deep} 层")
        print(f"     企业申报的（declared）：{n_decl} 条")
        if n_decl == 0:
            print("     ★ declared = 0 —— 江苏登记系统不采集「受益所有人」字段（矩阵B 第37行，仅河南有）")
            print("       → 法定备案事项在此省无处可填。「未备案受益所有人」这条规则会 100% 命中，")
            print("         但那不是全省企业都在违法，是登记系统没有这个入口。")
            print("       → **这是监管堵点，不是风险。**（★ 矩阵发现②仍待核，用前须核实）")

        # ---------- 2. 社区发现 ----------
        UG = nx.Graph()
        UG.add_nodes_from(ents)
        for u, v in G.edges():
            if G.nodes[u]["kind"] == "enterprise":
                UG.add_edge(u, v)
        comms = nx.community.louvain_communities(UG, seed=20260717)
        big = sorted([c for c in comms if len(c) >= 3], key=len, reverse=True)

        # ★ 写回派生表 —— 图是派生视图不是第二真相源（§3.8）：内存算完写回，供中观集群画像聚合。
        cur.execute("TRUNCATE graph_community")
        crows = [(ent, cid, len(c)) for cid, c in enumerate(big) for ent in c]
        cur.executemany(
            "INSERT INTO graph_community (ent_id, community_id, community_size)"
            " VALUES (%s,%s,%s)", crows)
        conn.commit()

        print(f"\n【2】社区发现（Louvain）—— ★ SQL 根本做不了")
        print(f"     企业投资图：{UG.number_of_nodes()} 节点 / {UG.number_of_edges()} 边")
        print(f"     社区 {len(comms)} 个，其中 ≥3 家的关联集群 {len(big)} 个（{len(crows)} 家企业已写回 graph_community）")
        for c in big[:5]:
            print(f"       集群 {len(c)} 家: {sorted(c)[0]} …")

        # ---------- 3. 强连通分量（环）—— 与 R-BG-05 交叉验证 ----------
        DG = G.subgraph(ents)
        sccs = [c for c in nx.strongly_connected_components(DG) if len(c) > 1]
        cur.execute("SELECT COUNT(DISTINCT entity_id) c FROM tag_instance WHERE tag_id='T-BG-05'")
        n_sql = cur.fetchone()["c"]
        n_graph = sum(len(c) for c in sccs)
        print(f"\n【3】强连通分量 vs 递归 CTE 交叉验证")
        print(f"     NetworkX 找到 {len(sccs)} 个环，涉及 {n_graph} 家企业")
        print(f"     规则引擎（递归 CTE）命中 {n_sql} 家")
        print(f"     {'✔ 两条路径结果一致' if n_graph == n_sql else '✘ 不一致，需排查'}")


if __name__ == "__main__":
    main()
