"""阈值校准 —— 用复核回流数据把「拍的数」变成「优化出来的数」

方法：在候选阈值上扫描，用复核结果算 P/R，
      选满足该处置级别 precision 门槛的最小阈值（precision 达标前提下 recall 最大）。

★ 同时报告【平台宽度】—— 这是本脚本最诚实的产出：
  若一大段阈值都给出同样的 P/R，说明数据根本没约束住阈值，
  所谓「校准」只是在平台上随便挑了一个点。合成数据尤其如此
  （实测 5~45 全部 precision=1.0，9 倍宽的平台）。
  平台宽 → 结论：阈值待真实数据标定，当前值不可信。

用法：.venv/bin/python scripts/calibrate.py
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

DSN = "postgresql://postgres:x@localhost:55432/reg"

# 各处置级别对 precision 的要求。阻断的门槛来自方案 §7.6 第三层。
TARGET_PRECISION = {"硬阻断": 0.99, "人工复核": 0.80, "仅打标": 0.50}

# 平台宽度超过此倍数，判定为「数据未约束住阈值」
PLATEAU_RATIO_UNCONSTRAINED = 2.0


def scan_zs02(cur, target: float):
    """扫描 R-ZS-02 的 new_threshold。

    注意：这里用 injection_log 只是因为原型期复核数据即由它模拟生成；
    真实场景该读 review 表。两者在本脚本中等价 —— review 就是带 4% 噪声的 ground truth。
    """
    cur.execute("""
        WITH c AS (
          SELECT e.address_id, COUNT(*) AS n,
                 COUNT(*) FILTER (WHERE e.estab_date > DATE '2026-07-17'-30) AS new30
          FROM enterprise e GROUP BY e.address_id
        ), b AS (SELECT PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY n) AS p99 FROM c)
        SELECT c.new30,
               COALESCE(il.rule_id IS NOT NULL AND NOT il.is_hard_negative, FALSE) AS truth
        FROM c CROSS JOIN b
        LEFT JOIN injection_log il ON il.entity_id = c.address_id AND il.rule_id = 'R-ZS-02'
        WHERE c.n > b.p99
    """)
    cand = cur.fetchall()
    if not cand:
        return None

    n_pos = sum(1 for r in cand if r["truth"])
    results = []
    for thr in range(0, int(max(r["new30"] for r in cand)) + 2):
        tp = sum(1 for r in cand if r["new30"] > thr and r["truth"])
        fp = sum(1 for r in cand if r["new30"] > thr and not r["truth"])
        if tp + fp == 0:
            continue
        p = tp / (tp + fp)
        rec = tp / n_pos if n_pos else 0
        results.append((thr, p, rec, tp, fp))

    ok = [r for r in results if r[1] >= target and r[2] > 0]
    if not ok:
        return None
    chosen = min(ok, key=lambda r: r[0])          # precision 达标前提下取最小阈值 → recall 最大
    return chosen, min(r[0] for r in ok), max(r[0] for r in ok), len(cand)


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM review")
        n_review = cur.fetchone()["c"]
        cur.execute("SELECT * FROM rule WHERE rule_id='R-ZS-02'")
        rule = cur.fetchone()
        target = TARGET_PRECISION[rule["disposal_level"]]

        print(f"复核样本 {n_review} 条 | R-ZS-02 处置={rule['disposal_level']} "
              f"→ 目标 precision >= {target}\n")

        out = scan_zs02(cur, target)
        if not out:
            print("★ 无法校准：没有任何阈值能达到目标 precision")
            return
        (thr, p, rec, tp, fp), lo, hi, n_cand = out

        width = (hi - lo) if lo > 0 else hi
        ratio = (hi / max(lo, 1)) if lo > 0 else float("inf")
        unconstrained = ratio >= PLATEAU_RATIO_UNCONSTRAINED

        print(f"候选池 {n_cand} 个地址（同址数已超 P99）")
        print(f"达标阈值区间：[{lo}, {hi}]，平台宽度 {width}（{ratio:.1f}×）")
        print(f"选定阈值：{thr}  → precision={p:.3f} recall={rec:.3f} (TP={tp} FP={fp})\n")

        if unconstrained:
            basis = "未校准初值"
            derivation = (
                f"★ 数据未约束住阈值：[{lo}, {hi}] 区间内全部达标（平台宽度 {ratio:.1f}×），"
                f"「校准」等于在平台上随便挑点。根因是合成数据在合法集群（近30日新增 1~2 家）"
                f"与虚假批量（50 家）之间留了一条不真实的宽沟；真实分布是连续的。"
                f"当前取 {thr} 仅为占位。→ 待真实数据标定（方案 §11 负面结果）。"
                f"退而求其次可用告警负荷倒推：全省日均可复核 N 条 → 阈值定在产出 N 条处。"
            )
        else:
            basis = "复核数据校准"
            derivation = (
                f"基于 {n_review} 条复核回流扫描候选阈值，在 precision >= {target}"
                f"（{rule['disposal_level']}级要求）前提下取最小值以最大化 recall。"
                f"达标区间 [{lo}, {hi}]，选定 {thr}。"
            )

        cur.execute(
            "INSERT INTO threshold_calibration (rule_id, rule_version, param_name, value,"
            " basis, derivation, target_precision, achieved_precision, achieved_recall,"
            " review_sample_size, plateau_low, plateau_high)"
            " VALUES (%s,%s,'new_threshold',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rule["rule_id"], rule["rule_version"], thr, basis, derivation,
             target, round(p, 3), round(rec, 3), n_review, lo, hi))
        conn.commit()

        print(f"依据类型：{basis}")
        print(f"依据说明：{derivation}\n")
        if unconstrained:
            print("→ 该阈值标记为【未校准初值】，引擎将强制把 R-ZS-02 降级为「仅打标」")


if __name__ == "__main__":
    main()
