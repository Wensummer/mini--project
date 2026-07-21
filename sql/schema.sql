-- 企业登记注册合规风险监测 · 原型 schema v0.1
-- 范围：矩阵B 中 9 省全 ✓ 的核心字段（属地差异字段不在本版）
-- 目标：跑通 schema → 1000 家合成数据 → R-CZ-01 / R-ZS-02 / R-BG-05 → 标签 → 可查询
-- DB：PostgreSQL 16+

BEGIN;

-- ============================================================
-- 一、登记数据层（治理后的核心口径）
-- ============================================================

-- 地址：标准化到房间粒度。
-- 粒度依据：矩阵B「住所粒度要求」行——广东要求门牌号+楼层+房间，北京要求门牌号或房间号，
-- 为最细口径。只标准化到门牌号会让同一栋楼的不同楼层被误判为同址，R-ZS-02 直接失真。
CREATE TABLE address (
    address_id      TEXT PRIMARY KEY,           -- 标准化后的稳定 ID
    raw_address     TEXT        NOT NULL,       -- 申报原文，保留用于证据链快照
    division_code   CHAR(6)     NOT NULL,       -- 行政区划码 GB/T 2260
    province_code   CHAR(2)     NOT NULL,       -- division_code 前 2 位，冗余存储
    road            TEXT,                       -- 以下五项为地址要素切分结果
    house_no        TEXT,
    building        TEXT,
    floor_no        TEXT,
    room_no         TEXT,
    lng             NUMERIC(10,7),
    lat             NUMERIC(10,7),
    norm_method     TEXT,                       -- 归一方式：rule / distance_cluster / manual
    norm_confidence NUMERIC(4,3)                -- 归一置信度，用于报告地址归一准确率
);
CREATE INDEX idx_address_province ON address (province_code);

-- 自然人：证件号与姓名一律哈希存储，原文不落库。
CREATE TABLE person (
    person_id       TEXT PRIMARY KEY,           -- 证件号哈希
    name_hash       TEXT        NOT NULL,
    id_type         TEXT        NOT NULL,       -- 身份证 / 护照 / 港澳台居民居住证 ...
    -- 失信被执行人标记。R-SM-06 需要：失信人不得任法定代表人（《公司法》任职资格）。
    -- ★ 这不是登记数据自带的，是外部关联数据（失信名单）落图后打上的 —— 属"外部关联数据"输入。
    is_dishonest    BOOLEAN     NOT NULL DEFAULT FALSE,
    dishonest_since DATE                        -- 失信起始日，用于判断任职是否在失信期内
);

-- 企业：核心字段来自矩阵B 9/9 行。
CREATE TABLE enterprise (
    ent_id          CHAR(18)    PRIMARY KEY,    -- 统一社会信用代码
    ent_name        TEXT        NOT NULL,       -- 9/9（北京补齐后）
    address_id      TEXT        NOT NULL REFERENCES address(address_id),
    -- 注册资本：万元。必须是 DECIMAL，绝不可用 FLOAT/DOUBLE。
    -- R-CZ-01 是等值比较，浮点误差会凭空造出假阳性——一条规则会因为一个类型选择而报废。
    reg_capital     NUMERIC(18,4) NOT NULL CHECK (reg_capital > 0),
    ent_type        TEXT,                       -- 公司类型。6/9，非核心，可空
    biz_term        TEXT,                       -- 经营期限：长期 / 固定年限
    -- 主行业码（GB/T 4754）与实缴额。R-CZ-05 需要：实缴制行业（银行/保险/证券等）
    -- 实缴额不得为 0（国发〔2014〕7号，认缴制改革保留了部分行业的实缴要求）。
    industry_code   TEXT,                       -- 如 J66=货币金融服务
    paid_capital    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (paid_capital >= 0),  -- 实缴额，万元
    estab_date      DATE        NOT NULL,
    status          TEXT        NOT NULL,       -- 存续 / 注销 / 吊销
    reg_authority   TEXT        NOT NULL,       -- 登记机关：效能标签的挂载对象
    -- province_code 可由 address 关联推出，此处反范式冗余。
    -- 理由：R-ZS-02 需要按省计算 P99 基线，冗余可避免每次基线计算都 join address。
    province_code   CHAR(2)     NOT NULL
);
CREATE INDEX idx_ent_address  ON enterprise (address_id);
CREATE INDEX idx_ent_province ON enterprise (province_code);

