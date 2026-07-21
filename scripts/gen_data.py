"""合成数据生成器 v0.1 —— 1000 家江苏企业 + ground truth

设计要点：
1. 地址分布是唯一需要精心设计的部分。R-ZS-02 是三条规则里唯一的「统计异常」类，
   它的阈值来自数据分位数而非法条——合成的地址分布不像真的，P99 就是假的。
   R-CZ-01 / R-BG-05 是法定强制类，正确性来自法条，数据怎么造都不改变对错。

2. 地址分三类：
   - 正常：幂律长尾（多数 1 家，少数几家）——真实世界的写字楼/商铺
   - 合法集群注册（难负例）：同址几十家，但成立日期在 3 年内缓慢累积。
     江苏有集群注册政策，一址多照在此合法。
   - 虚假批量注册（正例）：同址几十家，成立日期集中在 30 天内暴增。

   ★ 难负例与正例在「同址数」上几乎不可分，只有加时间窗才分得开。
     这是用来检验规则逻辑本身是否成立的，不只是检验代码能不能跑。

3. ground truth 一律写 injection_log，与业务表物理隔离。

用法：.venv/bin/python scripts/gen_data.py
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal

import psycopg
from faker import Faker

SEED = 20260717
DSN = "postgresql://postgres:x@localhost:55432/reg"

PROVINCE = "32"           # 江苏
DIVISIONS = ["320102", "320104", "320105", "320106", "320111", "320113", "320114"]
TODAY = date(2026, 7, 17)
HISTORY_DAYS = 3 * 365    # 正常企业成立日期回溯窗口
BURST_DAYS = 30           # 虚假批量注册的暴增窗口

N_TOTAL = 1000
N_CLUSTER_ADDR = 2        # 合法集群注册地址数（难负例）
N_CLUSTER_ENT = 50        # 每个集群注册地址挂多少家
N_FAKE_ADDR = 2           # 虚假批量注册地址数（正例）
N_FAKE_ENT = 50           # 每个虚假地址挂多少家

N_INJECT_CZ01 = 30        # 出资不符注入数
N_HARDNEG_CZ01 = 20       # 除不尽出资（合规但易被浮点误判）
N_INJECT_CYCLE = 5        # 股权环注入数
N_HARDNEG_DIAMOND = 3     # 菱形结构（多路径但无环）

CORP_SHAREHOLDER_RATE = 0.18   # 多少比例的企业有企业股东（穿透的地基）
N_HOLDING_CHAIN = 8       # 控股链条数（穿透的素材）
CHAIN_DEPTH = 3           # 每条链的层数：自然人 → A → B → C
N_PRO_LEGAL_PERSON = 4    # 职业法人（正例）
PRO_LEGAL_EACH = 12       # 每个职业法人任多少家法代
N_HARDNEG_LEGAL = 15      # 难负例：任 2~3 家法代，合法

# ---- 本轮新增四条规则的注入参数（企业级字段 + 失信信息）----
FIVE_YEARS_DAYS = 5 * 365
N_INJECT_CZ02 = 15        # R-CZ-02 出资期限超五年（正例）：缴付期限 > 成立日+5年
N_HARDNEG_CZ02 = 10       # 难负例：期限恰在五年内（边界，不应报）
N_INJECT_CZ04 = 15        # R-CZ-04 出资备案不全（正例）：出资方式/期限为空
N_HARDNEG_CZ04 = 10       # 对照：备案项完整（不应报）
N_INJECT_CZ05 = 12        # R-CZ-05 实缴制行业未实缴（正例）：行业∈名录 且 实缴=0
N_HARDNEG_CZ05 = 8        # 难负例：实缴制行业但已足额实缴（不应报）
N_INJECT_SM06 = 10        # R-SM-06 失信人员违规任职（正例）：失信人任法定代表人
N_HARDNEG_SM06 = 8        # 难负例：失信人任监事（非法代，不应报）

# 实缴登记制行业名录（国发〔2014〕7号 保留实缴的行业）。GB/T 4754 大类：
#   J66 货币金融服务（银行）· J67 资本市场服务（证券/期货）· J68 保险业
PAID_IN_INDUSTRIES = ["J66", "J67", "J68"]
# 非实缴制常见行业（认缴制默认，实缴额可为 0）
NORMAL_INDUSTRIES = ["I65", "F51", "F52", "M73", "R87", "G59", "C13"]

# ---- 经营范围：规范表述目录（合成，真实目录《经营范围规范表述目录》待获取）----
# is_licensed=True 的项须提交批准文件（《条例》第14条），否则 R-JY-01 命中。
BIZ_CATALOG = [
    # (item_id, item_name, industry_code, is_licensed)
    ("BS001", "技术服务、技术开发、技术咨询", "M74", False),
    ("BS002", "软件开发", "I65", False),
    ("BS003", "电子产品销售", "F52", False),
    ("BS004", "服装服饰零售", "F52", False),
    ("BS005", "企业管理咨询", "M73", False),
    ("BS006", "广告设计、代理、制作、发布", "L72", False),
    ("BS007", "家居用品销售", "F52", False),
    ("BS008", "计算机系统服务", "I65", False),
    ("BS009", "供应链管理服务", "G59", False),
    ("BS010", "会议及展览服务", "L72", False),
    ("BS101", "餐饮服务", "H62", True),          # 食品经营许可
    ("BS102", "危险化学品经营", "F51", True),    # 危化经营许可
    ("BS103", "药品零售", "F52", True),          # 药品经营许可
    ("BS104", "劳务派遣服务", "L72", True),      # 劳务派遣经营许可
    ("BS105", "食品销售", "F52", True),          # 食品经营许可
    ("BS011", "互联网直播营销服务", "L72", False),  # 直播电商专题（R-JY-07 圈定）；不进默认池
]
# 直播电商专题关键词（圈定用）。BS011 是其规范表述，另注入含关键词的原文表述。
LIVE_TXT = ["网络直播带货", "直播电商综合服务", "互联网直播营销"]
N_INJECT_JY07 = 14        # R-JY-07 直播电商专题标记（圈定，非风险；无难负例）
LIVE_LICENSE_GAP = 5      # 其中几家直播带货涉食品销售但无食品经营许可 → 同时命中 R-JY-01
                          # （制造 T-JY-07 ∩ T-JY-01 交叠，让专题画像的「许可缺失率」有真信号）
# R-JY-03 正例用的「目录外表述」（新业态，规范目录尚未收录 → 目录缺口候选）
OFF_CATALOG = ["元宇宙场景搭建", "AI大模型训练服务", "碳积分咨询", "预制菜研发",
               "宠物殡葬服务", "剧本杀策划运营"]

N_INJECT_JY01 = 14        # R-JY-01 许可项无批准文件（正例）
N_HARDNEG_JY01 = 10       # 难负例：许可项有批准文件（合规）
N_INJECT_JY03 = 16        # R-JY-03 表述不规范/目录缺口（正例）：item_id 为空
N_HARDNEG_JY03 = 10       # 难负例：表述在规范目录内（合规）

# ---- 名称与生命周期批次（R-MC-01/02 事前拦截 · R-ZX-01 事后回溯）----
# 禁限用词表（合成占位；真实清单见《经营主体登记文书规范2026年版》，完整版待获取）。
FORBIDDEN_WORDS = ["虚拟货币", "加密货币", "稳定币", "数字藏品", "元宇宙币",
                   "区块链金融", "P2P网贷", "RWA数字资产"]
# 难负例词：含禁用词的子串但非完整禁用词，测子串匹配特异性（不应命中）
MC02_HARDNEG = ["虚拟现实", "货币经纪", "数字科技", "区块链技术"]
N_INJECT_MC01 = 6         # R-MC-01 名称缺失（正例）
N_INJECT_MC02 = 10        # R-MC-02 名称含禁限用词（正例）
N_HARDNEG_MC02 = 6        # 难负例：含子串但非完整禁用词
N_INJECT_ZX01 = 12        # R-ZX-01 应注销未注销（正例）：status=吊销
N_HARDNEG_ZX01 = 8        # 难负例：status=注销（已注销，合规）

# ---- 变更/注销申报流（R-BG-01 变更逾期 · R-ZX-04 注销后仍有变更）----
N_CHANGE = 40             # 变更申请件总数（已核准）
N_INJECT_BG01 = 12        # R-BG-01 变更登记逾期（正例）：申请 - 决议 > 30 日
N_HARDNEG_BG01 = 10       # 难负例：30 日内申请（合规）
N_INJECT_ZX04 = 5         # R-ZX-04 注销后仍有变更（正例）：注销 8 家里取 5 家注入

# ---- 登记代理人（第 6 个挂载对象；《经营主体登记申请及代理行为管理办法》）----
N_AGENT = 30              # 登记代理人总数
N_INJECT_SM03 = 12        # R-SM-03 代理人未备案（正例）：filed=FALSE
N_INJECT_SM04 = 8         # R-SM-04 兼任登记联络员（正例）：代理人自然人兼任非自设主体联络员
N_HARDNEG_SM04 = 5        # 难负例：自设主体的联络员（第五条第二款「自设除外」）

rnd = random.Random(SEED)
fake = Faker("zh_CN")
Faker.seed(SEED)

ROADS = ["中山路", "珠江路", "汉中路", "太平南路", "新街口", "玄武大道", "龙蟠路",
         "北京西路", "广州路", "上海路", "洪武路", "健康路", "水西门大街"]


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:32]


PEOPLE: dict[str, str] = {}


def new_person_global() -> str:
    """自然人：证件号与姓名一律哈希，原文不落库。"""
    nm = fake.name()
    pid = h(fake.ssn() + nm)
    PEOPLE[pid] = h(nm)
    return pid


@dataclass
class Addr:
    address_id: str
    raw: str
    division: str
    road: str
    house_no: str
    room_no: str
    kind: str                      # normal / cluster_legal / fake_burst


@dataclass
class Ent:
    ent_id: str
    name: str
    addr: Addr
    reg_capital: Decimal
    estab: date
    shareholders: list = field(default_factory=list)   # (type, id, amount)
    # ---- 本轮新增：企业级字段。放这里而非股东三元组，避免牵动十几处解包。----
    # 出资方式/期限是【每股东】字段，但合成期对同一企业统一取值，load 时应用到其全部 investment 行。
    industry_code: str = "I65"                # 主行业码（GB/T 4754）
    paid_capital: Decimal = Decimal("0")      # 实缴额（万元），认缴制默认 0
    contrib_method: str | None = "货币出资"   # 出资方式（法定备案项）
    contrib_deadline: date | None = None      # 出资期限（法定备案项），new_ent 中按成立日填
    status: str = "存续"                      # 存续 / 吊销 / 注销（R-ZX-01 用）


def make_addr(kind: str, i: int) -> Addr:
    div = rnd.choice(DIVISIONS)
    road = rnd.choice(ROADS)
    house = f"{rnd.randint(1, 300)}号"
    room = f"{rnd.randint(1, 30)}{rnd.randint(1, 20):02d}室"
    aid = f"A{PROVINCE}-{i:05d}"
    raw = f"江苏省南京市{road}{house}{room}"
    return Addr(aid, raw, div, road, house, room, kind)


def reg_capital_sample() -> Decimal:
    """注册资本分布：真实世界是长尾且强烈聚集在整数档位。
    ★ 该分布形状为假设，未经真实数据标定（见方案 §11 负面结果）。"""
    buckets = [10, 50, 100, 200, 300, 500, 1000, 2000, 5000]
    weights = [18, 22, 25, 10, 8, 8, 5, 3, 1]
    base = rnd.choices(buckets, weights=weights)[0]
    return Decimal(base).quantize(Decimal("0.0001"))


def split_capital(total: Decimal, n: int) -> list[Decimal]:
    """把注册资本精确拆成 n 份，和必须严格等于 total。"""
    if n == 1:
        return [total]
    cents = int(total * 10000)
    cuts = sorted(rnd.sample(range(1, cents), n - 1)) if cents > n else list(range(1, n))
    parts, prev = [], 0
    for c in cuts:
        parts.append(c - prev)
        prev = c
    parts.append(cents - prev)
    out = [Decimal(p) / Decimal(10000) for p in parts]
    assert sum(out) == total, f"拆分不精确: {sum(out)} != {total}"
    return out


def build() -> tuple[list[Addr], list[Ent], list[tuple]]:
    addrs: list[Ent] = []
    ents: list[Ent] = []
    gt: list[tuple] = []          # (entity_type, entity_id, rule_id, params, hard_neg, noise)
    aidx = 0

    # ---- 1. 地址：三类 ----
    addr_pool: list[Addr] = []

    n_special = (N_CLUSTER_ADDR * N_CLUSTER_ENT) + (N_FAKE_ADDR * N_FAKE_ENT)
    n_normal_ent = N_TOTAL - n_special

    # 正常地址：幂律长尾，直到容纳 n_normal_ent 家
    normal_slots: list[tuple[Addr, int]] = []
    filled = 0
    while filled < n_normal_ent:
        aidx += 1
        a = make_addr("normal", aidx)
        k = min(int(rnd.paretovariate(1.6)), 12)      # 多数 1，尾部最多 12
        k = min(k, n_normal_ent - filled)
        normal_slots.append((a, k))
        addr_pool.append(a)
        filled += k

    cluster_addrs = []
    for _ in range(N_CLUSTER_ADDR):
        aidx += 1
        a = make_addr("cluster_legal", aidx)
        cluster_addrs.append(a)
        addr_pool.append(a)

    fake_addrs = []
    for _ in range(N_FAKE_ADDR):
        aidx += 1
        a = make_addr("fake_burst", aidx)
        fake_addrs.append(a)
        addr_pool.append(a)

    # ---- 2. 企业 ----
    seq = 0

    def new_ent(a: Addr, estab: date) -> Ent:
        nonlocal seq
        seq += 1
        eid = f"91{a.division}{seq:08d}X"[:18].ljust(18, "X")
        name = f"南京{fake.company_prefix()}{rnd.choice(['科技','贸易','咨询','文化','实业','网络'])}有限公司{seq}"
        e = Ent(eid, name, a, reg_capital_sample(), estab)
        # 默认：非实缴行业、实缴 0、备案项齐全、出资期限在成立日后五年内（合规基线）
        e.industry_code = rnd.choice(NORMAL_INDUSTRIES)
        e.contrib_method = "货币出资"
        e.contrib_deadline = estab + timedelta(days=rnd.randint(180, FIVE_YEARS_DAYS - 120))
        return e

    for a, k in normal_slots:
        for _ in range(k):
            estab = TODAY - timedelta(days=rnd.randint(30, HISTORY_DAYS))
            ents.append(new_ent(a, estab))

    # 合法集群注册：3 年内缓慢累积 —— 同址数很高，但 30 日新增很低。
    # ★ 起点必须是 0 而不是 60：真实的集群注册地址是持续涓流的，近 30 天不可能一家都没有。
    #   若从 60 起，等于人为保证近 30 日新增恒为 0，难负例被造得过于好分，precision 会虚高。
    for a in cluster_addrs:
        for _ in range(N_CLUSTER_ENT):
            estab = TODAY - timedelta(days=rnd.randint(0, HISTORY_DAYS))
            e = new_ent(a, estab)
            ents.append(e)
            gt.append(("地址", a.address_id, "R-ZS-02", {"kind": "cluster_legal"}, True, False))

    # 虚假批量注册：30 天内暴增
    for a in fake_addrs:
        for _ in range(N_FAKE_ENT):
            estab = TODAY - timedelta(days=rnd.randint(0, BURST_DAYS - 1))
            e = new_ent(a, estab)
            ents.append(e)
            gt.append(("地址", a.address_id, "R-ZS-02", {"kind": "fake_burst"}, False, False))

    rnd.shuffle(ents)

    # ---- 3. 股东 ----
    people: dict[str, str] = PEOPLE

    def new_person() -> str:
        return new_person_global()

    for e in ents:
        n = rnd.choices([1, 2, 3, 4], weights=[45, 30, 18, 7])[0]
        for amt in split_capital(e.reg_capital, n):
            e.shareholders.append(("NATURAL", new_person(), amt))

    # ---- 3b. 企业股东（穿透的地基）----
    # ★ 不造这个，图就是白上的：首版只有 41/1903 条企业投企业边（2.2%），全是为造环硬塞的，
    #   结果 1359 条受益所有人里仅 7 条需要穿透 —— 99.5% 用 JOIN 就能算出来，图毫无价值。
    #   真实世界企业股东占比远高于此。
    # 做法：**替换**而非新增一个股东槽位，保持认缴合计 = 注册资本，不污染 R-CZ-01 的评测。
    # 防环：只允许序号小的投资序号大的（构成 DAG），保证不会意外造出环 ——
    #      环必须是刻意注入的，否则 R-BG-05 的 ground truth 就不成立了。
    for idx, e in enumerate(ents):
        if idx == 0 or rnd.random() >= CORP_SHAREHOLDER_RATE:
            continue
        if not e.shareholders:
            continue
        parent = ents[rnd.randrange(0, idx)]          # 只从前面选 → DAG
        slot = rnd.randrange(len(e.shareholders))
        _, _, amt = e.shareholders[slot]
        e.shareholders[slot] = ("ENTERPRISE", parent.ent_id, amt)

    normal_ents = [e for e in ents if e.addr.kind == "normal"]

    # 出资不符（正例）
    for e in rnd.sample(normal_ents, N_INJECT_CZ01):
        t, pid, amt = e.shareholders[0]
        delta = (e.reg_capital * Decimal(rnd.randint(5, 50)) / Decimal(100)).quantize(Decimal("0.0001"))
        delta = delta if rnd.random() < 0.5 else -delta
        new_amt = amt + delta
        if new_amt <= 0:
            new_amt = amt + abs(delta)
        e.shareholders[0] = (t, pid, new_amt)
        gt.append(("企业", e.ent_id, "R-CZ-01",
                   {"orig": str(amt), "perturbed": str(new_amt)}, False, False))

    # 除不尽出资（难负例）：合规，但用 float 会被误判
    pool = [e for e in normal_ents if not any(g[1] == e.ent_id for g in gt)]
    for e in rnd.sample(pool, N_HARDNEG_CZ01):
        third = (e.reg_capital / 3).quantize(Decimal("0.0001"))
        remainder = e.reg_capital - third * 2
        e.shareholders = [("NATURAL", new_person(), third),
                          ("NATURAL", new_person(), third),
                          ("NATURAL", new_person(), remainder)]
        assert sum(a for _, _, a in e.shareholders) == e.reg_capital
        gt.append(("企业", e.ent_id, "R-CZ-01",
                   {"note": "除不尽出资，合规", "parts": [str(third), str(third), str(remainder)]},
                   True, False))

    # 股权环（正例）
    used = {g[1] for g in gt}
    avail = [e for e in normal_ents if e.ent_id not in used]
    ci = 0
    for _ in range(N_INJECT_CYCLE):
        ln = rnd.choice([2, 2, 3, 3, 4])
        ring = avail[ci:ci + ln]
        ci += ln
        for i, e in enumerate(ring):
            nxt = ring[(i + 1) % ln]
            amt = (e.reg_capital * Decimal("0.3")).quantize(Decimal("0.0001"))
            e.shareholders.append(("ENTERPRISE", nxt.ent_id, amt))
            # 环边额外注资会破坏 R-CZ-01 等式，同步调高注册资本以免污染 CZ-01 的评测
            e.reg_capital += amt
        for e in ring:
            gt.append(("企业", e.ent_id, "R-BG-05",
                       {"ring_len": ln, "ring": [x.ent_id for x in ring]}, False, False))

    # 菱形（难负例）：A→B, A→C, B→D, C→D —— 有多条路径但无环
    for _ in range(N_HARDNEG_DIAMOND):
        a, b, c, d = avail[ci:ci + 4]
        ci += 4
        for src, dst in [(a, b), (a, c), (b, d), (c, d)]:
            amt = (dst.reg_capital * Decimal("0.2")).quantize(Decimal("0.0001"))
            dst.shareholders.append(("ENTERPRISE", src.ent_id, amt))
            dst.reg_capital += amt
        for e in (a, b, c, d):
            gt.append(("企业", e.ent_id, "R-BG-05", {"note": "菱形，多路径无环"}, True, False))

    # 控股链：自然人 → A → B → C，3 层。
    # ★ 没有多层股权，穿透就没东西可穿 —— 受益所有人是沿链累乘算出来的。
    #   《受益所有人信息管理办法》：持股 25% 以上的自然人即为受益所有人。
    #   造链时刻意让部分链的累乘落在 25% 两侧，使穿透判定有区分度。
    for _ in range(N_HOLDING_CHAIN):
        chain = avail[ci:ci + CHAIN_DEPTH]
        ci += CHAIN_DEPTH
        # 链顶那个自然人：给它一个明确的高持股，让穿透结果可预期
        top_person = new_person()
        top = chain[0]
        top.shareholders = [("NATURAL", top_person, top.reg_capital)]   # 100% 持有链顶
        for i in range(len(chain) - 1):
            parent, child = chain[i], chain[i + 1]
            ratio = rnd.choice([Decimal("0.7"), Decimal("0.6"), Decimal("0.4"), Decimal("0.3")])
            amt = (child.reg_capital * ratio).quantize(Decimal("0.0001"))
            child.shareholders.append(("ENTERPRISE", parent.ent_id, amt))
            child.reg_capital += amt
        gt.append(("自然人", top_person, "GRAPH-BO",
                   {"chain": [e.ent_id for e in chain], "note": "控股链顶端自然人"}, False, False))

    # ---- R-CZ-02 / R-CZ-04 / R-CZ-05 注入（企业级字段，互不相交，且与上面的注入分离）----
    # 这些注入只改 contrib_*/industry_code/paid_capital，不动出资额与股权边，
    # 因此不污染 R-CZ-01（等式）与 R-BG-05（环）的评测。
    used2 = {g[1] for g in gt}
    pool2 = [e for e in normal_ents if e.ent_id not in used2]
    rnd.shuffle(pool2)
    p = 0

    # R-CZ-02 出资期限超五年（正例）：最晚出资期限 > 成立日 + 5 年
    for e in pool2[p:p + N_INJECT_CZ02]:
        e.contrib_deadline = e.estab + timedelta(days=FIVE_YEARS_DAYS + rnd.randint(120, 1000))
        gt.append(("企业", e.ent_id, "R-CZ-02",
                   {"成立": str(e.estab), "缴付期限": str(e.contrib_deadline)}, False, False))
    p += N_INJECT_CZ02
    # R-CZ-02 难负例：期限恰在五年内 —— 边界，合规，不应报
    for e in pool2[p:p + N_HARDNEG_CZ02]:
        e.contrib_deadline = e.estab + timedelta(days=FIVE_YEARS_DAYS - rnd.randint(60, 150))
        gt.append(("企业", e.ent_id, "R-CZ-02",
                   {"note": "出资期限恰在五年内，合规", "缴付期限": str(e.contrib_deadline)}, True, False))
    p += N_HARDNEG_CZ02

    # R-CZ-04 出资备案不全（正例）：出资方式 或 出资期限 为空
    for e in pool2[p:p + N_INJECT_CZ04]:
        if rnd.random() < 0.5:
            e.contrib_method = None
        else:
            e.contrib_deadline = None
        gt.append(("企业", e.ent_id, "R-CZ-04",
                   {"note": "出资方式或期限为空（法定备案项缺失）"}, False, False))
    p += N_INJECT_CZ04
    # R-CZ-04 对照：备案项完整（保持默认），显式记 GT 纳入评测 —— 不应报
    for e in pool2[p:p + N_HARDNEG_CZ04]:
        gt.append(("企业", e.ent_id, "R-CZ-04",
                   {"note": "出资方式与期限均已填，备案完整，合规"}, True, False))
    p += N_HARDNEG_CZ04

    # R-CZ-05 实缴制行业未实缴（正例）：行业∈名录 且 实缴额=0
    for e in pool2[p:p + N_INJECT_CZ05]:
        e.industry_code = rnd.choice(PAID_IN_INDUSTRIES)
        e.paid_capital = Decimal("0")
        gt.append(("企业", e.ent_id, "R-CZ-05",
                   {"行业码": e.industry_code, "实缴额": "0"}, False, False))
    p += N_INJECT_CZ05
    # R-CZ-05 难负例：属实缴制行业但已足额实缴 —— 合规，不应报（关键难负例：真银行确实实缴了）
    for e in pool2[p:p + N_HARDNEG_CZ05]:
        e.industry_code = rnd.choice(PAID_IN_INDUSTRIES)
        e.paid_capital = e.reg_capital
        gt.append(("企业", e.ent_id, "R-CZ-05",
                   {"note": "实缴制行业但已足额实缴，合规", "行业码": e.industry_code,
                    "实缴额": str(e.paid_capital)}, True, False))
    p += N_HARDNEG_CZ05

    # R-ZX-01 应注销未注销（企业级 status 字段）
    for e in pool2[p:p + N_INJECT_ZX01]:
        e.status = "吊销"
        gt.append(("企业", e.ent_id, "R-ZX-01", {"status": "吊销"}, False, False))
    p += N_INJECT_ZX01
    for e in pool2[p:p + N_HARDNEG_ZX01]:
        e.status = "注销"
        gt.append(("企业", e.ent_id, "R-ZX-01", {"note": "已注销，合规"}, True, False))
    p += N_HARDNEG_ZX01

    return addr_pool, ents, gt, people


def build_positions(ents, people_new, gt):
    """任职关系。挂载对象「自然人」的地基 —— 没有它，被法人/职业法人/受益所有人全做不了。

    职务取自矩阵B 的 9/9 核心口径：法定代表人、董事、监事、经理、登记联络员。
    财务负责人是 8/9（北京未提），一并生成但标注。

    ★ 职业法人注入：现实中同一自然人可合法担任多家公司法定代表人（《公司法》未禁止），
      但异常高频是虚假登记的已知信号 —— 官方点名的「被法人」即身份被冒用批量登记。
      注意这是【统计异常】不是【法定强制】：没有任何法条规定一人最多任几家。
    """
    positions = []
    # 各省对登记联络员的称谓不统一（矩阵B 观察列）：北京=相关联系人，河南=办税人（联络员）
    RAW_NAMES = {"登记联络员": "登记联络员"}

    for e in ents:
        legal = people_new()
        positions.append((e.ent_id, legal, "法定代表人", None, e.estab))
        for _ in range(rnd.choice([1, 2, 3])):
            positions.append((e.ent_id, people_new(), "董事", None, e.estab))
        positions.append((e.ent_id, people_new(), "监事", None, e.estab))
        positions.append((e.ent_id, people_new(), "经理", None, e.estab))
        positions.append((e.ent_id, people_new(), "登记联络员",
                          RAW_NAMES["登记联络员"], e.estab))
        positions.append((e.ent_id, people_new(), "财务负责人", None, e.estab))

    # 职业法人（正例）：少数自然人担任大量企业的法定代表人
    pro = [people_new() for _ in range(N_PRO_LEGAL_PERSON)]
    targets = rnd.sample(ents, N_PRO_LEGAL_PERSON * PRO_LEGAL_EACH)
    k = 0
    for p in pro:
        for _ in range(PRO_LEGAL_EACH):
            e = targets[k]; k += 1
            # 顶掉原法定代表人
            positions = [x for x in positions
                         if not (x[0] == e.ent_id and x[2] == "法定代表人")]
            positions.append((e.ent_id, p, "法定代表人", None, e.estab))
        gt.append(("自然人", p, "R-RY-01",
                   {"任法代企业数": PRO_LEGAL_EACH}, False, False))

    # 难负例：任 2~3 家法代 —— 完全合法且常见（一人开几家公司），不该被报
    for _ in range(N_HARDNEG_LEGAL):
        p = people_new()
        for e in rnd.sample(ents, rnd.choice([2, 3])):
            positions = [x for x in positions
                         if not (x[0] == e.ent_id and x[2] == "法定代表人")]
            positions.append((e.ent_id, p, "法定代表人", None, e.estab))
        gt.append(("自然人", p, "R-RY-01",
                   {"note": "任2~3家法代，合法且常见"}, True, False))

    return positions


def inject_dishonest(positions, gt):
    """失信被执行人注入。R-SM-06：失信被执行人任法定代表人。

    ★ 失信信息单独存 dict（person_id → dishonest_since），不改 person 的生成路径。
      失信是外部关联数据（失信名单）落图后打上的标记，不是登记数据自带的。
      正例：失信人 + 法定代表人（失信起始日设在其任职之前 → 在失信期内继续任职）。
      难负例：失信人 + 监事（非法代）—— 只有法定代表人受任职资格限制，监事不该被本规则命中。
    """
    dishonest: dict[str, date] = {}
    legals = list({x[1] for x in positions if x[2] == "法定代表人"})
    supers = list({x[1] for x in positions if x[2] == "监事"})
    rnd.shuffle(legals)
    rnd.shuffle(supers)

    for pid in legals[:N_INJECT_SM06]:
        eff = min(x[4] for x in positions if x[1] == pid and x[2] == "法定代表人")
        since = eff - timedelta(days=rnd.randint(30, 400))
        dishonest[pid] = since
        gt.append(("自然人", pid, "R-SM-06",
                   {"失信起始": str(since), "任职": "法定代表人"}, False, False))

    for pid in supers[:N_HARDNEG_SM06]:
        if pid in dishonest:
            continue
        dishonest[pid] = TODAY - timedelta(days=rnd.randint(30, 400))
        gt.append(("自然人", pid, "R-SM-06",
                   {"note": "失信人任监事（非法代），不应报", "任职": "监事"}, True, False))

    return dishonest


def build_biz_scope(ents, gt):
    """经营范围条目 —— 填 biz_scope_item（规范目录）+ ent_biz_scope（企业条目）两张空表。

    默认：每家企业 1~3 个条目，均取自规范目录（item_id 非空），许可项配批准文件号。
    注入：
      R-JY-01 许可项无批准文件（正例）：许可条目但 approval_no 为空。
      R-JY-03 表述不规范/目录缺口（正例）：item_id 为空（对不上规范目录）。
    两类命中集合互不相交，且与默认条目区分（item_id 与 approval_no 的取值决定命中，
    不依赖注入痕迹），故 P/R 对 ground truth 可算。
    """
    catalog = list(BIZ_CATALOG)
    licensed = [it for it in catalog if it[3]]
    normal_pool = [it for it in catalog if it[0] != "BS011"]   # 直播项不进默认池
    rows = []                       # (ent_id, item_id, raw_text, approval_no)
    seq = 0

    def approval():
        nonlocal seq
        seq += 1
        return f"许可字第{seq:05d}号"

    # 默认条目：规范目录内，许可项配批准文件
    for e in ents:
        k = rnd.choice([1, 1, 2, 2, 3])
        for it in rnd.sample(normal_pool, k):
            rows.append((e.ent_id, it[0], it[1], approval() if it[3] else None))

    pool = [e for e in ents if e.addr.kind == "normal"]
    rnd.shuffle(pool)
    p = 0

    # R-JY-01 正例：许可条目，无批准文件
    for e in pool[p:p + N_INJECT_JY01]:
        it = rnd.choice(licensed)
        rows.append((e.ent_id, it[0], it[1] + "（无批准文件）", None))
        gt.append(("企业", e.ent_id, "R-JY-01", {"许可项": it[1]}, False, False))
    p += N_INJECT_JY01
    # R-JY-01 难负例：许可条目，有批准文件
    for e in pool[p:p + N_HARDNEG_JY01]:
        it = rnd.choice(licensed)
        rows.append((e.ent_id, it[0], it[1] + "（持证）", approval()))
        gt.append(("企业", e.ent_id, "R-JY-01", {"note": "许可项有批准文件，合规"}, True, False))
    p += N_HARDNEG_JY01

    # R-JY-03 正例：item_id 为空（目录缺口）
    for e in pool[p:p + N_INJECT_JY03]:
        txt = rnd.choice(OFF_CATALOG) + f"#{e.ent_id[-5:]}"
        rows.append((e.ent_id, None, txt, None))
        gt.append(("企业", e.ent_id, "R-JY-03", {"表述": txt}, False, False))
    p += N_INJECT_JY03
    # R-JY-03 难负例：规范表述（item_id 非空）
    for e in pool[p:p + N_HARDNEG_JY03]:
        it = rnd.choice(normal_pool)
        rows.append((e.ent_id, it[0], it[1] + "（规范表述）", approval() if it[3] else None))
        gt.append(("企业", e.ent_id, "R-JY-03", {"note": "表述在规范目录内，合规"}, True, False))
    p += N_HARDNEG_JY03

    # R-JY-07 直播电商专题标记（圈定，非风险）：经营范围含直播关键词，映射到 BS011（不触发 R-JY-03）
    for idx, e in enumerate(pool[p:p + N_INJECT_JY07]):
        txt = rnd.choice(LIVE_TXT) + f"#{e.ent_id[-5:]}"
        rows.append((e.ent_id, "BS011", txt, None))
        gt.append(("企业", e.ent_id, "R-JY-07", {"表述": txt}, False, False))
        if idx < LIVE_LICENSE_GAP:
            # 直播带货涉食品销售（BS105 许可项）但无批准文件 → 同时命中 R-JY-01
            rows.append((e.ent_id, "BS105", "食品销售（直播带货·无证）", None))
            gt.append(("企业", e.ent_id, "R-JY-01",
                       {"许可项": "食品销售", "note": "直播带货涉食品无证"}, False, False))
    p += N_INJECT_JY07

    return catalog, rows


def build_agents(ents, positions, gt):
    """登记代理人 —— 第 6 个挂载对象。《经营主体登记申请及代理行为管理办法》（2025）。

    R-SM-03 未备案（第七条）：filed=FALSE 且有代理申报。
    R-SM-04 兼任登记联络员（第五条第二款，自设主体除外）：代理人自然人兼任某企业登记联络员，
      且未出资该企业。难负例 = 兼任「自设主体」的联络员（除外，不应报）。
    ★ 自设难负例用「替换股东三元组里的人、金额不变」制造 P 出资 X，不污染 R-CZ-01。
    """
    agents = []
    used = {g[1] for g in gt}
    # ★ 限定 0 号股东为自然人：自设难负例要「替换该股东为代理人自然人、金额不变」，
    #   若 0 号是企业股东则替换被跳过 → 自设没生效 → 难负例反被 R-SM-04 误报（FP）。
    clean = [e for e in ents if e.addr.kind == "normal" and e.ent_id not in used
             and e.shareholders and e.shareholders[0][0] == "NATURAL"]
    rnd.shuffle(clean)
    ci = 0

    for i in range(N_AGENT):
        pid = new_person_global()
        filed = i >= N_INJECT_SM03
        aid = f"AG{i:04d}"
        agents.append({"agent_id": aid, "person_id": pid, "agent_type": "个人",
                       "filed": filed,
                       "filed_at": (TODAY - timedelta(days=rnd.randint(30, 300))) if filed else None})
        if filed:
            gt.append(("登记代理人", aid, "R-SM-03", {"note": "已备案，合规"}, True, False))
        else:
            gt.append(("登记代理人", aid, "R-SM-03", {"filed": False}, False, False))

    filed_agents = [a for a in agents if a["filed"]]
    # R-SM-04 正例：兼任非自设主体的登记联络员
    for a in filed_agents[:N_INJECT_SM04]:
        e = clean[ci]; ci += 1
        positions.append((e.ent_id, a["person_id"], "登记联络员", "登记联络员", e.estab))
        gt.append(("登记代理人", a["agent_id"], "R-SM-04", {"兼任企业": e.ent_id}, False, False))
    # R-SM-04 难负例：自设主体除外（P 既是 X 联络员、又出资 X）
    for a in filed_agents[N_INJECT_SM04:N_INJECT_SM04 + N_HARDNEG_SM04]:
        e = clean[ci]; ci += 1
        if e.shareholders and e.shareholders[0][0] == "NATURAL":
            _, _, amt = e.shareholders[0]
            e.shareholders[0] = ("NATURAL", a["person_id"], amt)   # 自设，金额不变
        positions.append((e.ent_id, a["person_id"], "登记联络员", "登记联络员", e.estab))
        gt.append(("登记代理人", a["agent_id"], "R-SM-04",
                   {"note": "自设主体的联络员，除外，不应报"}, True, False))

    return agents


# 登记机关。★ A32-13 被刻意设成效能短板：退回率显著偏高、办理时长显著偏长。
# 效能标签挂登记机关，不挂企业 —— 赛题写了「效能短板」，而所有人都在给企业打标签。
AUTHORITIES = [
    # (authority_id, 名称, 行政区划, 退回率, 办理时长天数区间)
    ("AU320102", "南京市玄武区市场监督管理局", "320102", 0.14, (1, 3)),
    ("AU320104", "南京市秦淮区市场监督管理局", "320104", 0.16, (1, 3)),
    ("AU320105", "南京市建邺区市场监督管理局", "320105", 0.12, (1, 2)),
    ("AU320106", "南京市鼓楼区市场监督管理局", "320106", 0.15, (1, 3)),
    ("AU320111", "南京市浦口区市场监督管理局", "320111", 0.13, (1, 3)),
    ("AU320113", "南京市栖霞区市场监督管理局", "320113", 0.46, (3, 9)),   # ★ 效能短板
    ("AU320114", "南京市雨花台区市场监督管理局", "320114", 0.15, (1, 3)),
]
AUTH_BY_DIV = {a[2]: a for a in AUTHORITIES}

RETURN_REASONS = ["材料不齐", "住所证明不符合要求", "经营范围表述不规范",
                  "股东身份核验未通过", "出资信息填报有误"]

N_PENDING = 50          # 在途申请（事前拦截的作用对象）
N_PENDING_BAD = 8       # 其中注入出资不符 —— 应当被事前拦截


def build_applications(ents, gt, agents):
    """申请件。三类：
       已核准 —— 对应已登记企业。注意那 30 家出资不符的也在其中：
                 它们是【存量】，规则上线时早已核准。事前拦截防新增，事后回溯清存量。
       已退回 —— 无对应企业，效能分析的主要素材（退回率、退回原因分布）
       校验中 —— 在途，事前拦截规则作用于此。此时企业尚不存在，只有 payload。
    """
    apps = []
    seq = 0

    # ★ 登记机关的 ground truth。曾漏掉这段：AUTHORITIES 里把栖霞区设成了效能短板，
    #   却没写进 injection_log —— 没有 GT，模拟复核员一律默认判「误报」，
    #   于是 R-XN-01 的实测 precision 是 0.000，看起来像规则坏了，其实是评测坏了。
    #   教训：注入异常和记录 ground truth 必须同时做，分开写就会漏。
    norm_rate = sorted(a[3] for a in AUTHORITIES)[len(AUTHORITIES) // 2]   # 中位退回率
    for a in AUTHORITIES:
        is_outlier = a[3] > norm_rate * 2
        gt.append(("登记机关", a[0], "R-XN-01",
                   {"退回率": a[3], "全省中位": norm_rate,
                    "note": "效能短板" if is_outlier else "正常机关，不应报"},
                   not is_outlier, False))

    def payload_of(name, reg_capital, shareholders):
        return {"名称": name,
                "注册资本": float(reg_capital),
                "股东": [{"认缴": float(a)} for _, _, a in shareholders]}

    # 1. 已核准
    for e in ents:
        seq += 1
        auth = AUTH_BY_DIV[e.addr.division]
        sub = datetime.combine(e.estab, dtime(9, 0)) - timedelta(days=rnd.randint(*auth[4]))
        apps.append(dict(
            app_id=f"APP{seq:06d}", app_type="设立", authority_id=auth[0],
            province_code=PROVINCE, submitted_at=sub,
            decided_at=datetime.combine(e.estab, dtime(16, 0)),
            status="已核准", return_reason=None,
            return_count=1 if rnd.random() < auth[3] else 0,   # 退回后重报最终核准
            ent_id=e.ent_id, payload=payload_of(e.name, e.reg_capital, e.shareholders)))

    # 2. 已退回（无企业）
    for auth in AUTHORITIES:
        n_appr = sum(1 for a in apps if a["authority_id"] == auth[0])
        n_ret = int(n_appr * auth[3] / (1 - auth[3]))
        for _ in range(n_ret):
            seq += 1
            sub = TODAY - timedelta(days=rnd.randint(0, HISTORY_DAYS))
            cap = reg_capital_sample()
            apps.append(dict(
                app_id=f"APP{seq:06d}", app_type="设立", authority_id=auth[0],
                province_code=PROVINCE,
                submitted_at=datetime.combine(sub, dtime(9, 0)),
                decided_at=datetime.combine(sub, dtime(9, 0)) + timedelta(days=rnd.randint(*auth[4])),
                status="已退回", return_reason=rnd.choice(RETURN_REASONS),
                return_count=rnd.randint(1, 3), ent_id=None,
                payload=payload_of(fake.company()[:24], cap, [(None, None, cap)])))

    # 3. 校验中（在途）—— 事前拦截的作用对象（R-CZ-01-PRE 资本 + R-MC-01/02 名称）
    # 索引分区（互不相交）：[0,8) 资本不符 | [8,14) 名称缺失 | [14,24) 禁限用词
    #                       | [24,30) 名称难负例 | [30,50) 正常
    mc01_lo = N_PENDING_BAD
    mc02_lo = mc01_lo + N_INJECT_MC01
    mc02n_lo = mc02_lo + N_INJECT_MC02
    normal_lo = mc02n_lo + N_HARDNEG_MC02
    for i in range(N_PENDING):
        seq += 1
        auth = rnd.choice(AUTHORITIES)
        cap = reg_capital_sample()
        parts = split_capital(cap, rnd.choice([1, 2, 3]))
        bad = i < N_PENDING_BAD
        if bad:                                  # 注入：认缴合计 ≠ 注册资本
            parts[0] = parts[0] + (cap * Decimal("0.2")).quantize(Decimal("0.0001"))
        # 名称（事前拦截 R-MC-01/02 的判定对象）
        name = f"南京{fake.company_prefix()}{rnd.choice(['科技', '贸易', '咨询'])}有限公司(在途{i})"
        name_gt = None
        if mc01_lo <= i < mc02_lo:
            name, name_gt = "", ("R-MC-01", False)          # 名称缺失
        elif mc02_lo <= i < mc02n_lo:
            name = f"南京{rnd.choice(FORBIDDEN_WORDS)}科技有限公司(在途{i})"
            name_gt = ("R-MC-02", False)                    # 含禁限用词
        elif mc02n_lo <= i < normal_lo:
            name = f"南京{rnd.choice(MC02_HARDNEG)}服务有限公司(在途{i})"
            name_gt = ("R-MC-02", True)                     # 含子串非禁用词，不应报
        aid = f"APP{seq:06d}"
        apps.append(dict(
            app_id=aid, app_type="设立", authority_id=auth[0], province_code=PROVINCE,
            submitted_at=datetime.combine(TODAY - timedelta(days=rnd.randint(0, 5)), dtime(10, 0)),
            decided_at=None, status="校验中", return_reason=None, return_count=0,
            ent_id=None, payload=payload_of(name, cap, [(None, None, p) for p in parts])))
        if bad:
            gt.append(("业务单据", aid, "R-CZ-01-PRE",
                       {"注册资本": float(cap), "认缴合计": float(sum(parts))}, False, False))
        if name_gt:
            gt.append(("业务单据", aid, name_gt[0], {"名称": name}, name_gt[1], False))

    # 4. 变更申请（已核准）—— R-BG-01 变更登记逾期（《条例》第24条·30日）
    # ★ 只挑存续企业，避免与 R-ZX-04（注销后变更）互相干扰。
    chg_pool = [e for e in ents if e.status == "存续"]
    chg_targets = rnd.sample(chg_pool, N_CHANGE)
    for k, e in enumerate(chg_targets):
        seq += 1
        auth = AUTH_BY_DIV[e.addr.division]
        resol = e.estab + timedelta(days=rnd.randint(60, 900))
        if resol > TODAY - timedelta(days=130):
            resol = TODAY - timedelta(days=rnd.randint(130, 300))
        late = k < N_INJECT_BG01
        hardneg = N_INJECT_BG01 <= k < N_INJECT_BG01 + N_HARDNEG_BG01
        gap = rnd.randint(35, 120) if late else rnd.randint(1, 25)   # >30 逾期 / <=30 合规
        sub_date = resol + timedelta(days=gap)
        aid = f"APP{seq:06d}"
        apps.append(dict(
            app_id=aid, app_type="变更", authority_id=auth[0], province_code=PROVINCE,
            submitted_at=datetime.combine(sub_date, dtime(10, 0)),
            decided_at=datetime.combine(sub_date + timedelta(days=1), dtime(16, 0)),
            status="已核准", return_reason=None, return_count=0, ent_id=e.ent_id,
            payload={"变更事项": "经营范围", "决议日期": str(resol)}))
        if late:
            gt.append(("业务单据", aid, "R-BG-01",
                       {"决议日期": str(resol), "申请日期": str(sub_date),
                        "逾期天数": gap - 30}, False, False))
        elif hardneg:
            gt.append(("业务单据", aid, "R-BG-01",
                       {"note": "30日内申请，合规", "间隔天数": gap}, True, False))

    # 5. 注销申请（已核准）—— 给注销状态企业配注销件；部分注入注销后变更（R-ZX-04）
    zx_ents = [e for e in ents if e.status == "注销"]
    for j, e in enumerate(zx_ents):
        seq += 1
        auth = AUTH_BY_DIV[e.addr.division]
        zx_date = TODAY - timedelta(days=rnd.randint(120, 400))
        apps.append(dict(
            app_id=f"APP{seq:06d}", app_type="注销", authority_id=auth[0],
            province_code=PROVINCE,
            submitted_at=datetime.combine(zx_date - timedelta(days=5), dtime(9, 0)),
            decided_at=datetime.combine(zx_date, dtime(16, 0)),
            status="已核准", return_reason=None, return_count=0, ent_id=e.ent_id,
            payload={"注销原因": "决议解散"}))
        if j < N_INJECT_ZX04:
            # 注销之后又发生变更申请（数据矛盾）。★ 决议日期贴近申请日期，避免误触 R-BG-01。
            seq += 1
            chg_sub = zx_date + timedelta(days=rnd.randint(10, 90))
            resol2 = chg_sub - timedelta(days=rnd.randint(1, 20))
            apps.append(dict(
                app_id=f"APP{seq:06d}", app_type="变更", authority_id=auth[0],
                province_code=PROVINCE,
                submitted_at=datetime.combine(chg_sub, dtime(10, 0)),
                decided_at=datetime.combine(chg_sub + timedelta(days=1), dtime(16, 0)),
                status="已核准", return_reason=None, return_count=0, ent_id=e.ent_id,
                payload={"变更事项": "法定代表人", "决议日期": str(resol2)}))
            gt.append(("企业", e.ent_id, "R-ZX-04", {"注销日": str(zx_date)}, False, False))
        else:
            gt.append(("企业", e.ent_id, "R-ZX-04",
                       {"note": "注销后无变更，合规"}, True, False))

    # 代理人关联：每笔申报默认无代理人；给每个代理人分派 1 笔已核准申报（使其「有代理行为」）。
    # ★ 必须在全部申报（含变更/注销）建完后做，否则后建的申报缺 agent_id 键。
    for a in apps:
        a["agent_id"] = None
    approved = [a for a in apps if a["status"] == "已核准"]
    for app, ag in zip(rnd.sample(approved, min(len(agents), len(approved))), agents):
        app["agent_id"] = ag["agent_id"]
    return apps


def load(addrs, ents, gt, people, apps, positions, dishonest, catalog, biz_rows, agents):
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE injection_log, application, reg_agent, authority, investment,"
                    " position_hold, ent_biz_scope, biz_scope_item, enterprise,"
                    " person, address CASCADE")

        cur.executemany(
            "INSERT INTO authority (authority_id, authority_name, province_code, level)"
            " VALUES (%s,%s,%s,'县区')",
            [(a[0], a[1], PROVINCE) for a in AUTHORITIES])

        cur.executemany(
            "INSERT INTO address (address_id, raw_address, division_code, province_code,"
            " road, house_no, room_no, norm_method, norm_confidence)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,'synthetic',1.0)",
            [(a.address_id, a.raw, a.division, PROVINCE, a.road, a.house_no, a.room_no) for a in addrs])

        cur.executemany(
            "INSERT INTO person (person_id, name_hash, id_type, is_dishonest, dishonest_since)"
            " VALUES (%s,%s,'身份证',%s,%s)",
            [(p, n, p in dishonest, dishonest.get(p)) for p, n in people.items()])

        cur.executemany(
            "INSERT INTO enterprise (ent_id, ent_name, address_id, reg_capital, industry_code,"
            " paid_capital, estab_date, status, reg_authority, province_code)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'南京市市场监督管理局',%s)",
            [(e.ent_id, e.name, e.addr.address_id, e.reg_capital, e.industry_code,
              e.paid_capital, e.estab, e.status, PROVINCE) for e in ents])

        # 出资方式/期限按企业统一取值，应用到该企业的全部 investment 行
        rows = []
        for e in ents:
            for t, sid, amt in e.shareholders:
                rows.append((e.ent_id, t,
                             sid if t == "NATURAL" else None,
                             sid if t == "ENTERPRISE" else None,
                             amt, e.contrib_method, e.contrib_deadline))
        cur.executemany(
            "INSERT INTO investment (investee_ent_id, investor_type, investor_person_id,"
            " investor_ent_id, subscribed_amount, contrib_method, contrib_deadline)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)

        cur.executemany(
            "INSERT INTO biz_scope_item (item_id, item_name, industry_code, is_licensed)"
            " VALUES (%s,%s,%s,%s)", catalog)
        cur.executemany(
            "INSERT INTO ent_biz_scope (ent_id, item_id, raw_text, approval_no)"
            " VALUES (%s,%s,%s,%s)", biz_rows)

        cur.executemany(
            "INSERT INTO position_hold (ent_id, person_id, post_type, raw_post_name,"
            " effective_date) VALUES (%s,%s,%s,%s,%s)", positions)

        cur.executemany(
            "INSERT INTO reg_agent (agent_id, agent_name_hash, agent_type, filed, filed_at, person_id)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            [(a["agent_id"], h(a["agent_id"]), a["agent_type"], a["filed"],
              a["filed_at"], a["person_id"]) for a in agents])

        cur.executemany(
            "INSERT INTO application (app_id, app_type, authority_id, province_code,"
            " submitted_at, decided_at, status, return_reason, return_count, ent_id, agent_id, payload)"
            " VALUES (%(app_id)s,%(app_type)s,%(authority_id)s,%(province_code)s,"
            " %(submitted_at)s,%(decided_at)s,%(status)s,%(return_reason)s,"
            " %(return_count)s,%(ent_id)s,%(agent_id)s,%(payload)s)",
            [{**a, "payload": psycopg.types.json.Json(a["payload"])} for a in apps])

        seen = set()
        gt_rows = []
        for et, eid, rid, params, hard, noise in gt:
            key = (et, eid, rid, hard)
            if key in seen:
                continue
            seen.add(key)
            gt_rows.append((et, eid, rid, psycopg.types.json.Json(params), hard, noise))
        cur.executemany(
            "INSERT INTO injection_log (entity_type, entity_id, rule_id, injection_params,"
            " is_hard_negative, is_label_noise) VALUES (%s,%s,%s,%s,%s,%s)", gt_rows)

        conn.commit()
        return len(addrs), len(ents), len(rows), len(gt_rows), len(apps), len(positions)


if __name__ == "__main__":
    from collections import Counter
    addrs, ents, gt, people = build()
    positions = build_positions(ents, new_person_global, gt)
    dishonest = inject_dishonest(positions, gt)
    catalog, biz_rows = build_biz_scope(ents, gt)
    agents = build_agents(ents, positions, gt)
    apps = build_applications(ents, gt, agents)
    na, ne, ni, ng, nap, npos = load(addrs, ents, gt, people, apps, positions,
                                     dishonest, catalog, biz_rows, agents)
    print(f"地址 {na} | 企业 {ne} | 自然人 {len(people)} | 出资记录 {ni} | ground truth {ng}")
    print(f"申请件 {nap} |", dict(Counter(a["status"] for a in apps)))
    print(f"任职记录 {npos} |", dict(Counter(p[2] for p in positions)))
    print(f"失信自然人 {len(dishonest)} 人 | 经营范围目录 {len(catalog)} 项 / 企业条目 {len(biz_rows)} 条")
    print(f"登记代理人 {len(agents)} 人（未备案 {sum(1 for a in agents if not a['filed'])}）")
    print("地址类型:", dict(Counter(a.kind for a in addrs)))
    print("注入分布:", dict(Counter((g[2], "难负例" if g[4] else "正例") for g in gt)))
