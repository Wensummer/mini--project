"""规则引擎 —— 只做解释器

★ 本文件里没有任何一条规则的名字、字段或阈值。
  它读 RULE 表，执行 logic，写 EVIDENCE 与 TAG_INSTANCE。
  增删改规则 = 改数据库，不动这个文件，不发版。
  这是方案创新点①「规则即数据」的技术形态，也是对赛题「规则更新滞后」的正面回应。

执行契约：
  rule.baseline_sql（可选）→ 返回 (scope_value, value, sample_size)
      先算基线 → 落 STAT_BASELINE → 结果作为 %(baseline_value)s 注入 logic
  rule.logic → 返回 (entity_id, snapshot)
      每一行即一次命中 → 写一条 EVIDENCE + 一条 TAG_INSTANCE

confidence 的取值由规则类型决定，不是模型分数（方案 §7.4 决定3）。

用法：.venv/bin/python scripts/engine.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

DSN = "postgresql://postgres:x@localhost:55432/reg"
SCOPE_TYPE, SCOPE_VALUE = "province", "32"      # 本轮只做江苏

# 阻断级标签必须 precision > 0.99 才配设为阻断，否则降级为人工复核（方案 §7.6 第三层）。
# 这条写进代码，就把「你的误报怎么办」这个必问题提前答了：
# 不是靠承诺不误报，是靠系统自己不允许一条没被证明够准的规则去阻断企业开办。
BLOCK_MIN_PRECISION = 0.99

# 复核样本太少时，实测 precision 不可信，仍用先验。
MIN_REVIEWS_TO_TRUST = 20


def resolve_params(cur, rule: dict) -> tuple[dict, list[dict]]:
    """rule.params ← 属地覆盖 ← 阈值校准，三层叠加。

    返回 (params, 未校准的阈值清单)。
    未校准清单非空 ⇒ 该规则的阈值说不出依据 ⇒ 强制降级（见 resolve_disposal）。
    """
    params = dict(rule["params"])

    # 属地差异化参数：统一规则中台 + 属地参数（浙江 1000 万 vs 河南 100 万即此机制）
    cur.execute(
        "SELECT params FROM rule_param_override"
        " WHERE rule_id=%s AND rule_version=%s AND scope_type=%s AND scope_value=%s",
        (rule["rule_id"], rule["rule_version"], SCOPE_TYPE, SCOPE_VALUE))
    row = cur.fetchone()
    if row:
        params.update(row["params"])

    # 阈值校准：每个参数取最新一次校准结果
    cur.execute(
        "SELECT DISTINCT ON (param_name) param_name, value, basis, derivation"
        " FROM threshold_calibration WHERE rule_id=%s AND rule_version=%s"
        " ORDER BY param_name, calibrated_at DESC",
        (rule["rule_id"], rule["rule_version"]))
    uncalibrated = []
    for c in cur.fetchall():
        params[c["param_name"]] = float(c["value"])
        if c["basis"] == "未校准初值":
            uncalibrated.append(c)

    params["scope_value"] = SCOPE_VALUE
    return params, uncalibrated


def compute_baseline(cur, rule: dict, params: dict) -> tuple[int, float, int] | None:
    """算基线并落库。阈值必须来自数据分位数，且必须可追溯 —— 半年后要能回答『当时基线是多少』。"""
    if not rule["baseline_sql"]:
        return None
    cur.execute(rule["baseline_sql"], params)
    for row in cur.fetchall():
        if str(row["scope_value"]) != SCOPE_VALUE:
            continue
        cur.execute(
            "INSERT INTO stat_baseline (metric_name, scope_type, scope_value,"
            " quantile, value, sample_size) VALUES (%s,%s,%s,%s,%s,%s)"
            " RETURNING baseline_id",
            (rule["baseline_metric"], SCOPE_TYPE, SCOPE_VALUE,
             params.get("quantile"), row["value"], row["sample_size"]))
        bid = cur.fetchone()["baseline_id"]
        return bid, float(row["value"]), int(row["sample_size"])
    return None


def resolve_confidence(rule: dict) -> float:
    """confidence = 规则类型决定的先验，恒定，绝不被复核回流覆盖。

    ★ 这里踩过一次坑，留个记号：曾把 confidence 改为「有复核就用实测 precision」，
      结果 R-CZ-01（法定强制、等式判定、不可能判错）因复核员的 4% 误判被拉到 0.933
      并被自动降级 —— 规则没错，是复核员错了。方案 §7.4 早写了：
      「把它当模型输出，就把确定性规则污染成概率了。」

      confidence 与 precision 是两个东西，混了就出这种事：
        confidence —— 这条标签说的是不是事实。法定强制恒 1.0（算出来的，不是猜的）；
                       统计异常 < 1.0（超过 P99 是统计现象，不是事实断言）。
        precision  —— 命中后是否真的构成需要处置的问题。靠复核回流实测，见 resolve_disposal。

      confidence 可由 rule_type 推出，但它不是冗余，是反范式物化：
      下游拿到一条标签，不该为了知道它铁不铁而回去 join 规则库。
    """
    return float(rule["confidence_prior"])


def resolve_disposal(cur, rule: dict, uncalibrated: list[dict]) -> tuple[str, str | None]:
    """处置级别由**实测 precision** 与**阈值可信度**共同决定，不由 confidence 决定。

    两道闸，同一条逻辑的两个面：
      1. 阈值未校准 → 强制「仅打标」。不知道一个阈值准不准，
         就不配让人为它跑腿（复核要实地核查），更不配拿它阻断企业开办。
      2. 阻断级须实测 precision > 0.99，否则降级为人工复核（方案 §7.6 第三层）。

    这就把「你的误报怎么办」提前答了：不是承诺不误报，
    是系统结构上不允许一条没被证明够准的规则去阻断企业开办。
    """
    # 闸一：阈值说不出依据 → 只配打标
    if uncalibrated:
        names = "、".join(c["param_name"] for c in uncalibrated)
        return "仅打标", f"★ 强制降级：阈值 {names} 为未校准初值，说不出依据，不允许触发处置"

    level = rule["disposal_level"]
    if level != "硬阻断":
        return level, None

    cur.execute(
        "SELECT reviewed, precision FROM rule_measured_precision"
        " WHERE rule_id=%s AND rule_version=%s",
        (rule["rule_id"], rule["rule_version"]))
    row = cur.fetchone()
    if not row or row["reviewed"] < MIN_REVIEWS_TO_TRUST:
        n = row["reviewed"] if row else 0
        return "人工复核", (f"★ 降级：复核样本仅 {n} 条（<{MIN_REVIEWS_TO_TRUST}），"
                            f"precision 未经证明，不允许阻断")
    p = float(row["precision"])
    if p <= BLOCK_MIN_PRECISION:
        return "人工复核", (f"★ 降级：实测 precision {p:.3f} 未达阻断门槛 "
                            f"{BLOCK_MIN_PRECISION}（{row['reviewed']} 条复核）")
    return "硬阻断", f"实测 precision {p:.3f} > {BLOCK_MIN_PRECISION}，允许阻断"


def run_rule(cur, rule: dict, now: datetime) -> tuple[int, str]:
    params, uncalibrated = resolve_params(cur, rule)

    baseline_id = None
    bl = compute_baseline(cur, rule, params)
    if bl:
        baseline_id, params["baseline_value"], params["baseline_sample_size"] = bl
    elif rule["baseline_sql"]:
        return 0, "基线算不出（该 scope 无数据）"

    conf = resolve_confidence(rule)
    disposal, disposal_note = resolve_disposal(cur, rule, uncalibrated)

    cur.execute(rule["logic"], params)
    hits = cur.fetchall()

    # ---------- SCD Type 2：失效不删 ----------
    # ★ 这里踩过一次坑，留个记号：曾在每次运行时 TRUNCATE tag_instance，
    #   而 review 外键引用 tag_instance —— 于是每跑一次规则，复核历史就被连坐清空一次，
    #   实测 precision 永远算不出来，回流闭环半瘫。复核历史是资产，不能被规则重跑毁掉。
    #
    # 现在：标签实例按 (tag_id, entity_id) 做 SCD2
    #   仍命中 → 保持 valid_to IS NULL，valid_from 不动（同一个事实的延续，不是新事实）
    #   不再命中 → valid_to = now（失效，但记录永存）
    #   新命中 → 插入新实例 + 新证据
    # 这样才真的能回答「去年这家企业当时是什么状态」，
    # 且宏观趋势按 valid_from 聚合才是真的（否则每次重跑趋势都被重置）。
    tag_id, tv = rule["tag_id"], "v1"
    cur.execute(
        "SELECT instance_id, entity_id FROM tag_instance"
        " WHERE tag_id=%s AND tag_version=%s AND valid_to IS NULL", (tag_id, tv))
    open_now = {r["entity_id"]: r["instance_id"] for r in cur.fetchall()}
    hit_ids = {h["entity_id"] for h in hits}

    gone = [open_now[e] for e in set(open_now) - hit_ids]
    if gone:
        cur.execute("UPDATE tag_instance SET valid_to=%s WHERE instance_id = ANY(%s)",
                    (now, gone))

    fresh = hit_ids - set(open_now)
    for h in hits:
        if h["entity_id"] not in fresh:
            continue
        # 证据不可变：记的是命中当时的快照。持续命中不重开实例，故证据保持首次的。
        cur.execute(
            "INSERT INTO evidence (rule_id, rule_version, field_snapshot, law_anchor,"
            " baseline_id) VALUES (%s,%s,%s,%s,%s) RETURNING evidence_id",
            (rule["rule_id"], rule["rule_version"], Json(h["snapshot"]),
             rule["law_anchor"], baseline_id))
        eid = cur.fetchone()["evidence_id"]
        cur.execute(
            "INSERT INTO tag_instance (tag_id, tag_version, entity_type, entity_id,"
            " value, valid_from, confidence, evidence_id)"
            " VALUES (%s,%s,%s,%s,'true',%s,%s,%s)",
            (tag_id, tv, rule["target_entity"], h["entity_id"], now, conf, eid))

    kept = len(hit_ids & set(open_now))
    note = f"conf={conf:.3f}（{rule['rule_type']}先验，恒定）  处置={disposal}"
    note += f"\n           └─ SCD2: 新增 {len(fresh)} / 延续 {kept} / 失效 {len(gone)}"
    if disposal_note:
        note += f"\n           └─ {disposal_note}"
    return len(hits), note


def main():
    now = datetime.now(timezone.utc)
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        # ★ 什么都不 TRUNCATE。
        #   tag_instance —— SCD2，失效不删（见 run_rule）
        #   evidence     —— 不可变，被 tag_instance 引用
        #   stat_baseline—— 历史基线，被 evidence.baseline_id 引用。
        #                   删了就答不出「半年前这条为什么没报」（因为当时基线不同）
        #   review       —— 复核历史是资产，绝不能被规则重跑连坐
        cur.execute("SELECT * FROM rule ORDER BY rule_id")
        rules = cur.fetchall()

        print(f"载入 {len(rules)} 条规则（引擎不认识其中任何一条）\n")
        for r in rules:
            n, note = run_rule(cur, r, now)
            law = r["law_anchor"] or f"（无法源·{r['rule_type']}）"
            flag = " ★待核" if r["law_anchor"] and "待核" in r["law_anchor"] else ""
            print(f"  {r['rule_id']} {r['rule_type']:5s} 挂载={r['target_entity']:3s} "
                  f"命中 {n:3d}  法源={law}{flag}")
            print(f"           └─ {note}")
        conn.commit()

        cur.execute("SELECT COUNT(*) FILTER (WHERE valid_to IS NULL) AS cur,"
                    " COUNT(*) FILTER (WHERE valid_to IS NOT NULL) AS expired,"
                    " COUNT(*) AS total FROM tag_instance")
        t = cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM evidence")
        ev = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM review")
        rv = cur.fetchone()["c"]
        print(f"\n标签实例 {t['total']} 条（当前有效 {t['cur']} / 已失效 {t['expired']}）"
              f" | 证据 {ev} 条 | 复核历史 {rv} 条（未被清空）")


if __name__ == "__main__":
    main()
