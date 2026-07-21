"""指标引擎 —— 与规则引擎同构，只做解释器

★ 本文件里没有任何一个指标的名字、字段或口径。
  它读 METRIC_DICT，执行 logic，写 METRIC_INSTANCE。

执行契约：
  metric_dict.logic → 返回 (scope_value TEXT, value NUMERIC, sample_size INT, valid_from TIMESTAMPTZ)
  每一行即一条指标实例。

为什么指标要和标签分开物化（而不是让下游各自去算）：
  口径打架的病根是「重复计算」，不是「读了原始数据」。
  任何一个口径只允许被计算一次，结果物化为带版本、带时点的资产；下游只消费，不重算。
  风险口径 → TAG_INSTANCE ｜ 统计口径 → METRIC_INSTANCE ｜ 阈值基线 → STAT_BASELINE
  三者合起来才是唯一出口。

★ 趋势不需要另建表：METRIC_INSTANCE 按 valid_from 聚合就是趋势。

用法：.venv/bin/python scripts/metrics.py
"""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

DSN = "postgresql://postgres:x@localhost:55432/reg"
SCOPE_VALUE = "32"          # 江苏


def run_metric(cur, m: dict) -> int:
    cur.execute(m["logic"], {"scope_value": SCOPE_VALUE})
    rows = cur.fetchall()
    n = 0
    for r in rows:
        if r["value"] is None:
            continue
        cur.execute(
            "INSERT INTO metric_instance (metric_id, metric_version, scope_type,"
            " scope_value, value, sample_size, valid_from)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (m["metric_id"], m["metric_version"], m["scope_type"],
             str(r["scope_value"]), r["value"], r["sample_size"], r["valid_from"]))
        n += 1
    return n


def main():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE metric_instance RESTART IDENTITY")
        cur.execute("SELECT * FROM metric_dict ORDER BY grain DESC, metric_id")
        metrics = cur.fetchall()

        print(f"载入 {len(metrics)} 个指标（引擎不认识其中任何一个）\n")
        print(f"{'指标':11s} {'粒度':5s} {'来源':8s} {'名称':22s} {'实例数':>6s}")
        print("-" * 62)
        for m in metrics:
            n = run_metric(cur, m)
            print(f"{m['metric_id']:11s} {m['grain']:5s} {m['source_type']:8s} "
                  f"{m['metric_name']:22s} {n:6d}")
        conn.commit()

        cur.execute("SELECT COUNT(*) c FROM metric_instance")
        print(f"\n指标实例 {cur.fetchone()['c']} 条")


if __name__ == "__main__":
    main()
