-- 规则库与标签字典的初始装载
-- ★ 这个文件里没有一行是「程序」——全部是数据。
--   改规则 = UPDATE 这张表，不发版、不动引擎。这是方案创新点①的落点。
--
-- 构建顺序遵循方案 §7.5：
--   1. 规则表「风险标签」列去重 → 候选标签（自下而上）  ← 本文件的 tag_dict
--   2. 三级分析需求反推补维度（自上而下）              ← 本轮 3 条规则暂不涉及
--   3. 分配到 6 类挂载对象                              ← tag_dict.entity_type
--   4. 元数据卡，填不满的当场砍掉                       ← action / basis_* 均为 NOT NULL
--   5. 写算子、跑通、产出实例                           ← scripts/engine.py

BEGIN;

TRUNCATE rule_param_override, tag_dict, rule CASCADE;

-- ============================================================
-- 标签字典（定义层 · 静态）
-- ============================================================
-- action 列是 §7.5 第 4 步那个筛子：填不出「命中后谁做什么」的标签，当场砍掉。

INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-CZ-01', 'v1', '出资与注册资本不符', '企业', '布尔',
 '事后回溯：责令改正、限期更正登记。★ 不是阻断 —— 企业已登记，阻断无从谈起',
 '法条', '《公司法》第47条', '每次申报', '更正后失效'),

('T-ZS-02', 'v1', '住所批量聚集', '地址', '布尔',
 '事后回溯：该地址进入重点关注集群清单，下发属地核查实际经营',
 '统计基线', 'addr_ent_count_p99（全省同址主体数 P99）+ 30日新增', '每日', '连续90日新增回落至基线以下则失效'),

('T-BG-05', 'v1', '股权自环', '企业', '布尔',
 '仅打标：作为情报线索纳入关注，核查是否用于抽逃出资/循环注资虚增资本。★ 不作违法认定',
 '统计基线', '图上有向环检测（无禁止性法条 → 情报线索，非法定强制）', '每日', '股权结构变更解环后失效'),

-- ★ 挂载对象 = 业务单据。事前拦截时企业尚不存在，标签无处可挂 —— 只能挂申请件。
('T-CZ-01-PRE', 'v1', '申报出资与注册资本不符', '业务单据', '布尔',
 '事前拦截：校验阶段阻断，退回申请人更正（须 precision>0.99 方可真阻断，否则降级复核）',
 '法条', '《公司法》第47条', '每次申报', '更正重报后失效'),

-- ★ 挂载对象 = 登记机关。这是创新点④：把监管方自己变成标签挂载对象。
--   赛题写了「效能短板」，而效能短板根本不挂在企业身上。
('T-XN-01', 'v1', '登记机关退回率异常偏高', '登记机关', '布尔',
 '仅打标：纳入效能分析，核查该机关退回原因分布与尺度掌握是否与全省一致',
 '统计基线', 'authority_return_rate_p90（全省登记机关退回率 P90）', '每月',
 '连续两个月回落至基线以下则失效'),

-- ★ 挂载对象 = 自然人。官方点名的「被法人」（身份被冒用登记为法定代表人）挂这里。
--   basis_type 必须是「统计基线」不是「法条」—— 无法条规定一人最多任几家法代。
('T-RY-01', 'v1', '职业法人（多企业法定代表人）', '自然人', '布尔',
 '人工复核：核实本人是否知情、是否存在身份冒用。★ 不得据此拒绝登记 —— 一人多任并不违法',
 '统计基线', 'max_legal_rep（任法定代表人企业数阈值，待校准）', '每日',
 '任职关系变更后重算');

-- ---- 本轮新增四个标签（均为法条依据，挂载企业/自然人）----
INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-CZ-02', 'v1', '出资期限超五年', '企业', '布尔',
 '事后回溯：责令将认缴出资期限调整至法定五年内，逾期未调整依法处理',
 '法条', '《公司法》第47条', '每次申报/变更', '出资期限更正至五年内则失效'),

('T-CZ-04', 'v1', '出资备案信息不全', '企业', '布尔',
 '事后回溯：责令补正出资方式/期限等法定备案事项',
 '法条', '《市场主体登记管理条例》第9条', '每次申报/变更', '补正后失效'),

('T-CZ-05', 'v1', '实缴制行业未实缴', '企业', '布尔',
 '事后回溯：责令限期实缴到位。属实缴登记制行业（银行/保险/证券等），实缴额不得为0',
 '法条', '国发〔2014〕7号', '每次申报/变更', '实缴到位后失效'),

-- ★ 法条锚点已核（2026-07-20）：《公司法》第178条第1款第5项 +《市场主体登记管理条例》第12条第(五)项。
('T-SM-06', 'v1', '失信人员违规任职', '自然人', '布尔',
 '人工复核：核查失信被执行人担任法定代表人的任职资格，必要时责令变更法定代表人',
 '法条', '《公司法》第178条第1款第5项 +《市场主体登记管理条例》第12条', '每日',
 '失信状态解除或变更法定代表人后失效');

-- ---- 经营范围两个标签（填 biz_scope 两张空表；引入第四种规则类型「规范性」）----
INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-JY-01', 'v1', '许可项无批准文件', '企业', '布尔',
 '事后回溯：责令补交许可经营项目的批准文件，未补交的核查是否无证经营',
 '法条', '《市场主体登记管理条例》第14条', '每次申报/变更', '补交批准文件后失效'),

