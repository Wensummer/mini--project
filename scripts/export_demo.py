"""导出四屏 Demo 数据 → 一个 JSON

给前端喂的不是原始数据，是标签库+指标库的产物 —— 符合「下游只读标签库」。
每个数字都能点开看到支撑它的证据/规则/法条。
"""
import json
import psycopg
from decimal import Decimal
from datetime import date, datetime
from psycopg.rows import dict_row

DSN = "postgresql://postgres:x@localhost:55432/reg"
OUT = "/private/tmp/claude-501/-Users-summer-Documents----2026-mini--/32ac52f8-4b06-4a15-9b8a-8294870d83c2/scratchpad/demo_data.json"


def jd(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def main():
    d = {}
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        # ---- 顶部 KPI ----
        cur.execute("SELECT COUNT(*) c FROM enterprise")
        n_ent = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM tag_instance WHERE valid_to IS NULL")
        n_tag = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(DISTINCT entity_type) c FROM tag_dict")
        n_mount = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM rule")
        n_rule = cur.fetchone()["c"]
        d["kpi"] = {"企业总数": n_ent, "当前有效标签": n_tag,
                    "挂载对象覆盖": f"{n_mount}/6", "在库规则": n_rule}

        # ---- 宏观：月度新设趋势 ----
        cur.execute("""
            SELECT to_char(valid_from,'YYYY-MM') AS ym, value::int AS v, sample_size
            FROM metric_instance WHERE metric_id='M-NEW-01'
            ORDER BY valid_from""")
        d["macro_trend"] = [dict(r) for r in cur.fetchall()]

        # ---- 中观：登记机关退回率排名 ----
        cur.execute("""
            SELECT au.authority_name AS name, mi.value AS rate, mi.sample_size AS total,
                   EXISTS(SELECT 1 FROM tag_instance ti WHERE ti.entity_id=au.authority_id
                          AND ti.tag_id='T-XN-01' AND ti.valid_to IS NULL) AS flagged
            FROM metric_instance mi JOIN authority au ON au.authority_id=mi.scope_value
            WHERE mi.metric_id='M-XN-01' ORDER BY mi.value DESC""")
        d["meso_authority"] = [dict(r) for r in cur.fetchall()]

        # ---- 中观：聚集地址 ----
        cur.execute("""
            SELECT ti.entity_id AS addr_id, a.raw_address AS addr,
                   ev.field_snapshot AS snap
            FROM tag_instance ti
            JOIN evidence ev ON ev.evidence_id=ti.evidence_id
            JOIN address a ON a.address_id=ti.entity_id
            WHERE ti.tag_id='T-ZS-02' AND ti.valid_to IS NULL""")
        d["meso_cluster"] = [dict(r) for r in cur.fetchall()]

        # ---- 微观证据链 A：聚集地址（含挂在其上的企业清单）----
        addr = d["meso_cluster"][0]
        cur.execute("""
            SELECT ti.confidence, ti.valid_from, td.tag_name, td.action, td.basis_type, td.basis_ref,
                   r.rule_id, r.rule_version, r.rule_type, r.trigger_point, r.disposal_level, r.law_anchor,
                   ev.field_snapshot, ev.baseline_id
            FROM tag_instance ti
            JOIN tag_dict td ON td.tag_id=ti.tag_id AND td.tag_version=ti.tag_version
            JOIN evidence ev ON ev.evidence_id=ti.evidence_id
            JOIN rule r ON r.rule_id=ev.rule_id AND r.rule_version=ev.rule_version
            WHERE ti.entity_id=%s AND ti.tag_id='T-ZS-02'""", (addr["addr_id"],))
        chain_a = dict(cur.fetchone())
        cur.execute("""SELECT ent_id, ent_name, estab_date FROM enterprise
                       WHERE address_id=%s ORDER BY estab_date DESC LIMIT 8""", (addr["addr_id"],))
        members = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) c FROM enterprise WHERE address_id=%s", (addr["addr_id"],))
        d["evidence_addr"] = {"addr_id": addr["addr_id"], "addr": addr["addr"],
                              "chain": chain_a, "members": members,
                              "member_total": cur.fetchone()["c"]}

        # ---- 微观证据链 B：股权环 ----
        cur.execute("""
            SELECT ti.entity_id, e.ent_name, ti.confidence, ti.valid_from,
                   td.tag_name, td.action, r.rule_id, r.rule_version, r.rule_type,
                   r.trigger_point, r.disposal_level, r.law_anchor, ev.field_snapshot
            FROM tag_instance ti
            JOIN enterprise e ON e.ent_id=ti.entity_id
            JOIN tag_dict td ON td.tag_id=ti.tag_id AND td.tag_version=ti.tag_version
            JOIN evidence ev ON ev.evidence_id=ti.evidence_id
            JOIN rule r ON r.rule_id=ev.rule_id AND r.rule_version=ev.rule_version
            WHERE ti.tag_id='T-BG-05' AND ti.valid_to IS NULL ORDER BY ti.entity_id LIMIT 1""")
        d["evidence_ring"] = dict(cur.fetchone())

        # ---- 受益所有人穿透（图的真价值）----
        cur.execute("""SELECT ent_id, person_id, ratio, max_depth, path
                       FROM beneficial_owner WHERE max_depth>1 ORDER BY ratio DESC LIMIT 5""")
        d["penetration"] = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) a, COUNT(*) FILTER (WHERE max_depth>1) b FROM beneficial_owner")
        r = cur.fetchone()
        d["penetration_stat"] = {"total": r["a"], "indirect": r["b"]}

        # ---- 处置分布（分级处置）----
        cur.execute("""
            SELECT r.disposal_level AS lvl, COUNT(ti.instance_id) AS n
            FROM rule r JOIN tag_instance ti ON ti.tag_id=r.tag_id AND ti.valid_to IS NULL
            GROUP BY r.disposal_level""")
        d["disposal"] = [dict(r) for r in cur.fetchall()]

    with open(OUT, "w") as f:
        json.dump(d, f, ensure_ascii=False, default=jd, indent=1)
    print(f"导出 → {OUT}")
    print(f"  宏观趋势 {len(d['macro_trend'])} 月 | 登记机关 {len(d['meso_authority'])} 个")
    print(f"  聚集地址 {len(d['meso_cluster'])} | 穿透 {d['penetration_stat']}")


if __name__ == "__main__":
    main()
