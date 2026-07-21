-- 指标库装载 —— 与 rules.sql 同构：这里没有一行是程序，全部是数据
--
-- source_type 是这一层的要害：
--   raw_agg —— 业务态势统计，从治理后的核心口径聚合。不是任何标签的聚合，标签库里没有也不该有。
--   tag_agg —— 风险类指标，从 TAG_INSTANCE 聚合。
-- 让「这个数是从标签算的还是从原始数据算的」成为显式、可审计的事实。
--
-- 赛题目标2 原文：宏观是「研判」、中观是「分析」、只有微观才是「预警」。
-- 宏观本就不该只看风险 —— 新设趋势、资本结构演变都是 raw_agg，硬塞进标签库才是错的。
--
-- ★ 趋势不需要另建统计表：METRIC_INSTANCE 按 valid_from 聚合就是趋势（与 TAG_INSTANCE 同构）。

BEGIN;

TRUNCATE metric_instance, metric_dict CASCADE;

-- ============================================================
-- 宏观层（§8.1）—— 态势研判，驱动业务创新与科学决策
-- ============================================================

INSERT INTO metric_dict (metric_id, metric_version, metric_name, source_type,
                         lineage_ref, grain, unit, scope_type, definition, logic) VALUES

('M-NEW-01', 'v1', '月度新设经营主体数', 'raw_agg',
 'enterprise.estab_date 按月计数', '宏观', '户', 'province',
 '统计口径：按成立日期所属自然月计数，含全部存续与非存续主体。不含未核准的申请件。',
$SQL$
SELECT province_code AS scope_value,
       COUNT(*)::numeric AS value,
       COUNT(*) AS sample_size,
       date_trunc('month', estab_date)::timestamptz AS valid_from
FROM enterprise
GROUP BY province_code, date_trunc('month', estab_date)
$SQL$),

('M-CAP-01', 'v1', '新设主体注册资本中位数', 'raw_agg',
 'enterprise.reg_capital 按月中位数', '宏观', '万元', 'province',
 '统计口径：按成立月份取该月新设主体注册资本的中位数。用中位数不用均值 —— 注册资本是长尾分布，均值会被少数巨额认缴带偏。',
$SQL$
SELECT province_code AS scope_value,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY reg_capital)::numeric AS value,
       COUNT(*) AS sample_size,
       date_trunc('month', estab_date)::timestamptz AS valid_from
FROM enterprise
GROUP BY province_code, date_trunc('month', estab_date)
$SQL$),

('M-RISK-01', 'v1', '风险标签命中率（企业口径）', 'tag_agg',
 'TAG_INSTANCE 中挂载对象为企业的标签', '宏观', '%', 'province',
 '统计口径：当前有效的企业类风险标签所覆盖的企业数 ÷ 全部企业数。同一企业命中多个标签只计一次。',
$SQL$
SELECT %(scope_value)s AS scope_value,
       ROUND(100.0 * COUNT(DISTINCT ti.entity_id)
             / NULLIF((SELECT COUNT(*) FROM enterprise), 0), 4)::numeric AS value,
       (SELECT COUNT(*) FROM enterprise)::int AS sample_size,
       now() AS valid_from
FROM tag_instance ti
JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
WHERE td.entity_type = '企业' AND ti.valid_to IS NULL
$SQL$),

-- ============================================================
-- 中观层（§8.2）—— 重点领域分析
-- ============================================================

('M-XN-01', 'v1', '登记机关退回率', 'raw_agg',
 'application.status 按机关聚合', '中观', '%', 'authority',
 '统计口径：已退回件数 ÷ (已核准 + 已退回) 件数。不含在途（校验中）件。'
 '★ 该指标只能证明各机关退回率存在差异，不能证明差异成因 —— '
 '尺度过严与申报质量差在数据上不可分。',
$SQL$
SELECT authority_id AS scope_value,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status = '已退回') / COUNT(*), 4)::numeric AS value,
       COUNT(*)::int AS sample_size,
       now() AS valid_from
FROM application
WHERE status IN ('已核准', '已退回') AND province_code = %(scope_value)s
GROUP BY authority_id
$SQL$),

('M-XN-02', 'v1', '登记机关平均办理时长', 'raw_agg',
 'application.decided_at - submitted_at', '中观', '日', 'authority',
 '统计口径：已办结件（已核准+已退回）的 decided_at 与 submitted_at 之差的均值。'
 '★ 与各省对外宣传的「办理时限」不是一回事，后者是承诺值不是实测值，不可混用。',
$SQL$
SELECT authority_id AS scope_value,
       ROUND(AVG(EXTRACT(EPOCH FROM (decided_at - submitted_at)) / 86400.0)::numeric, 4) AS value,
       COUNT(*)::int AS sample_size,
       now() AS valid_from
FROM application
WHERE status IN ('已核准', '已退回') AND decided_at IS NOT NULL
  AND province_code = %(scope_value)s
GROUP BY authority_id
$SQL$),

('M-ZS-01', 'v1', '聚集地址占比', 'tag_agg',
 'T-ZS-02 标签实例数 ÷ 地址总数', '中观', '%', 'province',
 '统计口径：命中「住所批量聚集」标签的地址数 ÷ 全部地址数。',
$SQL$
SELECT %(scope_value)s AS scope_value,
       ROUND(100.0 * COUNT(DISTINCT ti.entity_id)
             / NULLIF((SELECT COUNT(*) FROM address), 0), 4)::numeric AS value,
       (SELECT COUNT(*) FROM address)::int AS sample_size,
       now() AS valid_from
FROM tag_instance ti
WHERE ti.tag_id = 'T-ZS-02' AND ti.valid_to IS NULL
$SQL$),