-- ★ 方案第一创新点：命中不是「企业错」的定论，而是「目录可能有缺口」的候选。
--   误报回流 → 沉淀为规范表述目录的补充项。故 confidence=0.8（规范性，非法定强制）。
('T-JY-03', 'v1', '经营范围表述不规范', '企业', '布尔',
 '仅打标：生成「目录缺口建议」候选；误报回流沉淀为规范表述目录补充项',
 '法条', '《市场主体登记管理条例》第14条 + 规范表述目录', '每日', '目录更新或表述修正后失效'),

-- ★ 微观专题二入口。basis_type='专题'：不是法条也不是统计基线，是专题范围标记。
--   非风险标签 —— 圈定直播电商企业子集，供三级分析的专题画像层聚合（许可缺失率/聚集/名称命中）。
('T-JY-07', 'v1', '直播电商专题', '企业', '布尔',
 '仅打标：纳入直播电商微观专题子集，供专题画像与专题内合规规则复用（不作违规认定）',
 '专题', '经营范围含 网络直播/直播电商/互联网直播 关键词', '每日', '经营范围变更移出关键词后失效');

-- ---- 名称与生命周期三个标签（R-MC-01/02 挂业务单据·事前 · R-ZX-01 挂企业·事后）----
INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-MC-01', 'v1', '名称缺失', '业务单据', '布尔',
 '事前拦截：校验阶段阻断，退回补填名称（须 precision>0.99 方可真阻断，否则降级复核）',
 '法条', '《公司法》第32条', '每次申报', '补填名称后失效'),

-- ★ 最佳 Demo 素材：2026 版文书规范新增禁限用词（虚拟货币/稳定币/RWA 等）。
('T-MC-02', 'v1', '名称含禁限用词', '业务单据', '布尔',
 '事前拦截：命中禁限用词表即阻断，退回改名（须 precision>0.99 方可真阻断，否则降级复核）',
 '法条', '《经营主体登记文书规范(2026年版)》', '词表更新即生效', '改名后失效'),

('T-ZX-01', 'v1', '应注销未注销', '企业', '布尔',
 '仅打标：营业执照已吊销但未申请注销，纳入清理台账，提示依法办理注销登记',
 '法条', '《公司法》第37条', '每日', '完成注销登记后失效');

-- ---- 变更/注销两个标签（R-BG-01 挂业务单据 · R-ZX-04 挂企业·数据矛盾零误报）----
INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-BG-01', 'v1', '变更登记逾期', '业务单据', '布尔',
 '仅打标：变更登记超30日申请，记入效能/合规台账，提示按期办理',
 '法条', '《市场主体登记管理条例》第24条', '每次变更', '本次变更登记完成即定格（历史事实不失效）'),

-- ★ 图约束 C4「注销后仍有变更」——赛题原文说的「数据矛盾」，客观且零误报。
('T-ZX-04', 'v1', '注销后仍有变更', '企业', '布尔',
 '人工复核：主体已注销却仍发生变更申请，属数据矛盾，核查是否违规操作或数据错误',
 '法条', '《公司法》第37条（数据一致性推定）', '每日', '数据订正后失效');

-- ---- 登记代理人两个标签（★ 第 6 个挂载对象，挂载达 6/6）----
INSERT INTO tag_dict (tag_id, tag_version, tag_name, entity_type, value_type,
                      action, basis_type, basis_ref, update_freq, expiry_cond) VALUES
('T-SM-03', 'v1', '登记代理人未备案', '登记代理人', '布尔',
 '事后回溯：代理人未按第七条通过系统表明代理身份/备案，责令补正，未补正的代理申报不予受理',
 '法条', '《经营主体登记申请及代理行为管理办法》第七条', '每次代理申报', '完成备案后失效'),

('T-SM-04', 'v1', '登记代理人兼任登记联络员', '登记代理人', '布尔',
 '人工复核：登记代理人兼任经营主体登记联络员（非自设主体），核查并责令改正',
 '法条', '《经营主体登记申请及代理行为管理办法》第五条第二款', '每日', '解除兼任后失效');

-- ============================================================
-- 规则库
-- ============================================================

-- ---------- R-CZ-01 出资与注册资本不符 · 事后清存量（法定强制 · 纯 SQL）----------
-- ★ 触发时点是「事后回溯」不是「事前拦截」—— 这里踩过一次坑，留个记号：
--   曾照抄方案 §5.3 规则表样例标成「事前拦截 + 硬阻断」，但本规则的 logic 查的是
--   enterprise 表（已登记企业）。企业都登记完了，拦什么？阻断什么？
--   **规则声明的触发时点，必须与它的 logic 实际作用的对象一致**：
--     事前拦截 → 只能查 application（此时企业尚不存在）→ 见 R-CZ-01-PRE
--     事后回溯 → 查 enterprise
--   处置也随之改为「人工复核」：已登记企业只能责令改正，不存在「阻断」这个动作。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-CZ-01', 'v1', '《公司法》第47条', '法定强制', '事后回溯', '人工复核', '企业', 'T-CZ-01',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '注册资本',  e.reg_capital,
         '认缴合计',  SUM(i.subscribed_amount),
         '差额',      SUM(i.subscribed_amount) - e.reg_capital,
         '股东数',    COUNT(*),
         '法条要求',  '注册资本为全体股东认缴出资额之和'
       ) AS snapshot
