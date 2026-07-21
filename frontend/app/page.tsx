"use client";

import { Fragment, useMemo, useState } from "react";

type View = "overview" | "standards" | "clues" | "evidence" | "analysis" | "rectification" | "rules" | "assistant";
type ClueKey = "address" | "capital" | "license" | "catalog" | "capitalFp";
type StandardKey = "license" | "capital" | "address" | "agent" | "change";
type WorkOrderKey = "capital" | "address";
type AlertKey = "address" | "capital";

const navigation: Array<{ id: View; label: string; icon: string; group: string }> = [
  { id: "overview", label: "监管总览", icon: "总", group: "" },
  { id: "standards", label: "标准规则", icon: "标", group: "" },
  { id: "analysis", label: "监测预警", icon: "警", group: "" },
  { id: "rectification", label: "整改闭环", icon: "整", group: "" },
  { id: "assistant", label: "智能助手", icon: "智", group: "" },
];

const clues: Record<ClueKey, {
  key: ClueKey; instance: number; entityType: string; entity: string; label: string; rule: string;
  type: string; action: string; verdict: string; fact: string; basis: string; explanation: string;
  fields: Array<[string, string]>;
}> = {
  address: { key:"address", instance:209, entityType:"地址", entity:"A32-00418", label:"住所批量聚集", rule:"R-ZS-02", type:"统计异常", action:"人工复核", verdict:"成立", fact:"同址50户；近30日新增50户；全省P99为12户", basis:"统计基线 · 样本量419 · 30日窗口", explanation:"同址主体数超过全省P99，且近30日新增超过当前阈值10户。该规则只生成异常线索，不作虚假登记认定。", fields:[["同址主体数","50户"],["近30日新增","50户"],["全省P99","12户"],["新增阈值","10户"],["时间窗口","30日"],["复核结果","成立（模拟）"]] },
  capital: { key:"capital", instance:29, entityType:"企业", entity:"9132011300000792XX", label:"出资与注册资本不符", rule:"R-CZ-01", type:"法定强制", action:"人工复核", verdict:"成立", fact:"注册资本100万元；股东认缴合计148万元；差额48万元", basis:"《公司法》第47条", explanation:"企业登记注册资本与股东认缴出资额合计存在可重复计算的数据矛盾，需结合原始申报材料人工核实。", fields:[["注册资本","100万元"],["认缴合计","148万元"],["差额","48万元"],["股东数","3人"],["规则版本","v1.0"],["复核结果","成立（模拟）"]] },
  license: { key:"license", instance:109, entityType:"企业", entity:"9132010200000217XX", label:"许可项无批准文件", rule:"R-JY-01", type:"法定强制", action:"人工复核", verdict:"成立", fact:"经营范围含“劳务派遣服务”，未关联批准文件", basis:"《市场主体登记管理条例》第14条", explanation:"许可经营项目在登记前依法须经批准时，应核验批准文件。系统确认字段缺失，具体适用范围仍由人员核验。", fields:[["许可经营项目","劳务派遣服务"],["批准文件编号","空"],["缺批准文件","是"],["对象类型","企业"],["规则版本","v1.0"],["复核结果","成立（模拟）"]] },
  catalog: { key:"catalog", instance:128, entityType:"企业", entity:"9132010200000236XX", label:"经营范围表述不规范", rule:"R-JY-03", type:"规范性", action:"仅打标", verdict:"成立", fact:"“宠物殡葬服务#236XX”未匹配规范表述目录", basis:"《市场主体登记管理条例》第14条 · 规范目录", explanation:"目录未匹配不等于企业表述错误，也可能说明规范目录存在缺口。因此只生成目录治理候选，不进入违法处置。", fields:[["目录外表述","宠物殡葬服务#236XX"],["匹配item_id","空"],["条目数","1"],["处置级别","仅打标"],["规则版本","v1.0"],["复核结果","成立（模拟）"]] },
  capitalFp: { key:"capitalFp", instance:32, entityType:"企业", entity:"9132011400000610XX", label:"出资与注册资本不符", rule:"R-CZ-01", type:"法定强制", action:"人工复核", verdict:"误报", fact:"注册资本10万元；认缴合计12.5万元；模拟复核判为误报", basis:"《公司法》第47条", explanation:"规则计算本身可复现，但模拟复核将该实例标记为误报。该结果保留并进入规则实测precision与处置等级治理。", fields:[["注册资本","10万元"],["认缴合计","12.5万元"],["差额","2.5万元"],["股东数","1人"],["规则版本","v1.0"],["复核结果","误报（模拟）"]] },
};

const clueOrder: ClueKey[] = ["address", "capital", "license", "catalog", "capitalFp"];
const months = ["8月","9月","10月","11月","12月","1月","2月","3月","4月","5月","6月","7月"];
const monthlyNew = [24,34,31,32,29,27,26,28,20,32,62,60];
const rules = [
  ["R-CZ-01","出资与注册资本不符","法定强制","人工复核",30],
  ["R-JY-01","许可项无批准文件","法定强制","人工复核",19],
  ["R-BG-05","股权自环","情报线索","仅打标",16],
  ["R-JY-03","经营范围表述不规范","规范性","仅打标",16],
  ["R-CZ-02","出资期限超五年","法定强制","人工复核",15],
  ["R-CZ-04","出资备案信息不全","法定强制","人工复核",15],
  ["R-JY-07","直播电商专题","规范性","仅打标",14],
  ["R-BG-01","变更登记逾期","法定强制","仅打标",12],
  ["R-CZ-05","实缴制行业未实缴","法定强制","人工复核",12],
  ["R-SM-03","登记代理人未备案","法定强制","人工复核",12],
  ["R-MC-02","名称含禁限用词","法定强制","硬阻断",10],
  ["R-ZS-02","住所批量聚集","统计异常","人工复核",2],
] as const;