-- 出资 / 投资关系。
-- 单表多态：investor_type 区分自然人股东与非自然人股东。
-- 依据：北京申报字段明确区分「自然人股东」与「非自然人股东」。
-- 一张表同时喂两条规则，过滤方式不同：
--   R-CZ-01 → 对某企业的全部股东求和，不分类型
--   R-BG-05 → 只取 investor_type='ENTERPRISE' 的边建图，自然人不可能被投资，构不成环
CREATE TABLE investment (
    inv_id              BIGSERIAL PRIMARY KEY,
    investee_ent_id     CHAR(18)  NOT NULL REFERENCES enterprise(ent_id),
    investor_type       TEXT      NOT NULL CHECK (investor_type IN ('NATURAL','ENTERPRISE')),
    investor_person_id  TEXT      REFERENCES person(person_id),
    investor_ent_id     CHAR(18)  REFERENCES enterprise(ent_id),
    subscribed_amount   NUMERIC(18,4) NOT NULL CHECK (subscribed_amount > 0),  -- 认缴出资额，万元
    subscribe_ratio     NUMERIC(9,6),           -- 出资比例。4/9
    contrib_method      TEXT,                   -- 出资方式。6/9
    -- 出资时间：矩阵B 显示仅沪粤明确采集，苏浙渝陕疑缺（★必核）。
    -- 保留字段并允许 NULL —— NULL 本身即「该省未采集」的证据。
    -- 若核实属实，R-CZ-02（《公司法》第47条五年缴足）在缺失省份无法校验 = 第一个实证的监管堵点。
    contrib_deadline    DATE,
    -- 多态完整性：类型与外键必须严格对应，否则图上会出现悬空节点
    CONSTRAINT ck_investor_polymorphic CHECK (
        (investor_type = 'NATURAL'    AND investor_person_id IS NOT NULL AND investor_ent_id IS NULL)
     OR (investor_type = 'ENTERPRISE' AND investor_ent_id    IS NOT NULL AND investor_person_id IS NULL)
    )
);
CREATE INDEX idx_inv_investee   ON investment (investee_ent_id);
CREATE INDEX idx_inv_investor_e ON investment (investor_ent_id) WHERE investor_type = 'ENTERPRISE';

-- 任职：法代 / 董监高 / 联络员 / 财务负责人 收敛为一张表。
-- 「登记联络员」在各省名称不统一（北京=相关联系人，河南=办税人（联络员）），
-- 此处统一到法定表述，原始称谓记入 raw_post_name。
CREATE TABLE position_hold (
    pos_id          BIGSERIAL PRIMARY KEY,
    ent_id          CHAR(18)  NOT NULL REFERENCES enterprise(ent_id),
    person_id       TEXT      NOT NULL REFERENCES person(person_id),
    post_type       TEXT      NOT NULL CHECK (post_type IN
                        ('法定代表人','董事','监事','经理','登记联络员','财务负责人')),
    raw_post_name   TEXT,                       -- 该省的原始称谓，属地差异证据
    effective_date  DATE
);
CREATE INDEX idx_pos_ent    ON position_hold (ent_id);
CREATE INDEX idx_pos_person ON position_hold (person_id);