FROM enterprise e
JOIN investment i ON i.investee_ent_id = e.ent_id
GROUP BY e.ent_id, e.reg_capital
HAVING SUM(i.subscribed_amount) <> e.reg_capital
$SQL$,
'{}'::jsonb,
1.0);   -- 法定强制 → 必须 1.0，由 ck_mandatory_conf_one 强制

-- ---------- R-ZS-02 住所批量聚集（统计异常 · 分位数基线 + 时间窗）----------
-- ★ 时间窗不是可选项：实测只用 P99 时 precision=0.500，合法集群注册地址被全部误报。
--   合法集群是每月涓流，虚假批量是30天暴增，只有时间窗分得开。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params,
                  confidence_prior, baseline_metric, baseline_sql) VALUES
('R-ZS-02', 'v1', NULL, '统计异常', '事后回溯', '人工复核', '地址', 'T-ZS-02',
$SQL$
WITH c AS (
  SELECT address_id, COUNT(*) AS n,
         COUNT(*) FILTER (WHERE estab_date > %(as_of)s::date - %(window_days)s) AS new30
  FROM enterprise
  WHERE province_code = %(scope_value)s
  GROUP BY address_id
)
SELECT c.address_id AS entity_id,
       jsonb_build_object(
         '同址主体数',      c.n,
         '基线_P99',        %(baseline_value)s,
         '基线样本量',      %(baseline_sample_size)s,
         '近N日新增',       c.new30,
         '时间窗天数',      %(window_days)s,
         '新增阈值',        %(new_threshold)s,
         '判定',            '同址主体数超全省P99 且 时间窗内新增超阈值'
       ) AS snapshot
FROM c
WHERE c.n > %(baseline_value)s
  AND c.new30 > %(new_threshold)s
$SQL$,
'{"as_of": "2026-07-17", "window_days": 30, "new_threshold": 10, "quantile": 0.99}'::jsonb,
0.6,   -- 统计异常 → 冷启动保守先验；一旦复核回流≥20次，由实测 precision 覆盖
'addr_ent_count_p99',
$SQL$
WITH c AS (
  SELECT address_id, province_code, COUNT(*) AS n
  FROM enterprise GROUP BY address_id, province_code
)
SELECT province_code AS scope_value,
       PERCENTILE_CONT(%(quantile)s) WITHIN GROUP (ORDER BY n) AS value,
       COUNT(*) AS sample_size
FROM c GROUP BY province_code
$SQL$);

-- ---------- R-BG-05 股权自环（情报线索 · 图算法）----------
-- ★ 类型从「法定强制」降级为「情报线索」（2026-07-19，核实后定案）：
--   曾挂《受益所有人信息管理办法》做法条锚点，但核实原文后确认——该办法讲的是备案
--   （第4/5/8条），根本不涉及"股权不得成环"。而股权环本身《公司法》亦无明文禁止
--   （除非被用于抽逃出资）。既无禁止性法条，就不配叫「法定强制」。
--   → 股权成环是「去查什么」的线索（可能是抽逃出资、循环注资虚增资本），不是「判了谁违法」。
--     这最符合原则6「监测已发生 ≠ 预测未来」：呈现事实序列，把定性留给人。
--   law_anchor 置 NULL（情报类无需法源），confidence 先验 0.3（低），处置降为「仅打标」。
--   这一改是纯 UPDATE 数据，engine.py 一行不动 —— 又一次「规则即数据」。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-BG-05', 'v1', NULL, '情报线索', '事后回溯',
 '仅打标', '企业', 'T-BG-05',
$SQL$
WITH RECURSIVE walk(origin, current, depth, path) AS (
  SELECT investor_ent_id, investee_ent_id, 1,
         ARRAY[investor_ent_id::text, investee_ent_id::text]
  FROM investment WHERE investor_type = 'ENTERPRISE'
  UNION ALL
  SELECT w.origin, i.investee_ent_id, w.depth + 1, w.path || i.investee_ent_id::text
  FROM walk w
  JOIN investment i ON i.investor_ent_id = w.current AND i.investor_type = 'ENTERPRISE'
  WHERE w.depth < %(max_depth)s AND w.current <> w.origin
),
rings AS (
  SELECT origin, depth, path,
         ROW_NUMBER() OVER (PARTITION BY origin ORDER BY depth) AS rk
  FROM walk WHERE current = origin
)
SELECT origin AS entity_id,
       jsonb_build_object(
         '环长',     depth,
         '环路径',   path,
         '判定',     '股权关系在图上存在有向环',
         '穿透深度上限', %(max_depth)s
       ) AS snapshot
FROM rings WHERE rk = 1
$SQL$,
'{"max_depth": 6}'::jsonb,
0.3);   -- 情报线索 → 低先验；股权成环是线索不是定性

-- ---------- R-CZ-01-PRE 出资不符 · 事前拦截（法定强制 · 挂业务单据）----------
-- ★ 与 R-CZ-01 同法条、同标签，但触发时点不同 → 方案 §5.3：「同一规则在不同时点是完全不同的产品」。
--   事前拦截时企业尚不存在（统一社会信用代码未发放），判定对象只能是申请件的 payload。
--   事前防新增，事后清存量：那 30 家出资不符的已登记企业是存量，规则上线时早已核准。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-CZ-01-PRE', 'v1', '《公司法》第47条', '法定强制', '事前拦截', '硬阻断',
 '业务单据', 'T-CZ-01-PRE',