const standards: Record<StandardKey, {
  id: string; name: string; domain: string; level: string; tone: string; status: string;
  basis: string; scope: string; fields: string; logic: string; trigger: string; action: string;
  evidence: string; national: string; local: string; version: string; rule: string;
  implementation: string; clue?: ClueKey;
}> = {
  license: {
    id:"STD-JY-001", name:"登记前许可项目核验", domain:"经营范围", level:"全国法定底线", tone:"red", status:"部分执行",
    basis:"《市场主体登记管理条例》第14条；《公司登记管理实施办法》第19条第（三）项",
    scope:"设立或变更经营范围、且包含登记前依法须经批准项目的经营主体",
    fields:"经营范围条目、许可属性、批准文件编号、文件有效期",
    logic:"经营范围命中前置许可目录，且未关联有效批准文件时生成合规线索",
    trigger:"目标：申报提交时；当前：登记后回溯",
    action:"目标：退回补正／不予登记；当前：人工复核",
    evidence:"经营范围快照、许可目录版本、批准文件查询结果、规则版本",
    national:"许可项目判定、必需字段、证据格式和处置边界全国统一",
    local:"地方仅可补充有合法依据的许可事项及责任部门，不得取消全国法定条件",
    version:"V1.0", rule:"R-JY-01", implementation:"登记后监测已运行", clue:"license"
  },
  capital: {
    id:"STD-CZ-001", name:"注册资本与股东认缴一致性", domain:"注册资本", level:"全国法定底线", tone:"red", status:"已执行",
    basis:"《中华人民共和国公司法》第47条",
    scope:"有限责任公司设立申报及登记后数据质量检查",
    fields:"注册资本、股东认缴出资额、币种、企业类型",
    logic:"同一企业全部股东认缴出资额合计应与登记注册资本一致",
    trigger:"申报提交时＋登记后定期回溯",
    action:"事前硬阻断；事后进入人工复核",
    evidence:"注册资本、逐股东认缴明细、合计值、差额和规则版本",
    national:"等式关系、字段口径、证据格式和法条依据全国统一",
    local:"不开放判定逻辑覆盖；仅配置责任机关和工单办理信息",
    version:"V1.0", rule:"R-CZ-01 / R-CZ-01-PRE", implementation:"事前与事后两种触发规则均已配置", clue:"capital"
  },
  address: {
    id:"STD-ZS-002", name:"住所短期批量聚集监测", domain:"住所", level:"全国监测框架", tone:"amber", status:"待真数校准",
    basis:"统计基线；不直接作违法认定",
    scope:"登记后住所数据质量和异常关联监测",
    fields:"标准化地址、同址主体数、近30日新增数、集群登记白名单",
    logic:"同址主体数超过地区基线且短期新增超过阈值，排除合法集群地址后生成线索",
    trigger:"登记后批量监测",
    action:"仅生成待核查线索，不得自动阻断或认定虚假登记",
    evidence:"原始地址、标准地址、地区基线、时间窗、白名单命中情况",
    national:"统一计算框架、证据字段、风险等级和不得自动定性的边界",
    local:"配置地址库、合法集群白名单、统计基线和核查责任机关",
    version:"V1.0", rule:"R-ZS-02", implementation:"按地区基线和白名单执行", clue:"address"
  },
  agent: {
    id:"STD-SM-003", name:"登记代理人身份备案核验", domain:"人员代理", level:"全国法定底线", tone:"red", status:"已执行",
    basis:"《经营主体登记申请及代理行为管理办法》第7条",
    scope:"由登记代理人代为提交的设立、变更、备案和注销申请",
    fields:"代理人身份、代理机构、全国代理人系统备案状态、授权关系",
    logic:"申报件存在代理人，但代理人未在全国信息系统表明身份时生成线索",
    trigger:"目标：申请受理时；当前：登记后回溯",
    action:"人工核验代理身份及授权材料",
    evidence:"代理人身份、备案状态、授权委托书和关联申请件",
    national:"代理身份、备案字段和核验要求全国统一",
    local:"配置核查承办机构和办理时限，不得放宽实名与备案要求",
    version:"V1.0", rule:"R-SM-03", implementation:"代理人对象、规则和标签已配置"
  },
  change: {
    id:"STD-BG-001", name:"登记事项变更时限监测", domain:"变更注销", level:"全国法定底线", tone:"red", status:"已执行",
    basis:"《市场主体登记管理条例》第24条",
    scope:"已经发生法定登记事项变更的市场主体",
    fields:"变更决议日期、法定事项发生日期、变更申请日期、申请类型",
    logic:"变更申请日期晚于决议、决定或法定事项发生之日起30日时生成线索",
    trigger:"变更申请受理时＋登记后回溯",
    action:"提醒补正并进入属地人工核实",
    evidence:"发生日期、申请日期、间隔天数、申请件及规则版本",
    national:"30日期限、日期口径、证据格式全国统一",
    local:"配置责任机关、提醒方式和工单时限，不得改变法定期限",
    version:"V1.0", rule:"R-BG-01", implementation:"登记后监测规则已运行"
  }
};

const standardOrder: StandardKey[] = ["license","capital","address","agent","change"];