-- 经营范围条目（规范表述目录）。9/9 目录勾选（北京补齐 + 辽宁反例排除后）。
CREATE TABLE biz_scope_item (
    item_id         TEXT PRIMARY KEY,           -- 规范表述目录 ID
    item_name       TEXT NOT NULL,
    industry_code   TEXT,                       -- GB/T 4754
    is_licensed     BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE ent_biz_scope (
    ent_id          CHAR(18) NOT NULL REFERENCES enterprise(ent_id),
    item_id         TEXT     REFERENCES biz_scope_item(item_id),
    raw_text        TEXT     NOT NULL,          -- 申报原文
    -- 许可经营项目的批准文件号。is_licensed 项而此列为空 ⇒ R-JY-01 命中
    -- （《条例》第14条：登记前依法须经批准的许可经营项目，应提交批准文件）。
    approval_no     TEXT,
    -- item_id IS NULL ⇒ 该条目对不上规范目录 ⇒ 即目录缺口候选（方案 §9.4）⇒ R-JY-03 命中
    PRIMARY KEY (ent_id, raw_text)
);
CREATE INDEX idx_ent_biz_scope_ent ON ent_biz_scope (ent_id);

-- ============================================================
-- 一之二、业务流程层（方案 §5.1 的两类「非典型」实体）
-- ============================================================
-- 为什么必须有这一层，三个理由，缺一个都堵：
--   1. 课题介绍原文是「梳理【全流程】数据标签体系」—— 全流程 = 申报→校验→核准→整改回传，
--      标签光挂企业挂不住；
--   2. 效能标签不挂企业，挂业务单据和登记机关（方案 §7.3 + 创新点④）。
--      赛题白纸黑字写了「效能短板」，而所有人都在给企业打标签；
--   3. 事前拦截类规则根本没有挂载对象 —— 申报未核准时统一社会信用代码尚未发放，
--      企业实体不存在。事前拦截的对象天然是申请件。
-- 触发时点分层（事前轻量 / 事后批量）同时也是「系统承载不足」的解法：
-- 不是靠堆机器，是靠让 99% 的办件只经过轻量路径。

CREATE TABLE authority (
    authority_id    TEXT        PRIMARY KEY,
    authority_name  TEXT        NOT NULL,
    province_code   CHAR(2)     NOT NULL,
    level           TEXT        NOT NULL CHECK (level IN ('省','市','县区'))
);

-- 登记代理人 —— 2025 新规把它变成监管抓手（《经营主体登记申请及代理行为管理办法》）。
-- 第六个挂载对象。★ filed=FALSE ⇒ 未按第七条通过系统表明代理身份 ⇒ R-SM-03 命中。
-- person_id：个人代理人对应的自然人，用于查「兼任登记联络员」（第五条第二款）。
CREATE TABLE reg_agent (
    agent_id        TEXT        PRIMARY KEY,
    agent_name_hash TEXT        NOT NULL,
    agent_type      TEXT        NOT NULL CHECK (agent_type IN ('个人','机构')),
    filed           BOOLEAN     NOT NULL DEFAULT FALSE,   -- 是否已备案（第七条）
    filed_at        DATE,
    person_id       TEXT        REFERENCES person(person_id)
);

CREATE TABLE application (
    app_id          TEXT        PRIMARY KEY,
    app_type        TEXT        NOT NULL CHECK (app_type IN ('设立','变更','注销')),
    authority_id    TEXT        NOT NULL REFERENCES authority(authority_id),
    -- 该申报由哪个登记代理人提交（可空：非代理申报）。R-SM-03/05 沿此关联代理行为。
    agent_id        TEXT        REFERENCES reg_agent(agent_id),
    province_code   CHAR(2)     NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL,
    decided_at      TIMESTAMPTZ,                -- 与 submitted_at 之差 = 办理时长（效能指标）
    status          TEXT        NOT NULL CHECK (status IN ('校验中','已核准','已退回')),
    return_reason   TEXT,
    return_count    INT         NOT NULL DEFAULT 0,   -- 被退回次数（效能标签挂这里，不挂企业）
    -- ★ 可空是本表的要害：核准前企业不存在，统一社会信用代码尚未发放。
    --   事前拦截规则作用于 payload，不作用于 enterprise。
    ent_id          CHAR(18)    REFERENCES enterprise(ent_id),
    -- 申报内容快照。校验发生在企业诞生之前，此时数据只存在于这里。
    payload         JSONB       NOT NULL,
    -- 核准必然产出企业；未核准必然没有。把流程语义变成数据库拒绝插入的墙。
    CONSTRAINT ck_approved_has_ent CHECK (
        (status = '已核准' AND ent_id IS NOT NULL AND decided_at IS NOT NULL)
     OR (status <> '已核准' AND ent_id IS NULL)
    )
);
CREATE INDEX idx_app_authority ON application (authority_id);
CREATE INDEX idx_app_status    ON application (status);
CREATE INDEX idx_app_submitted ON application (submitted_at);

-- 受益所有人 —— 派生事实，不是风险标签，所以落数据层不落标签库。
-- 《受益所有人信息管理办法》第2条：公司应当通过登记注册系统备案受益所有人。
-- 认定标准：持股/表决权 25% 以上的自然人（穿透计算，沿股权链累乘）。
--
-- ★ source 这一列是要害：
--   'declared' —— 企业申报的。矩阵关键发现②：9 省中疑似仅河南在设立环节采集此字段（★待核）。
--   'computed' —— 靠股权图谱穿透算出来的。
--   若发现②核实属实 → 其余 8 省 declared 恒为空 → 法定备案事项在登记环节根本无处可填
--   → 穿透不是技术炫技，是这项法定义务在这些省的【唯一实现路径】。
--   同时这也意味着「未备案受益所有人」这条规则在这些省会 100% 命中 ——
--   那不是 8 省的企业全在违法，是登记系统没有这个入口。
--   **这是监管堵点，不是风险。**（方案 §5.3：填不出判定逻辑的行 = 堵点）
CREATE TABLE beneficial_owner (
    ent_id          CHAR(18)    NOT NULL REFERENCES enterprise(ent_id),
    person_id       TEXT        NOT NULL REFERENCES person(person_id),
    ratio           NUMERIC(9,6) NOT NULL CHECK (ratio > 0 AND ratio <= 1),
    source          TEXT        NOT NULL CHECK (source IN ('declared','computed')),
    path            JSONB,                  -- 穿透路径（子图证据），declared 时为 NULL
    max_depth       INT,                    -- 穿透深度
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ent_id, person_id, source)
);
CREATE INDEX idx_bo_person ON beneficial_owner (person_id);