$SQL$
SELECT a.app_id AS entity_id,
       jsonb_build_object(
         '申报注册资本', (a.payload->>'注册资本')::numeric,
         '申报认缴合计', (SELECT SUM((s->>'认缴')::numeric)
                          FROM jsonb_array_elements(a.payload->'股东') s),
         '差额',         (SELECT SUM((s->>'认缴')::numeric)
                          FROM jsonb_array_elements(a.payload->'股东') s)
                         - (a.payload->>'注册资本')::numeric,
         '登记机关',     a.authority_id,
         '提交时间',     a.submitted_at,
         '法条要求',     '注册资本为全体股东认缴出资额之和',
         '说明',         '申报尚未核准，企业实体不存在，判定对象为申请件'
       ) AS snapshot
FROM application a
WHERE a.status = '校验中'
  AND (SELECT SUM((s->>'认缴')::numeric) FROM jsonb_array_elements(a.payload->'股东') s)
      <> (a.payload->>'注册资本')::numeric
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-XN-01 登记机关退回率异常（统计异常 · 挂登记机关）----------
-- ★ 创新点④：把监管方自己变成标签挂载对象。
--   赛题白纸黑字写了「效能短板」，但效能标签不挂企业 —— 挂业务单据和登记机关。
--   「各地标准不一」由此从一句话变成一张可排名的表。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params,
                  confidence_prior, baseline_metric, baseline_sql) VALUES
('R-XN-01', 'v1', NULL, '统计异常', '事后回溯', '仅打标', '登记机关', 'T-XN-01',
$SQL$
WITH r AS (
  SELECT authority_id,
         COUNT(*) FILTER (WHERE status = '已退回')::numeric / COUNT(*) AS return_rate,
         COUNT(*) AS total,
         AVG(EXTRACT(EPOCH FROM (decided_at - submitted_at)) / 86400.0) AS avg_days
  FROM application
  WHERE status IN ('已核准', '已退回') AND province_code = %(scope_value)s
  GROUP BY authority_id
)
SELECT r.authority_id AS entity_id,
       jsonb_build_object(
         '退回率',        ROUND(r.return_rate, 4),
         '基线_P90',      ROUND(%(baseline_value)s::numeric, 4),
         '基线样本量',    %(baseline_sample_size)s,
         '办件总量',      r.total,
         '平均办理天数',  ROUND(r.avg_days::numeric, 2),
         '机关名称',      au.authority_name,
         '判定',          '该机关退回率超出全省登记机关退回率 P90 基线'
       ) AS snapshot
FROM r JOIN authority au ON au.authority_id = r.authority_id
WHERE r.return_rate > %(baseline_value)s
$SQL$,
'{"quantile": 0.90}'::jsonb,
0.6,
'authority_return_rate_p90',
$SQL$
WITH r AS (
  SELECT authority_id, province_code,
         COUNT(*) FILTER (WHERE status = '已退回')::numeric / COUNT(*) AS return_rate
  FROM application WHERE status IN ('已核准', '已退回')
  GROUP BY authority_id, province_code
)
SELECT province_code AS scope_value,
       PERCENTILE_CONT(%(quantile)s) WITHIN GROUP (ORDER BY return_rate) AS value,
       COUNT(*) AS sample_size
FROM r GROUP BY province_code
$SQL$);

-- ---------- R-RY-01 职业法人（统计异常 · 挂自然人）----------
-- ★ 必须是「统计异常」不是「法定强制」：**没有任何法条规定一人最多任几家法定代表人**。
--   《公司法》未禁止一人多任。硬安一个法条会被业务评委当场戳穿（方案 §5.3 规则类型列的存在意义）。
--   它是官方点名的「被法人」（身份被冒用批量登记）的已知信号，但信号 ≠ 违法。
-- ★ 注意这条是纯 SQL —— COUNT(*) GROUP BY 而已，**不需要图**。
--   「职业法人」听起来像图算法，其实是个聚合。图的价值在变长路径，不在这里。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-RY-01', 'v1', NULL, '统计异常', '事后回溯', '人工复核', '自然人', 'T-RY-01',
$SQL$
SELECT p.person_id AS entity_id,
       jsonb_build_object(
         '任法定代表人企业数', COUNT(*),
         '阈值',               %(max_legal_rep)s,
         '涉及企业',           jsonb_agg(ph.ent_id ORDER BY ph.ent_id),
         '判定',               '同一自然人担任法定代表人的企业数超过阈值',
         '说明',               '统计异常，非法定强制 —— 无法条规定一人最多任几家法代。'
                               '本标签仅为「被法人」（身份冒用）的线索，不构成违法认定'
       ) AS snapshot
FROM position_hold ph
JOIN person p ON p.person_id = ph.person_id
WHERE ph.post_type = '法定代表人'
GROUP BY p.person_id
HAVING COUNT(*) > %(max_legal_rep)s
$SQL$,
'{"max_legal_rep": 5}'::jsonb,
0.6);

