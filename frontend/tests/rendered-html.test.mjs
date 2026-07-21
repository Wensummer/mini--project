import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the monitoring workflow and project boundary", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>登记智鉴｜企业登记合规监测<\/title>/);
  assert.match(html, /监管总览/);
  assert.match(html, /标准规则/);
  assert.match(html, /监测预警/);
  assert.match(html, /整改闭环/);
  assert.match(html, /智能助手/);
  assert.doesNotMatch(html, /项目说明|打开老师汇报页|合成数据演示/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("all visible JSX buttons declare an action", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const openings = page.match(/<button\b[\s\S]*?>/g) ?? [];
  assert.ok(openings.length >= 30, "expected the interactive dashboard controls");
  const inert = openings.filter((tag) => !/onClick\s*=|type\s*=\"submit\"/.test(tag));
  assert.deepEqual(inert, [], `inert buttons found:\n${inert.join("\n")}`);
});

test("keeps the roadshow system focused on monitoring and handling", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /核心业务闭环/);
  assert.match(page, /监管总览/);
  assert.match(page, /标准规则/);
  assert.match(page, /监测预警/);
  assert.match(page, /整改闭环/);
  assert.match(page, /登记智鉴助手/);
  assert.match(page, /全国统一部分/);
  assert.match(page, /属地可配置部分/);
  assert.match(page, /企业数据整改/);
  assert.match(page, /误报反馈与规则治理/);
  assert.match(page, /下发至江苏省/);
  assert.match(page, /规则重算并销号/);
  assert.match(page, /三级研判与预警处置/);
  assert.match(page, /预警不是违法认定/);
  assert.match(page, /宏观发现/);
  assert.match(page, /中观定位/);
  assert.match(page, /微观核验/);
  assert.match(page, /进入对应整改工单/);
  assert.doesNotMatch(page, /title="项目说明"|打开老师汇报页|合成数据|非真实工单/);
});

test("briefing deck separates the interactive rectification demo from the unbuilt backend", async () => {
  const html = await readFile(new URL("../public/briefing.html", import.meta.url), "utf8");
  assert.equal((html.match(/class="slide"/g) ?? []).length, 8);
  assert.match(html, /整改双闭环已有可交互前端样例/);
  assert.match(html, /确定性校验、统计计算和关系分析/);
  assert.match(html, /20规则\/20标签/);
  assert.match(html, /总局不直接改地方登记数据/);
  assert.match(html, /当前尚无真实工单数据表、账号权限和业务接口/);
  assert.match(html, /误报只改规则\/阈值/);
  assert.match(html, /打印 \/ PDF/);
});