-- ------------------------------------------------------------
-- 中观 · 微观专题二画像：直播电商（三级分析深化第一块「肉」）
-- ------------------------------------------------------------
-- 三条指标共同构成「直播电商专题看板」。scope_type='topic'、scope_value='直播电商'。
-- 数据全来自已有标签（T-JY-07 圈定 + 各风险标签叠加），零重复计算 —— 专题画像
-- 就是标签库在一个专题子集上的聚合，正是「标签库唯一出口」的直接兑现。

('M-LIVE-01', 'v1', '直播电商专题·企业数', 'tag_agg',
 'T-JY-07 当前有效标签计数', '中观', '户', 'topic',
 '统计口径：经营范围含直播关键词、被 R-JY-07 圈进直播电商专题的企业数（专题规模）。',
$SQL$
SELECT '直播电商' AS scope_value,
       COUNT(DISTINCT entity_id)::numeric AS value,
       COUNT(DISTINCT entity_id)::int AS sample_size,
       now() AS valid_from
FROM tag_instance WHERE tag_id = 'T-JY-07' AND valid_to IS NULL
$SQL$),

('M-LIVE-02', 'v1', '直播电商专题·许可缺失率', 'tag_agg',
 'T-JY-07 ∩ T-JY-01', '中观', '%', 'topic',
 '统计口径：直播专题企业中同时命中「许可项无批准文件」（R-JY-01）的占比。'
 '直播带货常涉食品/化妆品销售，属许可经营 —— 该率反映专题的准入合规短板。',
$SQL$
SELECT '直播电商' AS scope_value,
       ROUND(100.0 * COUNT(DISTINCT j1.entity_id)
             / NULLIF(COUNT(DISTINCT j7.entity_id), 0), 4)::numeric AS value,
       COUNT(DISTINCT j7.entity_id)::int AS sample_size,
       now() AS valid_from
FROM tag_instance j7
LEFT JOIN tag_instance j1
       ON j1.entity_id = j7.entity_id AND j1.tag_id = 'T-JY-01' AND j1.valid_to IS NULL
WHERE j7.tag_id = 'T-JY-07' AND j7.valid_to IS NULL
$SQL$),

('M-LIVE-03', 'v1', '直播电商专题·合规问题企业占比', 'tag_agg',
 'T-JY-07 ∩ 任一法条类企业风险标签', '中观', '%', 'topic',
 '统计口径：直播专题企业中命中任一「法条类」企业风险标签的占比（不含专题标记本身）。'
 '反映专题整体合规健康度，是专题画像的总览指标。',
$SQL$
SELECT '直播电商' AS scope_value,
       ROUND(100.0 * COUNT(DISTINCT r.entity_id)
             / NULLIF((SELECT COUNT(DISTINCT entity_id) FROM tag_instance
                       WHERE tag_id = 'T-JY-07' AND valid_to IS NULL), 0), 4)::numeric AS value,
       (SELECT COUNT(DISTINCT entity_id) FROM tag_instance
        WHERE tag_id = 'T-JY-07' AND valid_to IS NULL)::int AS sample_size,
       now() AS valid_from
FROM tag_instance r
JOIN tag_dict td ON td.tag_id = r.tag_id AND td.tag_version = r.tag_version
JOIN tag_instance j7 ON j7.entity_id = r.entity_id
                    AND j7.tag_id = 'T-JY-07' AND j7.valid_to IS NULL
WHERE td.entity_type = '企业' AND td.basis_type = '法条' AND r.valid_to IS NULL
$SQL$),

-- ------------------------------------------------------------
-- 中观 · 关联企业集群画像（三级分析深化第二块「肉」）
-- ------------------------------------------------------------
-- 依赖 graph.py 写回的 graph_community（Louvain 社区，SQL 做不了 → 图不可替代的价值）。
-- 每个集群一行：风险企业密度 + 集群规模。高密度小集群 = 疑似关联团伙，是 SQL+图 联手才拿得到的线索。
('M-CLU-01', 'v1', '关联集群·风险企业密度', 'tag_agg',
 'graph_community ⋈ 企业法条风险标签', '中观', '%', 'community',
 '统计口径：每个关联企业集群中，命中任一法条类企业风险标签的企业占比（sample_size=集群规模）。'
 '★ 集群由 Louvain 社区发现得到（SQL 做不了），密度由标签库聚合 —— 图与规则引擎联手的产物。',
$SQL$
SELECT gc.community_id::text AS scope_value,
       ROUND(100.0 * COUNT(DISTINCT ti.entity_id) FILTER (WHERE td.basis_type = '法条')
             / NULLIF(gc.community_size, 0), 4)::numeric AS value,
       gc.community_size AS sample_size,
       now() AS valid_from
FROM graph_community gc
LEFT JOIN tag_instance ti ON ti.entity_type = '企业' AND ti.entity_id = gc.ent_id AND ti.valid_to IS NULL
LEFT JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
WHERE gc.algo = 'louvain'
GROUP BY gc.community_id, gc.community_size
$SQL$);

COMMIT;