-- ============================================================
-- 属地差异化参数（示范：同一条规则、同一份 logic，各省不同参数）
-- ============================================================
-- 本轮 3 条规则暂无省际差异，此处留一条注释说明机制：
-- 「浙江冠省名企业注册资本最低认缴 1000 万 / 河南 100 万」将来会是这样两行：
--   ('R-MC-0X','v1','province','33','{"min_capital": 10000000}', '浙江省市监局办事指南')
--   ('R-MC-0X','v1','province','41','{"min_capital": 1000000}',  '河南省市监局办事指南')
-- 同一条 logic，两个参数，差10倍。这就是「统一规则中台 + 属地差异化参数」，
-- 而不是「全国一刀切」，也不是「各省各写一条规则」。

-- ============================================================
-- 本轮新增四条规则（一步同时推目标1「可执行规则」与目标2「标签数量」）
-- ============================================================

-- ---------- R-CZ-02 出资期限超五年（法定强制 · 纯 SQL）----------
-- 《公司法》第47条：注册资本为全体股东认缴出资额，自公司成立之日起【五年内缴足】。
--   认缴出资期限晚于「成立日 + 5 年」= 违反法定缴足期限。
--   用 investment.contrib_deadline；缺失（NULL）者不参与判定（那是 R-CZ-04 的事）。
-- ★ 五年边界用 SQL 的 INTERVAL '5 years'（按日历年，闰年安全），不在应用层拍天数。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-CZ-02', 'v1', '《公司法》第47条', '法定强制', '事后回溯', '人工复核', '企业', 'T-CZ-02',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '成立日期',     e.estab_date,
         '法定缴足期限', (e.estab_date + INTERVAL '5 years')::date,
         '最晚出资期限', MAX(i.contrib_deadline),
         '超期天数',     MAX(i.contrib_deadline) - (e.estab_date + INTERVAL '5 years')::date,
         '法条要求',     '注册资本自公司成立之日起五年内缴足'
       ) AS snapshot
FROM enterprise e
JOIN investment i ON i.investee_ent_id = e.ent_id
WHERE i.contrib_deadline IS NOT NULL
GROUP BY e.ent_id, e.estab_date
HAVING MAX(i.contrib_deadline) > (e.estab_date + INTERVAL '5 years')::date
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-CZ-04 出资备案不全（法定强制 · 纯 SQL 查空值）----------
-- 《市场主体登记管理条例》第9条：出资信息属法定备案事项。
--   出资方式（contrib_method）或出资期限（contrib_deadline）为空 = 备案不全。
-- ★ 命中≠必然是企业违法：也可能是该省登记系统未采集该字段（§3.5 规则证明差异存在，
--   不证明成因）。故处置是「责令补正/核查」而非阻断；confidence=1.0 说的是「该项确为空」这个事实。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-CZ-04', 'v1', '《市场主体登记管理条例》第9条', '法定强制', '事后回溯', '人工复核', '企业', 'T-CZ-04',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '缺出资方式', bool_or(i.contrib_method IS NULL),
         '缺出资期限', bool_or(i.contrib_deadline IS NULL),
         '股东数',     COUNT(*),
         '法条要求',   '出资信息（出资方式、出资期限）属法定备案事项，应完整备案'
       ) AS snapshot
FROM enterprise e
JOIN investment i ON i.investee_ent_id = e.ent_id
GROUP BY e.ent_id
HAVING bool_or(i.contrib_method IS NULL) OR bool_or(i.contrib_deadline IS NULL)
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-CZ-05 实缴制行业未实缴（法定强制 · 纯 SQL）----------
-- 国发〔2014〕7号：认缴制改革保留【部分行业】的实缴登记制（银行/证券/保险等）。
--   主行业码 ∈ 实缴名录 且 实缴额=0 = 违反该行业的实缴要求。
-- ★ 实缴名录用 params 传（属地/时点可调），不写死在 logic：改名录 = 改数据不改引擎。
--   关键难负例：属实缴制行业但【已足额实缴】的正规金融机构，不得误报。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-CZ-05', 'v1', '国发〔2014〕7号', '法定强制', '事后回溯', '人工复核', '企业', 'T-CZ-05',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '主行业码', e.industry_code,
         '实缴额',   e.paid_capital,
         '注册资本', e.reg_capital,
         '判定',     '属实缴登记制行业但实缴额为0',
         '法条依据', '国发〔2014〕7号 保留实缴登记制的行业（银行/证券/保险等）'
       ) AS snapshot
FROM enterprise e
WHERE e.industry_code = ANY(%(paid_in_industries)s)
  AND e.paid_capital = 0
$SQL$,
'{"paid_in_industries": ["J66", "J67", "J68"]}'::jsonb,
1.0);