-- 关联企业集群（社区发现派生结果）—— 与 beneficial_owner 同为图算法派生事实，落数据层不落标签库。
-- Louvain 社区发现 SQL 根本做不了（§3.8：图不可替代的三件事之一），由 scripts/graph.py
-- 内存计算后写回。只持久化 size>=3 的关联集群（≥3 家才构成有分析意义的关联团伙）。
CREATE TABLE graph_community (
    ent_id          CHAR(18)    NOT NULL REFERENCES enterprise(ent_id),
    algo            TEXT        NOT NULL DEFAULT 'louvain',
    community_id    INT         NOT NULL,
    community_size  INT         NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ent_id, algo)
);
CREATE INDEX idx_community ON graph_community (algo, community_id);

-- ============================================================
-- 二、统计基线层
-- ============================================================

-- 统计异常类规则的阈值必须来自数据分位数，且必须可追溯。
-- 半年后问「当时 P99 是多少、样本量多大」，答案在这张表里，不在代码里。
CREATE TABLE stat_baseline (
    baseline_id     BIGSERIAL PRIMARY KEY,
    metric_name     TEXT        NOT NULL,       -- 如 addr_ent_count_p99
    scope_type      TEXT        NOT NULL,       -- province / national
    scope_value     TEXT        NOT NULL,       -- 如 32（江苏）
    quantile        NUMERIC(5,4) NOT NULL,      -- 0.99
    value           NUMERIC(18,4) NOT NULL,
    sample_size     INT         NOT NULL,       -- 样本量过小则阈值不可信
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_baseline_lookup ON stat_baseline (metric_name, scope_type, scope_value, computed_at DESC);

-- ============================================================
-- 三、标签库层（方案 §7.4 四张表）
-- ============================================================

CREATE TABLE rule (
    rule_id         TEXT        NOT NULL,
    rule_version    TEXT        NOT NULL,
    law_anchor      TEXT,                       -- 法条锚点。统计异常类无法源，允许 NULL
    rule_type       TEXT        NOT NULL CHECK (rule_type IN ('法定强制','规范性','统计异常','情报线索')),
    trigger_point   TEXT        NOT NULL CHECK (trigger_point IN ('事前拦截','事中','事后回溯')),
    disposal_level  TEXT        NOT NULL CHECK (disposal_level IN ('硬阻断','人工复核','仅打标')),
    target_entity   TEXT        NOT NULL,       -- 命中后标签挂在谁身上（企业/地址/自然人/…）
    tag_id          TEXT        NOT NULL,       -- 命中后产出哪个标签
    -- 规则即数据：logic 是一段 SELECT，引擎只负责执行它，不认识任何一条具体规则。
    -- 契约：必须返回 (entity_id TEXT, snapshot JSONB)。
    -- 可用占位符 %(名)s 引用 params 里的值；若有 baseline_sql，另可用 %(baseline_value)s。
    logic           TEXT        NOT NULL,
    -- 统计异常类规则专用：先算基线，再判定。
    -- 契约：返回 (scope_value TEXT, value NUMERIC, sample_size INT)。
    -- 阈值必须来自数据分位数而非代码常数 —— 基线算出后落 STAT_BASELINE，
    -- 由 EVIDENCE.baseline_id 指向，使「半年前这条为什么没报」可回答（当时基线不同）。
    baseline_sql    TEXT,
    baseline_metric TEXT,                       -- 基线指标名，如 addr_ent_count_p99
    CONSTRAINT ck_baseline_pair CHECK ((baseline_sql IS NULL) = (baseline_metric IS NULL)),
    -- 属地差异化参数的默认值。「统一规则中台 + 属地差异化参数」的落点：
    -- 同一条规则、同一份 logic，靠 params 适配各地（浙江冠省名 1000 万 vs 河南 100 万即此机制）。
    params          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- confidence 的冷启动先验。先验也是数据，不是代码里的字典。
    -- 一旦该规则有了复核回流，实测 precision 覆盖此值 —— 否则 confidence 只是
    -- rule_type 的冗余写法，不携带任何额外信息。
    confidence_prior NUMERIC(4,3) NOT NULL CHECK (confidence_prior > 0 AND confidence_prior <= 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, rule_version),
    -- 法定强制规则必须有法源。填不出法条锚点的，不配叫法定强制。
    CONSTRAINT ck_mandatory_needs_law CHECK (rule_type <> '法定强制' OR law_anchor IS NOT NULL),
    -- 法定强制 = 1.0 没有商量余地：等式判定与图约束是逻辑判定，不是概率。
    -- 把方案 §7.4 的这条主张变成数据库拒绝插入的墙，而不是文档里的一句话。
    CONSTRAINT ck_mandatory_conf_one CHECK (rule_type <> '法定强制' OR confidence_prior = 1.0)
);

-- 属地差异化参数覆盖。不覆盖时用 rule.params。
-- 这张表是对赛题「各地校验标准不一」的正面回答：不是全国一刀切，也不是各写各的规则，
-- 而是全国一份 logic + 属地一份参数。改参数不改规则，改规则不发版。
CREATE TABLE rule_param_override (
    rule_id         TEXT        NOT NULL,
    rule_version    TEXT        NOT NULL,
    scope_type      TEXT        NOT NULL CHECK (scope_type IN ('province','city','authority')),
    scope_value     TEXT        NOT NULL,
    params          JSONB       NOT NULL,
    basis           TEXT,                       -- 该属地参数的依据（地方规定出处）
    PRIMARY KEY (rule_id, rule_version, scope_type, scope_value),
    FOREIGN KEY (rule_id, rule_version) REFERENCES rule(rule_id, rule_version)
);

CREATE TABLE tag_dict (
    tag_id          TEXT        NOT NULL,
    tag_version     TEXT        NOT NULL,       -- 与 rule_version 分离：标签口径变更 ≠ 规则实现变更
    tag_name        TEXT        NOT NULL,
    entity_type     TEXT        NOT NULL CHECK (entity_type IN
                        ('企业','自然人','地址','登记代理人','业务单据','登记机关')),
    value_type      TEXT        NOT NULL CHECK (value_type IN ('布尔','枚举','数值')),
    action          TEXT        NOT NULL,       -- 命中后谁做什么。填不出就砍掉这个标签
    -- 依据类型：法条 / 统计基线 / 专题（专题范围标记，依据是专题定义+关键词表，非法条非统计）。
    basis_type      TEXT        NOT NULL CHECK (basis_type IN ('法条','统计基线','专题')),
    basis_ref       TEXT        NOT NULL,
    update_freq     TEXT,
    expiry_cond     TEXT,
    PRIMARY KEY (tag_id, tag_version)
);

CREATE TABLE evidence (
    evidence_id     BIGSERIAL   PRIMARY KEY,
    rule_id         TEXT        NOT NULL,
    rule_version    TEXT        NOT NULL,       -- 让系统能回答「半年前这条为什么没报」
    field_snapshot  JSONB       NOT NULL,       -- 命中时的字段值快照
    subgraph_ref    JSONB,                      -- 图谱子图（节点/边 ID 列表）
    law_anchor      TEXT,
    baseline_id     BIGINT      REFERENCES stat_baseline(baseline_id),  -- 统计类规则用到的阈值
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id, rule_version) REFERENCES rule(rule_id, rule_version)
);

