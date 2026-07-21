"""模拟人工复核回流 —— 方案里那个「灵魂箭头」

复核员看到标签实例，判定「成立 / 误报」，结果回流。
回流之后：
  · confidence 由冷启动先验切换为实测 precision
  · 阻断级规则若实测 precision <= 0.99，自动降级为人工复核
  · 误报不再是垃圾，而是校准数据

★ 复核判定用 ground truth 模拟，但**刻意注入 4% 标注噪声**（方案 §4.2 第4条）：
  真实场景里复核员也会判错。不模拟噪声，回流出来的 precision 就是虚高的假数。

用法：.venv/bin/python scripts/review_feedback.py
"""
from __future__ import annotations

import random

import psycopg
from psycopg.rows import dict_row

DSN = "postgresql://postgres:x@localhost:55432/reg"
SEED = 20260717
NOISE_RATE = 0.04          # 复核员的误判率
rnd = random.Random(SEED)


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        # ★ 增量复核：只处理尚未复核过的实例。绝不 TRUNCATE ——
        #   复核历史是资产，重跑一次就洗掉一次的话，实测 precision 永远算不出来。
        #   现实里复核员也是「来一批看一批」，不会把去年的结论推翻重来。
        cur.execute("""
            SELECT ti.instance_id, ev.rule_id,
                   COALESCE(il.entity_id IS NOT NULL AND NOT il.is_hard_negative, FALSE) AS truly_pos
            FROM tag_instance ti
            JOIN evidence ev ON ev.evidence_id = ti.evidence_id
            LEFT JOIN injection_log il
                   ON il.entity_id = ti.entity_id AND il.rule_id = ev.rule_id
            WHERE NOT EXISTS (SELECT 1 FROM review r WHERE r.instance_id = ti.instance_id)
            ORDER BY ti.instance_id
        """)
        rows = cur.fetchall()
        if not rows:
            print("没有待复核的标签实例（已全部复核过）")
            return

        noise_n = 0
        for r in rows:
            verdict_truth = "成立" if r["truly_pos"] else "误报"
            if rnd.random() < NOISE_RATE:               # 复核员判错
                verdict = "误报" if verdict_truth == "成立" else "成立"
                noise_n += 1
                note = "（本条为模拟的复核员误判，用于检验噪声鲁棒性）"
            else:
                verdict = verdict_truth
                note = None
            fp_reason = "合法情形未排除" if verdict == "误报" else None
            cur.execute(
                "INSERT INTO review (instance_id, verdict, reviewer, note, fp_reason)"
                " VALUES (%s,%s,'复核员A',%s,%s)",
                (r["instance_id"], verdict, note, fp_reason))

        conn.commit()
        print(f"回流 {len(rows)} 条复核结果（其中 {noise_n} 条为模拟误判，噪声率 {noise_n/len(rows):.1%}）\n")

        cur.execute("""
            SELECT p.rule_id, r.rule_type, r.disposal_level AS 配置处置,
                   r.confidence_prior AS 先验, p.reviewed, p.upheld, p.precision
            FROM rule_measured_precision p
            JOIN rule r ON r.rule_id = p.rule_id AND r.rule_version = p.rule_version
            ORDER BY p.rule_id
        """)
        print(f"{'规则':10s} {'类型':6s} {'配置处置':8s} {'先验':>5s} {'复核':>4s} "
              f"{'成立':>4s} {'实测P':>6s}  {'→ 生效处置'}")
        for x in cur.fetchall():
            conf = float(x["precision"]) if x["reviewed"] >= 20 else float(x["先验"])
            eff = ("人工复核" if x["配置处置"] == "硬阻断" and conf <= 0.99 else x["配置处置"])
            flag = " ★降级" if eff != x["配置处置"] else ""
            print(f"{x['rule_id']:10s} {x['rule_type']:6s} {x['配置处置']:8s} "
                  f"{float(x['先验']):5.2f} {x['reviewed']:4d} {x['upheld']:4d} "
                  f"{float(x['precision']):6.3f}  → {eff}{flag}")


if __name__ == "__main__":
    main()