-- ---------- R-SM-06 失信人员违规任职（法定强制 · 纯 SQL 关联失信名单）----------
-- 失信被执行人担任法定代表人 —— 失信名单是【外部关联数据】，落 person.is_dishonest 后可判。
-- ★ 法条锚点已核实（2026-07-20，源：全国人大《公司法》2023修订 +《市场主体登记管理条例》）：
--   · 《公司法》第178条第1款第5项：「个人因所负数额较大债务到期未清偿被人民法院列为失信
--     被执行人」不得担任董事/监事/高管；再经第10条（法代由董事或经理担任）穿透到法定代表人。
--   · 《市场主体登记管理条例》第12条第(五)项：直接规定「个人所负数额较大的债务到期未清偿」
--     不得担任法定代表人 —— 对法代的直接锚点。
--   → 从「第__条 待核」升级为已核，本项目待核法条清零。
-- ⚠ 已知口径缺口（对应原「问题3·事由」）：法条限定的是【因大额债务】致失信，而失信被执行人
--   另有拒执/违反限高令等 6 类事由（最高法规定）。本规则只有 is_dishonest 布尔、无失信事由字段，
--   故命中集合略宽于严格法条边界。现实中失信绝大多数为债务类，暂按「命中→人工复核」处置（复核员
--   核事由），并在此备注；若要法条级精确，需给 person 增「失信事由/金额」字段后收窄 WHERE。
--   时点上（问题3·时点）新任与存量均在禁列（任职期间出现即应解除职务），故报存量方向正确。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-SM-06', 'v1', '《公司法》第178条第1款第5项、《市场主体登记管理条例》第12条', '法定强制', '事后回溯', '人工复核', '自然人', 'T-SM-06',
$SQL$
SELECT p.person_id AS entity_id,
       jsonb_build_object(
         '失信起始日',         p.dishonest_since,
         '任法定代表人企业数', COUNT(DISTINCT ph.ent_id),
         '涉及企业',           jsonb_agg(DISTINCT ph.ent_id),
         '判定',               '失信被执行人担任法定代表人',
         '说明',               '失信被执行人不得任法定代表人：《公司法》第178条第1款第5项 +《市场主体登记管理条例》第12条。'
                               '注：法条限「因大额债务」致失信，本规则未区分失信事由，命中略宽，交人工复核核实'
       ) AS snapshot
FROM person p
JOIN position_hold ph ON ph.person_id = p.person_id
WHERE p.is_dishonest = TRUE AND ph.post_type = '法定代表人'
GROUP BY p.person_id, p.dishonest_since
$SQL$,
'{}'::jsonb,
1.0);

-- ============================================================
-- 经营范围两条规则（本轮新增；填 biz_scope 空表，引入「规范性」类型 + 目录缺口回流）
-- ============================================================

-- ---------- R-JY-01 许可项无批准文件（法定强制 · 纯 SQL）----------
-- 《市场主体登记管理条例》第14条：登记前依法须经批准的许可经营项目，应当提交批准文件。
--   经营范围含许可项（biz_scope_item.is_licensed=true）但 ent_biz_scope.approval_no 为空 = 命中。
-- ★ 触发时点是「事后回溯」不是表格里的「事前拦截」：本 logic 查 ent_biz_scope（已登记企业的
--   经营范围），按 §3.6 触发时点一致性约束——查 enterprise 侧的规则只能是事后回溯，处置随之
--   降为人工复核（企业已登记，无「阻断」可言）。事前版应查 application.payload，待经营范围进
--   申报流程后再补 R-JY-01-PRE。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-JY-01', 'v1', '《市场主体登记管理条例》第14条', '法定强制', '事后回溯', '人工复核', '企业', 'T-JY-01',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '许可经营项目', jsonb_agg(DISTINCT bs.item_name),
         '缺批准文件',   true,
         '法条要求',     '登记前依法须经批准的许可经营项目，应当提交批准文件'
       ) AS snapshot
FROM enterprise e
JOIN ent_biz_scope ebs ON ebs.ent_id = e.ent_id
JOIN biz_scope_item bs ON bs.item_id = ebs.item_id
WHERE bs.is_licensed = TRUE AND ebs.approval_no IS NULL
GROUP BY e.ent_id
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-JY-03 经营范围表述不规范 / 目录缺口（规范性 · 纯 SQL）----------
-- 《市场主体登记管理条例》第14条 + 规范表述目录：经营范围应按登记机关公布的分类标准填报。
--   条目对不上规范目录（ent_biz_scope.item_id 为空）= 命中。
-- ★ 类型是「规范性」（第四种，本轮首次引入），不是法定强制：
--   「不在目录」不必然=企业表述错——可能是【目录本身有缺口】（新业态目录尚未收录）。
--   这正是方案第一创新点：命中→生成「目录缺口建议」候选，误报回流沉淀为目录补充项。
--   故 confidence 先验 0.8（< 1.0）：把「目录可能会错」这件事编码进置信度，而非假装 100% 确定。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-JY-03', 'v1', '《市场主体登记管理条例》第14条', '规范性', '事后回溯', '仅打标', '企业', 'T-JY-03',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '目录外表述', jsonb_agg(ebs.raw_text),
         '条目数',     COUNT(*),
         '判定',       '经营范围条目未匹配规范表述目录（item_id 为空）',
         '说明',       '不必然是企业表述错——也可能是规范目录有缺口。命中→目录缺口建议候选'
       ) AS snapshot
FROM enterprise e
JOIN ent_biz_scope ebs ON ebs.ent_id = e.ent_id
WHERE ebs.item_id IS NULL
GROUP BY e.ent_id
$SQL$,
'{}'::jsonb,
0.8);