CREATE TABLE tag_instance (
    instance_id     BIGSERIAL   PRIMARY KEY,
    tag_id          TEXT        NOT NULL,
    tag_version     TEXT        NOT NULL,
    entity_type     TEXT        NOT NULL,
    entity_id       TEXT        NOT NULL,       -- 多态：可指向企业/自然人/地址/机关
    value           TEXT        NOT NULL,
    -- SCD Type 2：绝不覆盖写。监管必须能回答「去年这家企业当时是什么状态」。
    -- 且宏观趋势无需另建统计表——趋势就是这张表按 valid_from 聚合。
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,                -- NULL = 当前有效
    -- confidence 不是模型分数，是规则类型决定的先验。法定强制规则恒为 1.0。
    confidence      NUMERIC(4,3) NOT NULL CHECK (confidence > 0 AND confidence <= 1),
    evidence_id     BIGINT      NOT NULL REFERENCES evidence(evidence_id),
    FOREIGN KEY (tag_id, tag_version) REFERENCES tag_dict(tag_id, tag_version)
);
CREATE INDEX idx_tag_inst_entity  ON tag_instance (entity_type, entity_id);
CREATE INDEX idx_tag_inst_current ON tag_instance (tag_id, valid_from) WHERE valid_to IS NULL;

-- ============================================================
-- 三之二、指标库（与标签库并列，同为唯一出口的一半）
-- ============================================================