const workOrders: Record<WorkOrderKey, {
  id:string; title:string; path:string; object:string; standard:string; rule:string; owner:string; deadline:string;
  finding:string; conclusion:string; correction:string; before:Array<[string,string]>; after:Array<[string,string]>;
  steps:Array<[string,string,string]>;
}> = {
  capital:{
    id:"WO-2026-0001",title:"注册资本与认缴合计不一致",path:"企业数据整改",object:"9132011300000792XX",standard:"STD-CZ-001",rule:"R-CZ-01",owner:"南京市栖霞区登记机关",deadline:"3个工作日",
    finding:"注册资本100万元，三名股东认缴合计148万元，存在48万元可重复计算的数据矛盾。",
    conclusion:"属地调取原始章程后确认注册资本为100万元；一条股东认缴记录在历史同步时重复写入。",
    correction:"地方更正重复的认缴明细，不改变企业真实登记事项；规则重算后注册资本与认缴合计均为100万元。",
    before:[["注册资本","100万元"],["认缴合计","148万元"],["差额","48万元"],["规则结果","命中"]],
    after:[["注册资本","100万元"],["认缴合计","100万元"],["差额","0万元"],["规则结果","不再命中"]],
    steps:[["总局生成线索","监测端","规则版本与原始证据快照已固化"],["按省下发","总局端","下发江苏省，指定3个工作日内核查"],["属地签收核查","江苏／南京","调取章程、申报表和股东明细"],["提交核查结论","属地登记机关","确认历史同步重复，问题成立"],["整改结果回传","属地登记机关","上传前后快照与原始章程依据"],["复核与规则重算","省级／总局","字段一致，R-CZ-01不再命中"],["销号归档","总局端","保留全过程记录，不覆盖原证据"]]
  },
  address:{
    id:"WO-2026-0002",title:"住所短期批量聚集核查",path:"误报反馈与规则治理",object:"A32-00418",standard:"STD-ZS-002",rule:"R-ZS-02",owner:"南京市栖霞区登记机关",deadline:"5个工作日",
    finding:"同址50户，近30日新增50户，超过全省P99和当前监测阈值，系统生成统计异常线索。",
    conclusion:"属地核实该地址为依法设立的集群登记场所，产权与托管材料有效，50户集中迁入具有合理原因。",
    correction:"不修改任何企业登记数据；将该地址作为有依据的合法集群地址反馈至规则治理，加入地区白名单后重新计算。",
    before:[["同址主体","50户"],["30日新增","50户"],["白名单命中","否"],["规则结果","命中"]],
    after:[["同址主体","50户"],["30日新增","50户"],["白名单命中","是"],["规则结果","不再命中"]],
    steps:[["总局生成线索","监测端","统计基线、时间窗和地址快照已固化"],["按省下发","总局端","下发江苏省，要求排除合法集群登记"],["属地签收核查","江苏／南京","核验地址、托管合同和集群登记资格"],["提交核查结论","属地登记机关","确认合法集群地址，线索不成立"],["误报证据回传","属地登记机关","上传政策依据、场所证明和核查说明"],["规则治理重算","省级／总局","加入有依据的白名单，企业数据不变"],["销号归档","总局端","记为规则误报，用于阈值和白名单治理"]]
  }
};

const alertCases: Record<AlertKey, {
  id:string; title:string; level:string; tone:string; type:string; state:string; clue:ClueKey; workOrder:WorkOrderKey;
  macro:{signal:string;value:string;compare:string;scope:string};
  meso:{title:string;scope:string;metrics:Array<[string,string,string]>};
  micro:{object:string;name:string;fact:string;label:string};
  handling:Array<[string,string]>;
}> = {
  address:{
    id:"ALERT-2026-021",title:"住所短期批量聚集",level:"黄色预警",tone:"amber",type:"统计异常",state:"待人工复核",clue:"address",workOrder:"address",
    macro:{signal:"全省住所聚集线索出现短期抬升",value:"2个地址",compare:"近30日新增主体集中度超过当前监测基线",scope:"江苏省 · 近30日"},
    meso:{title:"南京市住所聚集专题",scope:"南京市栖霞区 · 地址 A32-00418",metrics:[["50户","同址主体","超过全省P99：12户"],["50户","近30日新增","当前监测阈值：10户"],["未命中","合法集群白名单","必须由属地核验"]]},
    micro:{object:"A32-00418",name:"标准化地址对象",fact:"同址50户、近30日新增50户",label:"住所批量聚集"},
    handling:[["系统预警","只说明统计异常，不认定虚假登记"],["属地核查","核验场所、托管材料和合法集群资格"],["分类处置","若属误报，不改企业数据，反馈白名单和规则"],["重算销号","保留原始快照，规则重算不再命中后销号"]]
  },
  capital:{
    id:"ALERT-2026-018",title:"注册资本与认缴合计不一致",level:"橙色预警",tone:"red",type:"法定一致性校验",state:"待人工复核",clue:"capital",workOrder:"capital",
    macro:{signal:"注册资本一致性标签在本期集中出现",value:"30条",compare:"占当前227条标签实例的13.2%",scope:"江苏省 · 当前数据版本"},
    meso:{title:"登记机关一致性问题分布",scope:"南京市栖霞区登记机关",metrics:[["11条","该机关命中","需排除历史同步重复"],["100万元","样例注册资本","企业申报主表字段"],["148万元","股东认缴合计","存在48万元差额"]]},
    micro:{object:"9132011300000792XX",name:"登记企业",fact:"注册资本100万元，认缴合计148万元",label:"出资与注册资本不符"},
    handling:[["系统预警","固化注册资本、逐股东明细和规则版本"],["属地核查","调取章程、申报表和历史同步记录"],["分类处置","问题成立时由地方更正重复认缴明细"],["重算销号","总局复核前后快照，规则不再命中后销号"]]
  }
};