-- ---------- R-JY-07 直播电商专题标记（规范性 · 专题圈定 · 非风险）----------
-- 微观专题二入口。经营范围含直播关键词 → 圈进直播电商专题子集。
-- ★ 这是范围标记不是风险：law_anchor=NULL，disposal=仅打标。圈定后供三级分析的专题画像层
--   聚合（该子集的许可缺失率/同址聚集/名称禁限用词命中），以及专题内规则复用（如 R-JY-01 许可）。
-- ★ 关键词表存 params（改词表不改引擎）；strpos 子串匹配。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-JY-07', 'v1', NULL, '规范性', '事后回溯', '仅打标', '企业', 'T-JY-07',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '直播相关表述', jsonb_agg(ebs.raw_text),
         '判定',         '经营范围含网络直播/直播电商相关表述，纳入直播电商专题',
         '说明',         '专题范围标记，非风险（原则6：圈定专题范围，不作违规认定）'
       ) AS snapshot
FROM enterprise e
JOIN ent_biz_scope ebs ON ebs.ent_id = e.ent_id
WHERE EXISTS (SELECT 1 FROM unnest(%(live_keywords)s::text[]) w
              WHERE strpos(ebs.raw_text, w) > 0)
GROUP BY e.ent_id
$SQL$,
'{"live_keywords": ["网络直播", "直播带货", "直播电商", "互联网直播"]}'::jsonb,
0.8);

-- ============================================================
-- 名称与生命周期三条规则（本轮新增；快速推进目标2 标签数量）
-- ============================================================

-- ---------- R-MC-01 名称缺失（法定强制 · 事前拦截 · 挂业务单据）----------
-- 《公司法》第32条：名称为公司登记事项。名称为空 = 命中。
-- ★ 必须事前（挂 application.payload）而非事后：enterprise.ent_name 是 NOT NULL，
--   已登记企业不可能缺名称——缺名称只发生在核准前的申报件里。与 R-CZ-01-PRE 同构。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-MC-01', 'v1', '《公司法》第32条', '法定强制', '事前拦截', '硬阻断', '业务单据', 'T-MC-01',
$SQL$
SELECT a.app_id AS entity_id,
       jsonb_build_object(
         '申报名称', COALESCE(a.payload->>'名称', ''),
         '登记机关', a.authority_id,
         '判定',     '企业名称为空',
         '法条要求', '名称为公司登记事项（《公司法》第32条）'
       ) AS snapshot
FROM application a
WHERE a.status = '校验中'
  AND (a.payload->>'名称' IS NULL OR a.payload->>'名称' = '')
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-MC-02 名称含禁限用词（法定强制 · 事前拦截 · 挂业务单据）----------
-- 《经营主体登记文书规范(2026年版)》：新增禁限用词（虚拟货币/稳定币/RWA 等）。
-- ★ 禁限用词表用 params 传（规则即数据，改词表不改引擎）。用 strpos 而非 LIKE '%…%'，
--   避免引擎侧 % 转义麻烦；词表命中即阻断。★ 最佳 Demo 素材。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-MC-02', 'v1', '《经营主体登记文书规范(2026年版)》', '法定强制', '事前拦截', '硬阻断', '业务单据', 'T-MC-02',
$SQL$
SELECT a.app_id AS entity_id,
       jsonb_build_object(
         '申报名称',     a.payload->>'名称',
         '命中禁限用词', (SELECT jsonb_agg(w) FROM unnest(%(forbidden_words)s::text[]) w
                          WHERE strpos(a.payload->>'名称', w) > 0),
         '判定',         '企业名称含禁限用词',
         '法条依据',     '《经营主体登记文书规范(2026年版)》禁限用词规定'
       ) AS snapshot
FROM application a
WHERE a.status = '校验中'
  AND EXISTS (SELECT 1 FROM unnest(%(forbidden_words)s::text[]) w
              WHERE strpos(a.payload->>'名称', w) > 0)
$SQL$,
'{"forbidden_words": ["虚拟货币","加密货币","稳定币","数字藏品","元宇宙币","区块链金融","P2P网贷","RWA数字资产"]}'::jsonb,
1.0);

-- ---------- R-ZX-01 应注销未注销（法定强制 · 事后回溯 · 挂企业）----------
-- 《公司法》第37条：因解散、被吊销营业执照、被宣告破产等法定事由终止的，应依法注销。
--   营业执照已吊销（status=吊销）但未办理注销登记 = 命中。
-- ★ NOT EXISTS 注销申请：当前未合成注销申请件，故对所有吊销企业成立；
--   将来接入注销流程后，已注销者自动落出——规则前瞻性写好，不必回改。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-ZX-01', 'v1', '《公司法》第37条', '法定强制', '事后回溯', '仅打标', '企业', 'T-ZX-01',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '主体状态', e.status,
         '判定',     '营业执照已吊销但未申请注销登记',
         '法条要求', '因解散/被吊销/被宣告破产等法定事由终止的，应依法申请注销登记（《公司法》第37条）'
       ) AS snapshot
FROM enterprise e
WHERE e.status = '吊销'
  AND NOT EXISTS (SELECT 1 FROM application a
                  WHERE a.ent_id = e.ent_id AND a.app_type = '注销' AND a.status = '已核准')
$SQL$,
'{}'::jsonb,
1.0);

-- ============================================================
-- 变更/注销两条规则（本轮新增；补齐 application 三种 app_type 的生命周期）
-- ============================================================