-- 为什么需要这一层：方案 §7.2 定义了「标签/特征/指标」三个并列概念，
-- 但 §7.4 的数据模型只实现了标签，指标无处安放 —— 于是「新设企业趋势」这类
-- 业务态势统计（不是任何标签的聚合）被迫与「只读标签库」原则冲突。
-- 赛题目标2 原文本就是并列的：「构建数据标签【和】分析预警体系」；
-- 且赛题里宏观是「研判」、中观是「分析」，只有微观才是「预警」——
-- 宏观本就不该只看风险标签。
--
-- 修正后的原则：任何一个口径只允许被计算一次，结果物化为带版本、带时点的资产；
-- 下游只消费资产，不重新计算。口径打架的病根是「重复计算」，不是「读了原始数据」。
--   风险口径 → TAG_INSTANCE
--   统计口径 → METRIC_INSTANCE
--   阈值基线 → STAT_BASELINE
-- 三者合起来才是唯一出口。

CREATE TABLE metric_dict (
    metric_id       TEXT        NOT NULL,
    metric_version  TEXT        NOT NULL,       -- 口径版本。口径变了必须升版，不可原地改写
    metric_name     TEXT        NOT NULL,
    -- ★ 这个字段是本层的关键：让「这个数是从标签算的还是从原始数据算的」
    --   成为显式、可审计的事实，而不是一个含糊的架构争议。
    source_type     TEXT        NOT NULL CHECK (source_type IN ('tag_agg','raw_agg')),
    lineage_ref     TEXT        NOT NULL,       -- tag_agg → 指向 tag_id；raw_agg → 指向计算逻辑
    grain           TEXT        NOT NULL CHECK (grain IN ('宏观','中观','微观')),
    unit            TEXT,
    definition      TEXT        NOT NULL,       -- 口径的自然语言定义。答辩时被追问「这个数怎么来的」就看它
    -- 指标即数据，与规则同构：引擎只做解释器。
    -- 契约：返回 (scope_value TEXT, value NUMERIC, sample_size INT)。
    logic           TEXT        NOT NULL,
    scope_type      TEXT        NOT NULL,
    PRIMARY KEY (metric_id, metric_version)
);

CREATE TABLE metric_instance (
    minst_id        BIGSERIAL   PRIMARY KEY,
    metric_id       TEXT        NOT NULL,
    metric_version  TEXT        NOT NULL,
    scope_type      TEXT        NOT NULL,       -- national / province / industry / authority
    scope_value     TEXT        NOT NULL,
    value           NUMERIC(20,6) NOT NULL,
    sample_size     INT,
    -- 与 TAG_INSTANCE 同构：不覆盖写。宏观趋势 = 这张表按 valid_from 聚合，无需另建趋势表。
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (metric_id, metric_version) REFERENCES metric_dict(metric_id, metric_version)
);
CREATE INDEX idx_metric_lookup  ON metric_instance (metric_id, scope_type, scope_value, valid_from DESC);
CREATE INDEX idx_metric_current ON metric_instance (metric_id, scope_value) WHERE valid_to IS NULL;

-- ============================================================
-- 二之二、阈值校准
-- ============================================================