function Pill({ children, tone="gray" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function Heading({ eyebrow:_, title, description, aside }: { eyebrow: string; title: string; description?: string; aside?: React.ReactNode }) {
  return <header className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{aside}</header>;
}

export default function Home() {
  const [view,setView] = useState<View>("overview");
  const [selected,setSelected] = useState<ClueKey>("address");
  const [selectedStandard,setSelectedStandard] = useState<StandardKey>("license");
  const [selectedWorkOrder,setSelectedWorkOrder] = useState<WorkOrderKey>("capital");
  const [toast,setToast] = useState("");
  const notify = (message:string) => { setToast(message); window.setTimeout(()=>setToast(""),2400); };
  const go = (target:View) => { setView(target); window.scrollTo({top:0,behavior:"smooth"}); };
  const openEvidence = (key:ClueKey) => { setSelected(key); go("evidence"); };
  const openStandard = (key:StandardKey) => { setSelectedStandard(key); go("standards"); };
  const openRectification = (key:WorkOrderKey) => { setSelectedWorkOrder(key); go("rectification"); };
  return <main className="shell">
    <header className="app-header">
      <button className="brand" onClick={()=>go("overview")}><b>登</b><div><strong>登记智鉴</strong><span>企业登记合规监测</span></div></button>
      <nav aria-label="系统导航">{navigation.map(item=><button key={item.id} className={view===item.id?"active":""} onClick={()=>go(item.id)}><i>{item.icon}</i><span>{item.label}</span></button>)}</nav>
      <div className="header-status"><span className="dot"/><div><strong>监测服务运行中</strong><small>数据更新 2026-07-20</small></div></div>
    </header>
    <section className="workspace">
      <div className="content">
        {view==="overview"&&<Overview go={go} openEvidence={openEvidence}/>} 
        {view==="standards"&&<Standards selected={selectedStandard} setSelected={setSelectedStandard} openEvidence={openEvidence}/>}
        {view==="clues"&&<ClueList openEvidence={openEvidence}/>} 
        {view==="evidence"&&<Evidence clue={clues[selected]} go={go} openEvidence={openEvidence} openStandard={openStandard} openRectification={openRectification}/>}
        {view==="analysis"&&<Analysis openEvidence={openEvidence} openRectification={openRectification}/>}
        {view==="rectification"&&<Rectification go={go} notify={notify} initial={selectedWorkOrder}/>}
        {view==="rules"&&<RuleGovernance notify={notify} openEvidence={openEvidence}/>} 
        {view==="assistant"&&<Assistant notify={notify}/>} 
      </div>
    </section>
    {toast&&<div className="toast" role="status">{toast}</div>}
  </main>;
}

function Overview({go,openEvidence}:{go:(v:View)=>void;openEvidence:(k:ClueKey)=>void}) {
  return <>
    <Heading eyebrow="" title="企业登记合规监测工作台" description="统一标准发现问题，三级研判定位风险，整改工单推动问题闭环。" aside={<Pill tone="green">今日监测已完成</Pill>}/>
    <section className="kpis focus-kpis"><article><span>登记主体</span><strong>1,000<small> 家</small></strong><p>当前监管范围</p></article><article><span>运行规则</span><strong>20<small> 条</small></strong><p>按统一标准执行</p></article><article><span>待核查预警</span><strong>2<small> 条</small></strong><p>黄色1条 / 橙色1条</p></article><article><span>整改工单</span><strong>2<small> 件</small></strong><p>待下发2件</p></article></section>
    <section className="panel core-flow"><div className="section-title"><div><span>核心业务闭环</span><h2>从统一标准到整改销号</h2></div></div><div><button onClick={()=>go("standards")}><i>1</i><b>标准规则</b><small>明确监管口径</small></button><em>→</em><button onClick={()=>go("analysis")}><i>2</i><b>监测预警</b><small>发现并定位异常</small></button><em>→</em><button onClick={()=>openEvidence("address")}><i>3</i><b>证据核验</b><small>查看字段与依据</small></button><em>→</em><button onClick={()=>go("rectification")}><i>4</i><b>整改闭环</b><small>回传、复核、销号</small></button></div></section>
    <section className="dashboard-grid focus-dashboard"><article className="panel trend-card"><div className="section-title"><div><span>主体发展态势</span><h2>近12个月新设主体</h2></div><Pill>本月 60 户</Pill></div><div className="bars">{monthlyNew.map((v,i)=><div key={months[i]}><i style={{height:`${Math.max(22,v*1.8)}px`}} className={i>9?"hot":""}><b>{i>9?v:""}</b></i><span>{months[i]}</span></div>)}</div></article><article className="panel current-alerts"><div className="section-title"><div><span>当前重点</span><h2>待核查预警</h2></div><button className="text-action" onClick={()=>go("analysis")}>查看全部 →</button></div><button onClick={()=>go("analysis")}><Pill tone="amber">黄色</Pill><div><b>住所短期批量聚集</b><small>2个地址 · 待人工复核</small></div><em>→</em></button><button onClick={()=>go("analysis")}><Pill tone="red">橙色</Pill><div><b>注册资本与认缴不一致</b><small>30条线索 · 待人工复核</small></div><em>→</em></button></article></section>
  </>;
}

function Standards({selected,setSelected,openEvidence}:{selected:StandardKey;setSelected:(k:StandardKey)=>void;openEvidence:(k:ClueKey)=>void}) {
  const [domain,setDomain]=useState("全部");
  const current=standards[selected];
  const visible=standardOrder.filter(key=>domain==="全部"||standards[key].domain===domain);
  return <>
    <Heading eyebrow="UNIFIED REGULATORY STANDARD" title="统一监管标准中心" description="目标1在这里形成标准，目标2按标准执行。它不是法规清单，也不是SQL列表，而是可发布、可执行、可追溯的监管口径。" aside={<Pill tone="green">核心产品 · 标准样板5项</Pill>}/>
    <section className="standard-definition"><div><b>全国统一</b><span>法定底线、数据字段、证据格式、风险分级、版本与反馈编码</span></div><i>+</i><div><b>属地适配</b><span>依法配置住所政策、地方许可、统计阈值、责任机关和办理时限</span></div><i>=</i><div className="result"><b>统一监管标准</b><span>统一框架和底线，不等于全国一刀切</span></div></section>
    <section className="kpis standard-kpis"><article><span>已入库执行规则</span><strong>20<small> 条</small></strong><p>由标准映射为机器规则</p></article><article><span>法定强制规则</span><strong>14<small> 条</small></strong><p>必须具备明确法条锚点</p></article><article><span>标签挂载对象</span><strong>6<small> 类</small></strong><p>企业、人员、地址、单据、机关、代理人</p></article><article><span>当前标准化工作</span><strong>5<small> 项样板</small></strong><p>其余规则待补齐标准字段</p></article></section>
    <section className="standards-layout">
      <aside className="panel standard-catalog"><div className="standard-catalog-head"><span>标准目录</span><strong>从监管事项选标准</strong></div><div className="standard-domain-tabs">{["全部","经营范围","注册资本","住所","人员代理","变更注销"].map(x=><button key={x} className={domain===x?"active":""} onClick={()=>setDomain(x)}>{x}</button>)}</div><div className="standard-list">{visible.map(key=>{const item=standards[key];return <button key={key} className={selected===key?"active":""} onClick={()=>setSelected(key)}><span><Pill tone={item.tone}>{item.level}</Pill><small>{item.status}</small></span><b>{item.name}</b><em>{item.id} · {item.domain}</em></button>})}</div></aside>
      <article className="panel standard-detail">
        <header><div><span>{current.id} · {current.domain}</span><h2>{current.name}</h2><p>{current.basis}</p></div><div><Pill tone={current.tone}>{current.level}</Pill><Pill tone={current.status==="已执行"?"green":"amber"}>{current.status}</Pill></div></header>
        <div className="standard-fields"><div><span>适用范围</span><strong>{current.scope}</strong></div><div><span>所需数据</span><strong>{current.fields}</strong></div><div><span>判定逻辑</span><strong>{current.logic}</strong></div><div><span>触发时点</span><strong>{current.trigger}</strong></div><div><span>处置方式</span><strong>{current.action}</strong></div><div><span>证据要求</span><strong>{current.evidence}</strong></div></div>
        <div className="standard-split"><section><span>全国统一部分</span><p>{current.national}</p></section><section><span>属地可配置部分</span><p>{current.local}</p></section></div>
        <footer><div><span>标准版本</span><b>{current.version}</b></div><div><span>执行规则</span><b>{current.rule}</b></div><div><span>工程现状</span><b>{current.implementation}</b></div>{current.clue&&<button onClick={()=>openEvidence(current.clue!)}>查看命中证据 →</button>}</footer>
      </article>
    </section>
    <section className="panel standard-chain"><div className="section-title"><div><span>执行链路</span><h2>一条标准如何进入监管主链</h2></div><small>任一结论均可正向执行、反向追溯</small></div><div>{[["01","法规政策","确定法定底线"],["02","监管标准","定义字段、逻辑和处置"],["03","执行规则","机器解释运行"],["04","标签证据","保留命中快照"],["05","分析预警","形成研判线索"],["06","复核反馈","修正规则和标准"]].map((x,i)=><Fragment key={x[0]}><section><b>{x[0]}</b><strong>{x[1]}</strong><small>{x[2]}</small></section>{i<5&&<i>→</i>}</Fragment>)}</div></section>
    <p className="table-note">当前发布5项核心监管标准，覆盖经营范围、注册资本、住所、人员代理和变更注销。</p>
  </>;
}

function ClueList({openEvidence}:{openEvidence:(k:ClueKey)=>void}) {
  const [filter,setFilter]=useState("全部");
  const [query,setQuery]=useState("");
  const rows=clueOrder.map(k=>clues[k]).filter(x=>(filter==="全部"||x.type===filter)&&`${x.entity}${x.label}${x.rule}`.includes(query));
  return <>
    <Heading eyebrow="" title="线索清单" description="每条监测线索都能回到执行规则和命中时的字段快照。" aside={<Pill tone="green">227条线索</Pill>}/>
    <section className="filterbar"><label><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索对象、标签或规则编号"/></label>{["全部","法定强制","统计异常","规范性"].map(x=><button className={filter===x?"active":""} onClick={()=>setFilter(x)} key={x}>{x}</button>)}</section>
    <section className="panel clue-table"><div className="clue-row head"><span>标签实例</span><span>监测对象</span><span>命中标签 / 事实</span><span>类型与处置</span><span>复核结果</span><span>操作</span></div>{rows.map(x=><div className="clue-row" key={x.key}><span><b>TI-{x.instance}</b><small>{x.rule}</small></span><span><b>{x.entity}</b><small>{x.entityType}</small></span><span><b>{x.label}</b><small>{x.fact}</small></span><span><Pill tone={x.type==="法定强制"?"red":x.type==="统计异常"?"amber":"blue"}>{x.type}</Pill><small>{x.action}</small></span><span><Pill tone={x.verdict==="误报"?"blue":"green"}>{x.verdict}</Pill></span><button onClick={()=>openEvidence(x.key)}>查看证据 →</button></div>)}{rows.length===0&&<div className="empty">没有匹配的线索</div>}</section>
    <p className="table-note">页面只列出5条代表性样本；完整数据库中有227条当前有效标签和227条证据。</p>
  </>;
}

function Evidence({clue,go,openEvidence,openStandard,openRectification}:{clue:(typeof clues)[ClueKey];go:(v:View)=>void;openEvidence:(k:ClueKey)=>void;openStandard:(k:StandardKey)=>void;openRectification:(k:WorkOrderKey)=>void}) {
  const standardKey: StandardKey = clue.rule.startsWith("R-JY") ? "license" : clue.rule.startsWith("R-CZ") ? "capital" : "address";
  const linkedOrder: WorkOrderKey|null = clue.rule.startsWith("R-CZ") ? "capital" : clue.rule.startsWith("R-ZS") ? "address" : null;
  return <>
    <div className="evidence-head"><div><button onClick={()=>go("clues")}>← 返回线索清单</button><span>标签实例 TI-{clue.instance} · {clue.rule}</span><h1>{clue.label}</h1><p>{clue.entityType} · {clue.entity}</p></div><div><Pill tone={clue.verdict==="误报"?"blue":"green"}>模拟复核：{clue.verdict}</Pill><button className="secondary" onClick={()=>openEvidence(clue.verdict==="误报"?"address":"capitalFp")}>{clue.verdict==="误报"?"查看成立样例":"查看误报样例"}</button></div></div>
    <section className="evidence-grid"><div className="evidence-main"><article className="evidence-statement"><span>系统发现的可复核事实</span><h2>{clue.fact}</h2><p>{clue.explanation}</p></article><article className="panel block"><div className="section-title"><div><span>命中依据</span><h2>命中时字段快照</h2></div><Pill>不可覆盖留痕</Pill></div><div className="field-grid">{clue.fields.map(([a,b])=><div key={a}><span>{a}</span><strong>{b}</strong></div>)}</div></article><article className="panel block"><div className="section-title"><div><span>证据链路</span><h2>证据从哪里来</h2></div></div><div className="provenance"><div><b>1</b><strong>登记数据归集</strong><small>{clue.entityType} / {clue.entity}</small></div><i>→</i><div><b>2</b><strong>规则解释执行</strong><small>{clue.rule} · 规则存库</small></div><i>→</i><div><b>3</b><strong>标签与证据落库</strong><small>TI-{clue.instance} · 快照保留</small></div><i>→</i><div><b>4</b><strong>人工复核回流</strong><small>{clue.verdict}</small></div></div></article></div>
      <aside className="evidence-side"><article className="panel block"><div className="section-title"><div><span>处置依据</span><h2>标准、规则与依据</h2></div></div><dl><div><dt>监管标准</dt><dd>{standards[standardKey].id}</dd></div><div><dt>规则编号</dt><dd>{clue.rule}</dd></div><div><dt>规则类型</dt><dd>{clue.type}</dd></div><div><dt>处置级别</dt><dd>{clue.action}</dd></div><div><dt>法条/基线</dt><dd>{clue.basis}</dd></div><div><dt>自动违法认定</dt><dd>否</dd></div></dl><button className="full-button" onClick={()=>openStandard(standardKey)}>查看统一监管标准 →</button><button className="full-button muted stacked" onClick={()=>go("rules")}>查看执行规则 →</button></article><article className="boundary"><strong>处置边界</strong><p>{clue.type==="统计异常"?"统计异常没有直接法定结论，必须排除合法集群登记、集中迁入和地址归一错误。":"规则命中提供核验依据，最终处理仍应结合原始档案和完整事实。"}</p></article><article className="panel block"><div className="section-title"><div><span>后续处置</span><h2>线索去向</h2></div></div><p className="small-copy">{linkedOrder?"人工复核后，可直接进入对应整改或规则治理工单。":"该专题线索进入人工复核队列。"}</p>{linkedOrder?<button className="full-button muted" onClick={()=>openRectification(linkedOrder)}>进入对应整改工单 →</button>:<button className="full-button muted" onClick={()=>go("analysis")}>返回监测预警 →</button>}</article></aside></section>
  </>;
}

function Analysis({openEvidence,openRectification}:{openEvidence:(k:ClueKey)=>void;openRectification:(k:WorkOrderKey)=>void}) {
  const [level,setLevel]=useState<"macro"|"meso"|"micro">("macro");
  const [selectedAlert,setSelectedAlert]=useState<AlertKey>("address");
  const alert=alertCases[selectedAlert];
  const chooseAlert=(key:AlertKey)=>{setSelectedAlert(key);setLevel("macro");};
  return <>
    <Heading eyebrow="EARLY WARNING · DRILL DOWN · HANDLING" title="三级研判与预警处置" description="围绕同一条预警，从宏观异常、中观定位下钻到微观证据，复核后再进入整改或规则治理。" aside={<Pill tone="amber">2条联动预警样例</Pill>}/>
    <section className="alert-boundary"><div><b>预警不是违法认定</b><p>系统只报告可复核事实和异常程度；是否成立、如何处理，由属地结合原始档案人工核查。</p></div><div className="warning-legend"><span><i className="blue"/>蓝色：态势关注</span><span><i className="amber"/>黄色：统计核查</span><span><i className="red"/>橙色：重点复核</span></div></section>
    <section className="alert-selector">{(["address","capital"] as AlertKey[]).map(key=>{const item=alertCases[key];return <button key={key} className={selectedAlert===key?"active":""} onClick={()=>chooseAlert(key)}><div><Pill tone={item.tone}>{item.level}</Pill><span>{item.state}</span></div><b>{item.title}</b><small>{item.id} · {item.type}</small></button>})}</section>
    <section className="panel warning-chain"><header><div><span>当前预警任务</span><h2>{alert.title}</h2><p>{alert.id} · {alert.macro.scope}</p></div><Pill tone={alert.tone}>{alert.state}</Pill></header><div className="warning-steps"><button className={level==="macro"?"active":""} onClick={()=>setLevel("macro")}><i>1</i><b>宏观发现</b><small>指标异常触发关注</small></button><em>→</em><button className={level==="meso"?"active":""} onClick={()=>setLevel("meso")}><i>2</i><b>中观定位</b><small>地区／机关／专题</small></button><em>→</em><button className={level==="micro"?"active":""} onClick={()=>setLevel("micro")}><i>3</i><b>微观核验</b><small>对象、标签和证据</small></button><em>→</em><button className="handling" onClick={()=>openRectification(alert.workOrder)}><i>4</i><b>分类处置</b><small>整改或规则治理</small></button></div></section>
    <section className="level-tabs linked"><button className={level==="macro"?"active":""} onClick={()=>setLevel("macro")}><span>宏观</span><b>发现“发生了什么”</b><small>省域、时间和总体趋势</small></button><i>→</i><button className={level==="meso"?"active":""} onClick={()=>setLevel("meso")}><span>中观</span><b>定位“集中在哪里”</b><small>地区、机关、专题和群体</small></button><i>→</i><button className={level==="micro"?"active":""} onClick={()=>setLevel("micro")}><span>微观</span><b>解释“具体是谁、为什么”</b><small>对象、字段、规则和证据</small></button></section>
    {level==="macro"&&<section className="analysis-grid"><article className="panel block wide"><div className="section-title"><div><span>宏观预警 · {alert.id}</span><h2>{alert.macro.signal}</h2></div><Pill tone={alert.tone}>{alert.level}</Pill></div><div className="macro-signal"><strong>{alert.macro.value}</strong><div><b>{alert.macro.compare}</b><span>{alert.macro.scope}</span></div></div><div className="large-bars compact">{monthlyNew.map((v,i)=><div key={months[i]}><b>{v}</b><i style={{height:`${v*1.5}px`}} className={i>9?"hot":""}/><span>{months[i]}</span></div>)}</div><p className="metric-definition">监测指标超过设定基线后触发预警，再进入地区、登记机关或专题群体分析。</p></article><article className="panel block action-panel"><div className="section-title"><div><span>下一步</span><h2>定位异常集中范围</h2></div></div><p>宏观层发现总体变化，中观层进一步定位异常集中在哪个地区、登记机关或专题群体。</p><button className="full-button" onClick={()=>setLevel("meso")}>进入中观定位 →</button></article></section>}
    {level==="meso"&&<section className="analysis-grid"><article className="panel block wide"><div className="section-title"><div><span>中观定位 · {alert.id}</span><h2>{alert.meso.title}</h2></div><Pill tone="blue">{alert.meso.scope}</Pill></div><div className="topic-metrics">{alert.meso.metrics.map(([value,label,note])=><div key={label}><strong>{value}</strong><span>{label}</span><small>{note}</small></div>)}</div><div className="topic-note"><b>中观判断</b><p>异常已经从全省范围收敛到具体地区、登记机关或关联群体，但仍只是待核查对象集合。</p></div><button className="text-action next-link" onClick={()=>setLevel("micro")}>查看其中一个对象及证据 →</button></article><article className="panel block topic-side"><div className="section-title"><div><span>重点专题</span><h2>直播电商</h2></div></div><div className="community-number"><strong>14</strong><span>家专题主体</span><i>/</i><strong>5</strong><span>家许可缺失</span></div><p className="small-copy">直播电商在中观层表现为专题群体，点击企业后进入微观预警。</p><button className="text-action" onClick={()=>openEvidence("license")}>查看一条许可缺失证据 →</button></article></section>}
    {level==="micro"&&<><section className="profile-layout"><article className="panel block"><div className="section-title"><div><span>微观对象 · {alert.id}</span><h2>具体对象与命中事实</h2></div><Pill tone={alert.tone}>{alert.level}</Pill></div><div className="profile-head"><div className="company-mark">{selectedAlert==="address"?"址":"企"}</div><div><strong>{alert.micro.object}</strong><p>{alert.micro.name}</p></div></div><div className="profile-sections"><div><span>风险标签</span><b>{alert.micro.label}</b></div><div><span>当前状态</span><b>{alert.state}</b></div><div><span>命中事实</span><b>{alert.micro.fact}</b></div><div><span>处置边界</span><b>必须人工复核</b></div></div><button className="full-button" onClick={()=>openEvidence(alert.clue)}>查看字段快照与规则依据 →</button></article><article className="panel block"><div className="section-title"><div><span>处置路径</span><h2>预警如何处理</h2></div><Pill tone="green">路径已连接</Pill></div><ol className="handling-list">{alert.handling.map(([title,copy],i)=><li key={title}><i>{i+1}</i><div><b>{title}</b><p>{copy}</p></div></li>)}</ol><button className="full-button handling-button" onClick={()=>openRectification(alert.workOrder)}>进入对应整改工单 →</button></article></section><section className="warning-outcome"><div><span>系统输出</span><b>预警线索＋不可变证据快照</b></div><i>→</i><div><span>人工结论</span><b>成立 / 误报 / 补充材料</b></div><i>→</i><div><span>分类反馈</span><b>{selectedAlert==="capital"?"更正企业数据":"治理白名单与规则"}</b></div><i>→</i><button onClick={()=>openRectification(alert.workOrder)}>工单重算销号 →</button></section></>}
  </>;
}

function Rectification({go,notify,initial}:{go:(v:View)=>void;notify:(m:string)=>void;initial:WorkOrderKey}) {
  const [selected,setSelected]=useState<WorkOrderKey>(initial);
  const [stages,setStages]=useState<Record<WorkOrderKey,number>>({capital:0,address:0});
  const [detail,setDetail]=useState<"none"|"evidence"|"record">("none");
  const order=workOrders[selected];
  const stage=stages[selected];
  const stageNames=["待下发","待签收","核查中","待回传","待复核","规则重算","已销号"];
  const actions=["下发至江苏省","属地签收","提交核查结论","上传回传证据","省级复核通过","规则重算并销号","重新流转"];
  const advance=()=>{
    const next=stage===6?0:stage+1;
    setStages({...stages,[selected]:next});
    notify(stage===6?`${order.id} 已恢复为待下发状态`:`${order.id}：${actions[stage]}完成`);
  };
  const comparison=stage>=4?order.after:order.before;
  return <>
    <Heading eyebrow="" title="整改闭环" description="总局下发问题，属地核查回传，总局复核并通过规则重算确认整改结果。" aside={<Pill tone="blue">2件待办工单</Pill>}/>
    <section className="order-switch">{(["capital","address"] as WorkOrderKey[]).map(key=>{const item=workOrders[key],s=stages[key];return <button key={key} className={selected===key?"active":""} onClick={()=>{setSelected(key);setDetail("none");}}><div><Pill tone={key==="capital"?"red":"amber"}>{item.path}</Pill><Pill tone={s===6?"green":"blue"}>{stageNames[s]}</Pill></div><b>{item.title}</b><small>{item.id} · {item.owner}</small></button>})}</section>
    <section className="panel rect-task">
      <header><div><span>{order.id} · {order.path}</span><h2>{order.title}</h2><p>{order.finding}</p></div><Pill tone={stage===6?"green":stage<2?"blue":"amber"}>{stageNames[stage]}</Pill></header>
      <div className="order-meta"><div><span>监管标准</span><b>{order.standard}</b></div><div><span>执行规则</span><b>{order.rule}</b></div><div><span>承办单位</span><b>{order.owner}</b></div><div><span>办理时限</span><b>{order.deadline}</b></div></div>
      <div className="stepper" aria-label="工单进度">{order.steps.map((x,i)=><div key={x[0]} className={i<stage?"done":i===stage?"current":""}><i>{i<stage?"✓":i+1}</i><span>{x[0]}</span></div>)}</div>
      <section className="stage-card"><div><span>当前任务</span><h3>{order.steps[stage][0]}</h3><b>{order.steps[stage][1]}</b><p>{order.steps[stage][2]}</p></div><div className="stage-actions">{stage===4&&<button className="return" onClick={()=>{setStages({...stages,[selected]:3});notify(`${order.id} 已退回属地补充材料`);}}>退回补正</button>}<button onClick={advance}>{actions[stage]} →</button></div></section>
      <div className="rect-toolbar"><button className={detail==="evidence"?"active":""} onClick={()=>setDetail(detail==="evidence"?"none":"evidence")}>核查结论与前后对比</button><button className={detail==="record"?"active":""} onClick={()=>setDetail(detail==="record"?"none":"record")}>查看流转记录</button><button onClick={()=>go("evidence")}>查看原始证据</button></div>
    </section>
    {detail==="evidence"&&<section className="rect-detail-grid"><article className="panel block"><div className="section-title"><div><span>属地核查</span><h2>核查与处置结论</h2></div><Pill tone={stage>=3?"green":"gray"}>{stage>=3?"已形成":"等待核查"}</Pill></div><dl className="decision"><div><dt>核查结论</dt><dd>{stage>=3?order.conclusion:"完成属地核查后显示"}</dd></div><div><dt>处置方式</dt><dd>{stage>=4?order.correction:"核查结论确认后分类处置"}</dd></div></dl></article><article className="panel block"><div className="section-title"><div><span>整改校验</span><h2>{stage>=4?"整改后的重算结果":"命中时字段快照"}</h2></div><Pill tone={stage>=4?"green":"amber"}>{stage>=4?"整改后":"整改前"}</Pill></div><div className="compare-fields">{comparison.map(([a,b])=><div key={a}><span>{a}</span><strong>{b}</strong></div>)}</div></article></section>}
    {detail==="record"&&<section className="panel audit-panel compact-audit"><div className="section-title"><div><span>流转记录</span><h2>工单全过程留痕</h2></div></div><div className="audit-list">{order.steps.map((x,i)=><div key={x[0]} className={i<=stage?"visible":"pending"}><i>{i<stage?"✓":i===stage?"●":"○"}</i><span><b>{x[0]}</b><small>{x[1]} · {x[2]}</small></span><em>{i<stage?"已完成":i===stage?"当前环节":"待办理"}</em></div>)}</div></section>}
  </>;
}

function RuleGovernance({notify,openEvidence}:{notify:(m:string)=>void;openEvidence:(k:ClueKey)=>void}) {
  const [filter,setFilter]=useState("全部");
  const rows=useMemo(()=>rules.filter(r=>filter==="全部"||r[2]===filter),[filter]);
  return <>
    <Heading eyebrow="RULE EXECUTION" title="规则执行与治理" description="这里是统一监管标准的机器执行层：规则存库并独立版本化，引擎只解释执行。" aside={<Pill tone="green">20条规则在库</Pill>}/>
    <section className="kpis"><article><span>法定强制</span><strong>14<small> 条</small></strong><p>有法条锚点</p></article><article><span>统计异常</span><strong>3<small> 条</small></strong><p>依赖基线与时间窗</p></article><article><span>规范性 / 情报</span><strong>3<small> 条</small></strong><p>只打标或人工复核</p></article><article><span>处置分布</span><strong>3 / 11 / 6</strong><p>硬阻断 / 人工复核 / 仅打标</p></article></section>
    <section className="filterbar rule-filter">{["全部","法定强制","统计异常","规范性","情报线索"].map(x=><button className={filter===x?"active":""} onClick={()=>setFilter(x)} key={x}>{x}</button>)}</section>
    <section className="panel rule-table"><div className="rule-row head"><span>规则</span><span>类型</span><span>处置</span><span>当前命中</span><span>状态</span><span>操作</span></div>{rows.map(r=><div className="rule-row" key={r[0]}><span><b>{r[1]}</b><small>{r[0]} · v1.0</small></span><span><Pill tone={r[2]==="法定强制"?"red":r[2]==="统计异常"?"amber":"blue"}>{r[2]}</Pill></span><span>{r[3]}</span><span><strong>{r[4]}</strong> 条</span><span><Pill tone={r[0]==="R-ZS-02"?"amber":"green"}>{r[0]==="R-ZS-02"?"阈值待真数校准":"运行中"}</Pill></span><button onClick={()=>{if(r[0]==="R-ZS-02")openEvidence("address");else if(r[0]==="R-CZ-01")openEvidence("capital");else if(r[0]==="R-JY-01")openEvidence("license");else notify(`${r[0]}：当前命中${r[4]}条标签实例`);}}>查看 →</button></div>)}</section>
    <section className="rule-loop"><div><b>1</b><strong>规则发布</strong><small>逻辑、参数、法源和版本入库</small></div><i>→</i><div><b>2</b><strong>解释执行</strong><small>生成标签与证据</small></div><i>→</i><div><b>3</b><strong>人工复核</strong><small>成立或误报</small></div><i>→</i><div><b>4</b><strong>实测治理</strong><small>precision、阈值与处置调整</small></div><i>↻</i></section>
  </>;
}

function Assistant({notify}:{notify:(m:string)=>void}) {
  const [input,setInput]=useState("");
  const [messages,setMessages]=useState<Array<{role:"user"|"assistant";text:string}>>([{role:"assistant",text:"您好，我是登记智鉴助手。您可以查询法规政策、监管指标、预警线索和整改进度。"}]);
  const answerFor=(question:string)=>{
    if(question.includes("直播")||question.includes("许可"))return "直播电商专题共识别14家相关主体，其中5家命中“许可项无批准文件”，占35.71%。可继续进入监测预警查看具体企业和字段证据。";
    if(question.includes("住所")||question.includes("地址"))return "当前发现2个住所聚集预警地址。其中A32-00418同址主体50户、近30日新增50户，已进入属地核查，需排除合法集群登记情形。";
    if(question.includes("资本")||question.includes("认缴"))return "当前注册资本一致性线索30条。样例企业登记注册资本100万元、股东认缴合计148万元，差额48万元，等待属地调取章程和申报材料核查。";
    if(question.includes("工单")||question.includes("整改")||question.includes("进度"))return "当前有2件整改工单，分别对应企业数据整改和规则误报治理。工单依次经过下发、签收、核查、回传、复核、重算和销号。";
    if(question.includes("公司法")||question.includes("法规"))return "《中华人民共和国公司法》第47条规定，有限责任公司股东认缴的出资额应当按照公司章程规定，自公司成立之日起五年内缴足。";
    return "您可以换一种方式提问，例如：‘住所聚集预警有哪些？’‘直播电商许可缺失率是多少？’或‘整改工单现在到哪一步？’";
  };
  const send=(preset?:string)=>{const question=(preset??input).trim();if(!question){notify("请输入问题");return;}setMessages(items=>[...items,{role:"user",text:question},{role:"assistant",text:answerFor(question)}]);setInput("");};
  return <>
    <Heading eyebrow="" title="智能助手" description="直接提问，即时查询登记法规、监测指标、预警线索和整改进度。" aside={<Pill tone="green">在线</Pill>}/>
    <section className="chatbot panel"><header><div className="chat-avatar">智</div><div><b>登记智鉴助手</b><span><i className="dot"/> 在线</span></div></header><div className="quick-questions">{["住所聚集预警有哪些？","直播电商许可缺失率是多少？","整改工单现在到哪一步？"].map(q=><button key={q} onClick={()=>send(q)}>{q}</button>)}</div><div className="chat-messages">{messages.map((message,i)=><div key={i} className={`chat-message ${message.role}`}><span>{message.role==="assistant"?"智":"我"}</span><p>{message.text}</p></div>)}</div><form className="chat-input" onSubmit={e=>{e.preventDefault();send();}}><input value={input} onChange={e=>setInput(e.target.value)} placeholder="请输入您想查询的问题…" aria-label="输入问题"/><button type="submit">发送</button></form></section>
  </>;
}