-- ---------- R-BG-01 变更登记逾期（法定强制 · 挂业务单据）----------
-- 《市场主体登记管理条例》第24条：自作出变更决议/决定或法定变更事项发生之日起30日内申请变更。
--   变更申请日（submitted_at）- 决议日期（payload.决议日期）> 30 日 = 逾期。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-BG-01', 'v1', '《市场主体登记管理条例》第24条', '法定强制', '事后回溯', '仅打标', '业务单据', 'T-BG-01',
$SQL$
SELECT a.app_id AS entity_id,
       jsonb_build_object(
         '变更事项', a.payload->>'变更事项',
         '决议日期', a.payload->>'决议日期',
         '申请日期', a.submitted_at::date,
         '逾期天数', a.submitted_at::date - (a.payload->>'决议日期')::date - 30,
         '法条要求', '变更登记应自决议/决定或法定变更事项发生之日起30日内申请'
       ) AS snapshot
FROM application a
WHERE a.app_type = '变更'
  AND a.submitted_at::date - (a.payload->>'决议日期')::date > 30
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-ZX-04 注销后仍有变更（法定强制 · 图约束 C4 · 数据矛盾）----------
-- 《公司法》第37条（数据一致性推定）：主体已注销，其后不应再有变更登记发生。
--   企业 status=注销，却存在提交时间晚于注销核准日的变更申请 = 数据矛盾。
-- ★ 这是「已发生的数据矛盾」，客观、零误报（呼应原则6：监测已发生≠预测未来）。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-ZX-04', 'v1', '《公司法》第37条（数据一致性推定）', '法定强制', '事后回溯', '人工复核', '企业', 'T-ZX-04',
$SQL$
SELECT e.ent_id AS entity_id,
       jsonb_build_object(
         '主体状态',   e.status,
         '注销核准日', zx.decided_at::date,
         '注销后变更', jsonb_agg(bg.app_id ORDER BY bg.submitted_at),
         '判定',       '主体已注销，其后仍发生变更登记申请（数据矛盾）'
       ) AS snapshot
FROM enterprise e
JOIN application zx ON zx.ent_id = e.ent_id AND zx.app_type = '注销' AND zx.status = '已核准'
JOIN application bg ON bg.ent_id = e.ent_id AND bg.app_type = '变更'
                   AND bg.submitted_at > zx.decided_at
WHERE e.status = '注销'
GROUP BY e.ent_id, e.status, zx.decided_at
$SQL$,
'{}'::jsonb,
1.0);

-- ============================================================
-- 登记代理人两条规则（★ 挂载第 6 个对象 → 6/6；法源来自 2025 新规）
-- ============================================================

-- ---------- R-SM-03 登记代理人未备案（法定强制 · 挂登记代理人）----------
-- 《经营主体登记申请及代理行为管理办法》第七条：登记代理人应通过全国代理人信息系统表明代理身份
--   并提供法定信息（备案）。filed=FALSE 且有代理申报 = 未备案却在代理，命中。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-SM-03', 'v1', '《经营主体登记申请及代理行为管理办法》第七条', '法定强制', '事后回溯',
 '人工复核', '登记代理人', 'T-SM-03',
$SQL$
SELECT ra.agent_id AS entity_id,
       jsonb_build_object(
         '代理人类型', ra.agent_type,
         '备案状态',   '未备案',
         '代理申报数', (SELECT COUNT(*) FROM application a WHERE a.agent_id = ra.agent_id),
         '法条要求',   '登记代理人应通过全国代理人信息系统表明代理身份并提供法定信息'
       ) AS snapshot
FROM reg_agent ra
WHERE ra.filed = FALSE
  AND EXISTS (SELECT 1 FROM application a WHERE a.agent_id = ra.agent_id)
$SQL$,
'{}'::jsonb,
1.0);

-- ---------- R-SM-04 登记代理人兼任登记联络员（法定强制 · 图约束 C6）----------
-- 《办法》第五条第二款：登记代理人不得兼任经营主体的登记联络员，【自设主体除外】。
--   代理人对应自然人担任某企业登记联络员，且未出资该企业（非自设）= 命中。
-- ★ NOT EXISTS(该人出资该企业) 正是把「自设主体除外」写进判定，不是靠人记着。
INSERT INTO rule (rule_id, rule_version, law_anchor, rule_type, trigger_point,
                  disposal_level, target_entity, tag_id, logic, params, confidence_prior) VALUES
('R-SM-04', 'v1', '《经营主体登记申请及代理行为管理办法》第五条第二款', '法定强制', '事后回溯',
 '人工复核', '登记代理人', 'T-SM-04',
$SQL$
SELECT ra.agent_id AS entity_id,
       jsonb_build_object(
         '代理人自然人',   ra.person_id,
         '兼任联络员企业', jsonb_agg(DISTINCT ph.ent_id),
         '判定',           '登记代理人兼任经营主体登记联络员（非自行出资设立）',
         '法条要求',       '登记代理人不得兼任经营主体的登记联络员，自设主体除外'
       ) AS snapshot
FROM reg_agent ra
JOIN position_hold ph ON ph.person_id = ra.person_id AND ph.post_type = '登记联络员'
WHERE NOT EXISTS (SELECT 1 FROM investment i
                  WHERE i.investor_person_id = ra.person_id AND i.investee_ent_id = ph.ent_id)
GROUP BY ra.agent_id, ra.person_id
$SQL$,
'{}'::jsonb,
1.0);

COMMIT;