-- 为什么要单独一张表：阈值不是一个数，是一个【带依据的主张】。
--
-- ★ 实测推翻了方案那条规矩「阈值必须来自数据分位数，不能拍脑袋」：
--   1. P99 里的 99 本身就是拍的 —— 分位数只是把「拍绝对数」换成「拍百分比」；
--   2. 分位数保证恒定告警率（P99 永远报 1%），与真实风险无关：
--      全省干净时照样报 1%（全误报），全省烂透时也只报 1%（大量漏报）；
--   3. 更要命的是零膨胀分布上分位数直接退化 —— 实测「30日新增」的
--      P90=P95=P99=0（415/419 个地址近 30 天零新增），按分位数定阈值 precision 掉到 0.5，
--      反倒是「拍的常数 10」precision=1.0。有依据的错了，没依据的对了。
--
-- 阈值确定分三层，取决于手上有什么：
--   复核数据校准 —— 扫描候选值，选满足处置级别 precision 门槛的最小值（recall 最大）
--   告警负荷倒推 —— 「全省一天能复核 N 条 → 阈值定在产出 N 条的位置」。
--                    依据是运营的不是统计的，但能说出口，且是真实监管系统的做法。
--   未校准初值   —— 承认定不出。★ 此时该规则强制降级为「仅打标」：
--                    不知道一个阈值准不准，就不配让人为它跑腿，更不配拿它阻断企业开办。
CREATE TABLE threshold_calibration (
    calib_id            BIGSERIAL   PRIMARY KEY,
    rule_id             TEXT        NOT NULL,
    rule_version        TEXT        NOT NULL,
    param_name          TEXT        NOT NULL,   -- 对应 rule.params 里的键
    value               NUMERIC     NOT NULL,
    basis               TEXT        NOT NULL CHECK (basis IN
                            ('未校准初值','告警负荷倒推','复核数据校准')),
    -- 人话说明这个数怎么来的。答辩被问「这个 10 哪来的」，念这一列。
    -- NOT NULL：说不出依据的阈值不许入库。
    derivation          TEXT        NOT NULL,
    target_precision    NUMERIC(4,3),
    achieved_precision  NUMERIC(4,3),
    achieved_recall     NUMERIC(4,3),
    review_sample_size  INT,
    -- ★ 平台宽度 = 数据对阈值的约束力。平台越宽，说明数据越定不住阈值。
    --   实测合成数据上 5~45 全部 precision=1.0 —— 9 倍宽的平台，
    --   等于数据根本没约束住阈值，「校准」只是运气。诚实地把它记下来。
    plateau_low         NUMERIC,
    plateau_high        NUMERIC,
    calibrated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rule_id, rule_version) REFERENCES rule(rule_id, rule_version)
);
CREATE INDEX idx_calib_lookup ON threshold_calibration
    (rule_id, rule_version, param_name, calibrated_at DESC);

-- ============================================================
-- 三之三、复核回流（方案的灵魂箭头：没有它只是报警器）
-- ============================================================

-- 人工复核结果回流。这张表让系统从「报警器」变成「会自我进化的规则治理系统」：
--   1. confidence 冷启动用 rule.confidence_prior，有回流后用实测 precision 覆盖；
--   2. 误报不再是垃圾，而是校准 confidence 的标注数据；
--   3. 「表述不规范」类误报可进一步沉淀为目录缺口建议（方案 §13.2 第6步）。
CREATE TABLE review (
    review_id       BIGSERIAL   PRIMARY KEY,
    instance_id     BIGINT      NOT NULL REFERENCES tag_instance(instance_id),
    verdict         TEXT        NOT NULL CHECK (verdict IN ('成立','误报')),
    reviewer        TEXT        NOT NULL,
    reviewed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    note            TEXT,
    -- 误报时可标注根因：数据质量问题 / 规则缺陷 / 目录缺口 / 合法情形未排除
    fp_reason       TEXT,
    UNIQUE (instance_id)
);
CREATE INDEX idx_review_verdict ON review (verdict);

-- 每条规则的实测 precision —— confidence 的来源，也是「阻断级须 >0.99」的判据。
CREATE VIEW rule_measured_precision AS
SELECT ev.rule_id, ev.rule_version,
       COUNT(*)                                        AS reviewed,
       COUNT(*) FILTER (WHERE rv.verdict = '成立')     AS upheld,
       ROUND(COUNT(*) FILTER (WHERE rv.verdict = '成立')::numeric
             / NULLIF(COUNT(*), 0), 4)                 AS precision
FROM review rv
JOIN tag_instance ti ON ti.instance_id = rv.instance_id
JOIN evidence ev     ON ev.evidence_id = ti.evidence_id
GROUP BY ev.rule_id, ev.rule_version;

