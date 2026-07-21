"""数据接口层 —— FastAPI。三级分析看板 与 Dify 智能问数/报告 的【共用数据地基】。

★ 铁律（原则2「LLM 严格旁路」的接口侧落点）：
  本层只吐【物化资产】—— metric_instance / tag_instance / 画像视图 / 图派生表，
  每个数字都带【口径 + 时点 + 版本】。判定来自规则引擎，数字来自这里，
  LLM（在 Dify 那侧）只做【路由 + 排版】，绝不在这里算数或下判定。

谁调它：
  · 前端看板（Next.js）—— 直连本接口画图表，不经过 Dify。
  · Dify 智能助手 —— 把本接口配成【自定义工具】，问数时反过来调它拿真实数字。

用法：
  uv pip install fastapi uvicorn
  .venv/bin/python scripts/api.py            # 起在 :8000
  curl localhost:8000/catalog/metrics
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

DSN = "postgresql://postgres:x@localhost:55432/reg"
app = FastAPI(title="企业登记合规监测 · 数据接口", version="0.1")

# 浏览器端前端（Next.js）跨域调用需要 CORS。原型期放开全部来源；
# 生产应收窄到前端域名。注意：Dify 服务端调用不受 CORS 限制（CORS 只管浏览器）。
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@contextmanager
def db():
    with psycopg.connect(DSN, row_factory=dict_row) as conn, conn.cursor() as cur:
        yield cur


@app.get("/health")
def health():
    with db() as cur:
        cur.execute("SELECT count(*) c FROM enterprise")
        return {"status": "ok", "enterprises": cur.fetchone()["c"]}


# ============================================================
# 语义层：指标目录 —— Dify 用它把「自然语言问题」映射到 metric_id
# ============================================================
@app.get("/catalog/metrics")
def catalog_metrics():
    """指标目录（含口径定义）。这就是给 Dify 的语义层：
    LLM 读它 → 把「直播电商许可缺失率多少」映射到 M-LIVE-02 → 再调 /metric/M-LIVE-02。"""
    with db() as cur:
        cur.execute("""SELECT metric_id, metric_version, metric_name, grain, unit,
                              source_type, scope_type, definition
                       FROM metric_dict ORDER BY grain DESC, metric_id""")
        return {"metrics": cur.fetchall()}


@app.get("/catalog/tags")
def catalog_tags():
    """标签目录（含法条依据）。供报告/问数说明「这个风险标签是什么、依据哪条法」。"""
    with db() as cur:
        cur.execute("""SELECT td.tag_id, td.tag_name, td.entity_type, td.basis_type,
                              td.basis_ref, r.rule_type, r.disposal_level, r.law_anchor
                       FROM tag_dict td
                       LEFT JOIN rule r ON r.tag_id = td.tag_id
                       ORDER BY td.tag_id""")
        return {"tags": cur.fetchall()}


# ============================================================
# 智能问数核心：返回物化指标值 + 口径 + 时点 + 版本（可审计）
# ============================================================
@app.get("/metric/{metric_id}")
def get_metric(metric_id: str, scope_value: str | None = None):
    """问数返回的每个数字都是物化 metric_instance，附口径。LLM 不得改写或再计算。"""
    with db() as cur:
        cur.execute("SELECT * FROM metric_dict WHERE metric_id=%s "
                    "ORDER BY metric_version DESC LIMIT 1", (metric_id,))
        md = cur.fetchone()
        if not md:
            raise HTTPException(404, f"未知指标 {metric_id}（见 /catalog/metrics）")
        q = ("SELECT scope_type, scope_value, value::float8 AS value, sample_size,"
             " valid_from, metric_version FROM metric_instance"
             " WHERE metric_id=%s AND valid_to IS NULL")
        params: list = [metric_id]
        if scope_value is not None:
            q += " AND scope_value=%s"
            params.append(scope_value)
        q += " ORDER BY valid_from, scope_value"
        cur.execute(q, params)
        return {
            "metric_id": metric_id,
            "metric_name": md["metric_name"],
            "口径": md["definition"],
            "unit": md["unit"],
            "grain": md["grain"],
            "source_type": md["source_type"],
            "data": cur.fetchall(),
            "_note": "数字为物化指标实例，口径见上、时点见 valid_from；LLM 仅排版，不得改写或再计算",
        }


# ============================================================
# 微观画像：一个 ent_id → 一份全息 JSON（前端证据链那屏 & 报告典型案例）
# ============================================================
@app.get("/enterprise/{ent_id}")
def enterprise_profile(ent_id: str):
    with db() as cur:
        cur.execute("SELECT profile FROM v_enterprise_profile WHERE ent_id=%s", (ent_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404, f"未知企业 {ent_id}")
        return r["profile"]


# ============================================================
# 中观：关联企业集群画像
# ============================================================
@app.get("/clusters")
def clusters(limit: int = Query(10, le=50)):
    """关联企业集群，按风险密度降序。高密度小集群 = 疑似关联团伙。"""
    with db() as cur:
        cur.execute("""SELECT scope_value AS community_id, sample_size AS size,
                              value::float8 AS risk_density_pct, valid_from
                       FROM metric_instance WHERE metric_id='M-CLU-01' AND valid_to IS NULL
                       ORDER BY value DESC, sample_size DESC LIMIT %s""", (limit,))
        return {"clusters": cur.fetchall()}


@app.get("/clusters/{community_id}")
def cluster_detail(community_id: int):
    with db() as cur:
        cur.execute("SELECT ent_id, community_size FROM graph_community"
                    " WHERE community_id=%s AND algo='louvain'", (community_id,))
        members = cur.fetchall()
        if not members:
            raise HTTPException(404, f"未知集群 {community_id}")
        ids = [m["ent_id"] for m in members]
        cur.execute("SELECT ent_id, ent_name, status FROM enterprise WHERE ent_id = ANY(%s)", (ids,))
        return {"community_id": community_id,
                "size": members[0]["community_size"],
                "members": cur.fetchall()}


# ============================================================
# 智能报告：产出【结构化数据槽位】——不出散文，散文由 Dify/LLM 排版
# ============================================================
@app.get("/report/situation")
def report_situation():
    """态势研判报告的结构化数据。三级分析各出一段：宏观趋势 / 中观专题+集群 / 微观典型案例。
    ★ 每个数字/每条证据都来自物化资产；LLM 只把它顺成通顺的话，不得增删数字或生成判定。"""
    with db() as cur:
        cur.execute("""SELECT scope_value, value::float8 AS value, sample_size, valid_from
                       FROM metric_instance WHERE metric_id='M-NEW-01' AND valid_to IS NULL
                       ORDER BY valid_from DESC LIMIT 6""")
        macro_new = cur.fetchall()
        cur.execute("""SELECT mi.metric_id, md.metric_name, mi.value::float8 AS value, mi.sample_size
                       FROM metric_instance mi JOIN metric_dict md
                         ON md.metric_id=mi.metric_id AND md.metric_version=mi.metric_version
                       WHERE mi.metric_id LIKE 'M-LIVE-%%' AND mi.valid_to IS NULL
                       ORDER BY mi.metric_id""")
        topic = cur.fetchall()
        cur.execute("""SELECT scope_value AS community_id, sample_size AS size,
                              value::float8 AS risk_pct FROM metric_instance
                       WHERE metric_id='M-CLU-01' AND valid_to IS NULL
                       ORDER BY value DESC LIMIT 3""")
        clusters_top = cur.fetchall()
        cur.execute("""SELECT ti.entity_id, count(*) n FROM tag_instance ti
                       JOIN tag_dict td ON td.tag_id=ti.tag_id AND td.tag_version=ti.tag_version
                       WHERE ti.entity_type='企业' AND ti.valid_to IS NULL AND td.basis_type='法条'
                       GROUP BY ti.entity_id ORDER BY n DESC LIMIT 3""")
        cases = []
        for row in cur.fetchall():
            cur.execute("SELECT profile FROM v_enterprise_profile WHERE ent_id=%s", (row["entity_id"],))
            cases.append(cur.fetchone()["profile"])
        return {
            "报告类型": "态势研判报告（结构化数据槽位，供 LLM 排版）",
            "宏观": {"月度新设趋势": macro_new},
            "中观": {"直播电商专题看板": topic, "高风险关联集群": clusters_top},
            "微观": {"典型案例": cases},
            "生成约束": "每个数字/每条证据均来自物化资产；LLM 仅排版，不得增删数字或生成判定",
        }


if __name__ == "__main__":
    import uvicorn
    # ★ 绑 0.0.0.0（不是 127.0.0.1）：否则 Docker 里的 Dify 容器够不着本机服务。
    #   Dify 侧工具 URL 用 host.docker.internal:8000（Mac/Win）或主机局域网 IP，不要用 localhost。
    uvicorn.run(app, host="0.0.0.0", port=8000)