-- ============================================================
-- 三之四、企业风险画像（微观层 · 三级分析的「预警」粒度）
-- ============================================================
-- 一个 ent_id → 一份完整 JSON 画像。前端 Demo「证据链那一屏」的现成数据接口：
--   SELECT profile FROM v_enterprise_profile WHERE ent_id = '...';
-- ★ 全息：不只企业自身标签，还沿关系汇入【法定代表人/住所/变更单据】的风险 ——
--   一家企业的合规风险散落在多个挂载对象上，画像负责把它们收拢到一处。
-- ★ 证据链即解释：每条标签都带 field_snapshot + law_anchor，倒着念就是「因某法条、某字段值，故命中」，
--   无一字由 LLM 生成（explanation-by-construction）。
CREATE VIEW v_enterprise_profile AS
SELECT e.ent_id,
       jsonb_build_object(
         '企业', jsonb_build_object(
            '统一社会信用代码', e.ent_id, '名称', e.ent_name, '状态', e.status,
            '注册资本', e.reg_capital, '实缴额', e.paid_capital,
            '成立日期', e.estab_date, '住所', a.raw_address, '登记机关', e.reg_authority),
         '自身风险标签', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                     '标签', td.tag_name, '类型', r.rule_type, '置信度', ti.confidence,
                     '处置', r.disposal_level, '法条锚点', ev.law_anchor,
                     '证据', ev.field_snapshot, '命中时间', ti.valid_from)
                   ORDER BY ti.confidence DESC)
            FROM tag_instance ti
            JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
            JOIN evidence ev ON ev.evidence_id = ti.evidence_id
            JOIN rule r ON r.rule_id = ev.rule_id AND r.rule_version = ev.rule_version
            WHERE ti.entity_type = '企业' AND ti.entity_id = e.ent_id
              AND ti.valid_to IS NULL AND td.basis_type = '法条'), '[]'::jsonb),
         '关联风险', COALESCE((
            SELECT jsonb_agg(x.item) FROM (
              SELECT jsonb_build_object('对象', '法定代表人', '标签', td.tag_name,
                       '类型', r.rule_type, '法条锚点', ev.law_anchor, '证据', ev.field_snapshot) AS item
              FROM position_hold ph
              JOIN tag_instance ti ON ti.entity_type = '自然人' AND ti.entity_id = ph.person_id AND ti.valid_to IS NULL
              JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
              JOIN evidence ev ON ev.evidence_id = ti.evidence_id
              JOIN rule r ON r.rule_id = ev.rule_id AND r.rule_version = ev.rule_version
              WHERE ph.ent_id = e.ent_id AND ph.post_type = '法定代表人'
              UNION ALL
              SELECT jsonb_build_object('对象', '住所', '标签', td.tag_name,
                       '类型', r.rule_type, '法条锚点', ev.law_anchor, '证据', ev.field_snapshot)
              FROM tag_instance ti
              JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
              JOIN evidence ev ON ev.evidence_id = ti.evidence_id
              JOIN rule r ON r.rule_id = ev.rule_id AND r.rule_version = ev.rule_version
              WHERE ti.entity_type = '地址' AND ti.entity_id = e.address_id AND ti.valid_to IS NULL
              UNION ALL
              SELECT jsonb_build_object('对象', '变更单据', '单据', app.app_id, '标签', td.tag_name,
                       '类型', r.rule_type, '法条锚点', ev.law_anchor, '证据', ev.field_snapshot)
              FROM application app
              JOIN tag_instance ti ON ti.entity_type = '业务单据' AND ti.entity_id = app.app_id AND ti.valid_to IS NULL
              JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
              JOIN evidence ev ON ev.evidence_id = ti.evidence_id
              JOIN rule r ON r.rule_id = ev.rule_id AND r.rule_version = ev.rule_version
              WHERE app.ent_id = e.ent_id
            ) x), '[]'::jsonb),
         '专题', COALESCE((
            SELECT jsonb_agg(td.tag_name)
            FROM tag_instance ti
            JOIN tag_dict td ON td.tag_id = ti.tag_id AND td.tag_version = ti.tag_version
            WHERE ti.entity_id = e.ent_id AND td.basis_type = '专题' AND ti.valid_to IS NULL), '[]'::jsonb),
         '受益所有人穿透', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                     '自然人', bo.person_id, '持股比例', bo.ratio,
                     '穿透深度', bo.max_depth, '穿透路径', bo.path))
            FROM beneficial_owner bo WHERE bo.ent_id = e.ent_id), '[]'::jsonb)
       ) AS profile
FROM enterprise e
JOIN address a ON a.address_id = e.address_id;

-- ============================================================
-- 四、评测层（ground truth）
-- ============================================================

-- 合成数据注入日志 = ground truth。
-- 刻意与业务表物理分离：规则引擎的输入里绝不能出现任何注入痕迹，
-- 否则就是拿答案去算答案，P/R 全部失效。
CREATE TABLE injection_log (
    injection_id    BIGSERIAL   PRIMARY KEY,
    entity_type     TEXT        NOT NULL,
    entity_id       TEXT        NOT NULL,
    rule_id         TEXT        NOT NULL,       -- 本次注入意图违反的规则
    injection_params JSONB      NOT NULL,       -- 注入参数，用于复现
    is_hard_negative BOOLEAN    NOT NULL DEFAULT FALSE,  -- 难负例：接近阈值但合规
    is_label_noise   BOOLEAN    NOT NULL DEFAULT FALSE,  -- 人为标注噪声（3%-5%）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_injection_entity ON injection_log (entity_type, entity_id);

COMMIT;
