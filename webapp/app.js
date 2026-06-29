/* 광동 품질·시험 통합 대시보드 — 프론트엔드 (vanilla JS, 디자인 1:1 재현) */
'use strict';

const S = {
  nav: 'oot',
  // OOT
  ootTestType: '완제품', ootProducts: [], query: '', open: false,
  code: null, productName: '', lotSummary: null, years: ['전체'],
  yearFilter: '전체', lotQuery: '', lot: null,
  // Stability
  stabTestType: '시판후 안정성시험(Ongoing Stability)', stabProducts: [],
  stabCode: null, stabName: '', stabFromOot: false,
  specLow: '90', specHigh: '150', method: 'pooled', stabTestItem: null,
  stabData: null, stabLoading: false, stabTables: null, stabTablesKey: '', stabBatch: null,
  // Alarm
  alarm: { policy: '관리이탈만', recipients: [], interval: '10분', night: true },
  alarmAuthed: false, alarmFromEnv: false, alarmDirty: false,
};
const STAB_TYPES_FALLBACK = ['시판후 안정성시험(Ongoing Stability)', '장기 안정성시험(Long Term)',
  '가속 안정성시험(Acclerated)', '4b장기 안정성시험(LT4b)'];
let OOT_TEST_TYPES = ['완제품'];

const $ = (sel, root = document) => root.querySelector(sel);
async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status); return r.json(); }
async function postJSON(url, body) { const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return r.json(); }
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function fmt(n, d) { if (n == null || isNaN(n)) return '—'; return Number(n).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }); }
function sigStr(z) { if (z == null || isNaN(z)) return '—'; return (z >= 0 ? '+' : '−') + fmt(Math.abs(z), 2) + 'σ'; }
const MONO = "'JetBrains Mono',monospace";

/* ============================ SIDEBAR ============================ */
function navBtn(active) {
  return 'display:flex;align-items:center;gap:11px;width:100%;text-align:left;padding:11px 12px;border:none;border-radius:10px;cursor:pointer;font-family:inherit;font-size:13.5px;position:relative;margin-bottom:4px;' +
    (active ? 'background:linear-gradient(90deg,rgba(229,49,15,.26),rgba(229,49,15,.10));color:#fff;font-weight:600'
            : 'background:transparent;color:#aeb9cc;font-weight:500');
}
const navBar = (a) => a ? 'position:absolute;left:0;top:9px;bottom:9px;width:3px;border-radius:0 3px 3px 0;background:#FF6A2C' : 'display:none';
const navIcon = (a) => a ? '#FF8A5C' : '#7d8aa3';

function sidebar() {
  const n = S.nav;
  return `<aside style="flex:0 0 236px;align-self:flex-start;position:sticky;top:0;height:100vh;background:#16181d;display:flex;flex-direction:column;padding:22px 16px;color:#aeb9cc">
    <div data-act="home" title="홈으로" style="display:flex;align-items:center;gap:11px;padding:4px 6px 0;cursor:pointer">
      <div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(118deg,#E5310F,#FF6A2C);display:flex;align-items:center;justify-content:center;flex:0 0 auto;box-shadow:0 4px 12px rgba(229,49,15,.4)">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"><path d="M4 19V9"></path><path d="M10 19V5"></path><path d="M16 19v-7"></path><path d="M21 19H3"></path></svg>
      </div>
      <div><div style="color:#fff;font-weight:700;font-size:14.5px;letter-spacing:-.01em">광동제약</div>
        <div style="font-size:11px;color:#7d8aa3;font-weight:500">품질·시험 플랫폼</div></div>
    </div>
    <button data-act="home" style="margin-top:16px;display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:10px;border:1px solid #2c2f38;border-radius:10px;background:#20232b;color:#cdd8ea;font-size:13px;font-weight:600;cursor:pointer">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FF8A5C" stroke-width="2.2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M9 22V12h6v10"></path></svg>홈</button>
    <div style="margin-top:18px">
      <div style="font-size:10.5px;font-weight:600;letter-spacing:.08em;color:#5d6b86;padding:0 8px 10px">모니터링</div>
      <button data-act="nav" data-nav="oot" style="${navBtn(n === 'oot')}"><span style="${navBar(n === 'oot')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'oot')}" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>OOT 빠른 조회</button>
      <button data-act="nav" data-nav="stability" style="${navBtn(n === 'stability')}"><span style="${navBar(n === 'stability')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'stability')}" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 7-6 7-4-3-4 5"></path></svg>안정성 회귀분석</button>
    </div>
    <div style="margin-top:18px">
      <div style="font-size:10.5px;font-weight:600;letter-spacing:.08em;color:#5d6b86;padding:0 8px 10px">설정</div>
      <button data-act="nav" data-nav="alarm" style="${navBtn(n === 'alarm')}"><span style="${navBar(n === 'alarm')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'alarm')}" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>알림 설정</button>
    </div>
    <button data-act="refresh" style="margin-top:22px;display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:11px;border:1px solid #2c2f38;border-radius:10px;background:#20232b;color:#cdd8ea;font-size:13px;font-weight:600;cursor:pointer">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FF8A5C" stroke-width="2.2"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>데이터 새로고침</button>
    <div style="margin-top:auto;background:#1f2128;border:1px solid #2c2f38;border-radius:12px;padding:13px 14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px"><span style="width:7px;height:7px;border-radius:50%;background:#34d27b;animation:pulseDot 1.8s infinite"></span><span style="font-size:12px;font-weight:600;color:#dbe3f0">알람 감시 정상</span></div>
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px"><span style="color:#6b7a96">데이터원</span><span style="color:#c3cee0;font-family:${MONO}">OOT_추출용</span></div>
      <div style="display:flex;justify-content:space-between;font-size:11px"><span style="color:#6b7a96">서버</span><span style="color:#c3cee0;font-family:${MONO}">tableau.ekdp</span></div>
    </div>
  </aside>`;
}

function topbar() {
  const crumb = S.nav === 'oot' ? ['OOT 관리', '빠른 조회'] : S.nav === 'stability' ? ['안정성', '회귀분석'] : ['설정', '알림'];
  return `<header style="position:sticky;top:0;z-index:20;background:rgba(236,239,244,.82);backdrop-filter:blur(10px);border-bottom:1px solid #dde2ea;padding:13px 30px;display:flex;align-items:center;gap:16px">
    <div style="display:flex;align-items:center;gap:8px;font-size:13px"><span style="color:#8a94a6">${esc(crumb[0])}</span><span style="color:#c2cad6">/</span><span style="font-weight:600;color:#27303f">${esc(crumb[1])}</span></div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:12px">
      <div style="display:flex;align-items:center;gap:9px;background:#fff;border:1px solid #dde2ea;border-radius:10px;padding:7px 13px"><span style="width:7px;height:7px;border-radius:50%;background:#22c55e;animation:pulseDot 1.8s infinite"></span><span style="font-size:12.5px;font-weight:600;color:#15803d">실시간 알람 감시 중</span></div>
    </div>
  </header>`;
}

function pageHeader(eyebrow, title, sub, subText) {
  return `<div style="margin-bottom:20px">
    <div style="font-size:11.5px;font-weight:600;letter-spacing:.04em;color:#E5310F;margin-bottom:8px">${eyebrow}</div>
    <h1 style="margin:0;font-size:26px;font-weight:700;letter-spacing:-.02em;display:flex;align-items:baseline;gap:11px">${title}<span style="color:#8a94a6;font-weight:500;font-size:15px">${sub}</span></h1>
    ${subText ? `<div style="font-size:12.5px;color:#9aa4b4;margin-top:7px">${subText}</div>` : ''}
  </div>`;
}

/* ============================ OOT PAGE ============================ */
function ootDropdown() {
  const q = (S.query || '').trim().toLowerCase();
  const matchAll = S.code && S.productName && (S.query === S.code || S.query === S.productName);
  if (!S.open || matchAll) return '';
  const opts = S.ootProducts.filter(p => !q || p.code.includes(q) || p.name.toLowerCase().includes(q)).slice(0, 8);
  if (!opts.length) return '';
  return `<div style="position:absolute;top:100%;left:0;right:0;margin-top:6px;background:#fff;border:1px solid #dde2ea;border-radius:12px;box-shadow:0 16px 40px rgba(20,30,50,.16);z-index:30;overflow:hidden;max-height:300px;overflow-y:auto">
    ${opts.map(o => `<div data-act="pickProduct" data-code="${esc(o.code)}" data-name="${esc(o.name)}" style="display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;border-bottom:1px solid #f2f4f8" data-hover>
      <span style="font-family:${MONO};font-weight:600;font-size:13px;color:#E5310F;min-width:52px">${esc(o.code)}</span>
      <span style="font-size:13.5px;color:#27303f;flex:1">${esc(o.name)}</span></div>`).join('')}
  </div>`;
}

function ootLotControls() {
  if (!S.code || !S.lotSummary) return `<div style="font-size:13px;color:#9aa4b4;padding:2px 0">품목코드를 먼저 선택하세요.</div>`;
  const segBase = `font-family:${MONO};font-size:12px;font-weight:600;padding:5px 11px;border-radius:7px;cursor:pointer;border:none`;
  const yearChips = S.years.map(y => {
    const sel = S.yearFilter === y;
    const st = sel ? segBase + ';background:#fff;color:#27303f;box-shadow:0 1px 2px rgba(20,30,50,.12)' : segBase + ';background:transparent;color:#7a8699';
    return `<button data-act="pickYear" data-year="${esc(y)}" style="${st}">${esc(y)}</button>`;
  }).join('');
  const lots = S.lotSummary.lots;
  return `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:13px">
      <span style="font-size:11px;font-weight:600;color:#8a94a6;letter-spacing:.02em">제조번호 (LOT)</span>
      <div style="display:flex;gap:3px;background:#eef1f6;border:1px solid #e2e7ef;border-radius:9px;padding:3px">${yearChips}</div>
      <div style="position:relative;margin-left:2px">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#a6b0c0" stroke-width="2.2" style="position:absolute;left:10px;top:50%;transform:translateY(-50%)"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
        <input id="lot-search" value="${esc(S.lotQuery)}" placeholder="LOT 검색" style="width:128px;padding:7px 10px 7px 29px;border:1px solid #d7dce4;border-radius:8px;font-size:12.5px;font-family:${MONO};outline:none;background:#fff"></div>
      <span id="lot-count" style="margin-left:auto;font-size:11.5px;color:#9aa4b4;font-family:${MONO}">표시 ${lots.length} / 전체 ${lots.length}</span>
    </div>
    <div class="lotscroll" style="max-height:104px;overflow-y:auto;border:1px solid #e7ebf1;border-radius:10px;background:#fff;padding:11px 12px"><div id="lot-chips" style="display:flex;gap:7px;flex-wrap:wrap">${lotChips()}</div></div>`;
}

function lotChips() {
  const lots = (S.lotSummary ? S.lotSummary.lots : []).filter(l =>
    (S.yearFilter === '전체' || l.year === S.yearFilter) &&
    (!S.lotQuery || l.lot.toLowerCase().includes(S.lotQuery.toLowerCase())));
  if (!lots.length) return `<div style="font-size:12.5px;color:#9aa4b4;padding:6px 2px">검색 결과 없음</div>`;
  const base = `font-family:${MONO};font-size:12.5px;font-weight:600;padding:7px 12px;border-radius:8px;cursor:pointer`;
  return lots.map(l => {
    const sel = l.lot === S.lot, flag = l.flagged;
    let st = sel ? base + ';border:1px solid #E5310F;background:#E5310F;color:#fff'
      : flag ? base + ';border:1px solid #f5c98f;background:#fffaf0;color:#b45309'
        : base + ';border:1px solid #e0e5ec;background:#fff;color:#46536a';
    return `<button data-act="pickLot" data-lot="${esc(l.lot)}" style="${st}">${flag ? '⚠ ' : ''}${esc(l.lot)}</button>`;
  }).join('');
}

function normalItemsTable(lot) {
  const items = lot.normalItems || [];
  if (!items.length) return '';
  const COLS = '2fr 1fr 1fr 1fr .9fr .8fr';
  const rows = items.map(it => `<div style="display:grid;grid-template-columns:${COLS};border-top:1px solid #f2f4f8">
    <div style="padding:10px 14px;font-size:13px;font-weight:600;color:#27303f">${esc(it.name)}</div>
    <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-size:13px;color:#27303f">${fmt(it.val, 2)}</div>
    <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-size:12.5px;color:#5b6573">${fmt(it.mean, it.mean != null && it.mean < 10 ? 3 : 1)}</div>
    <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-size:12.5px;color:#5b6573">${fmt(it.sd, it.sd != null && it.sd < 10 ? 3 : 1)}</div>
    <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-size:12.5px;font-weight:600;color:#16a34a">${sigStr(it.z)}</div>
    <div style="padding:10px 14px"><span style="font-size:10.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:#ecfdf3;color:#15803d">정상</span></div></div>`).join('');
  return `<div style="margin-top:18px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px"><span style="font-size:14.5px;font-weight:700">정상 항목 시험결과</span><span style="font-family:${MONO};font-size:12px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">${items.length}</span></div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden;background:#fff">
      <div style="display:grid;grid-template-columns:${COLS};background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:9px 14px">시험항목</div><div style="padding:9px 14px;text-align:right">결과값</div><div style="padding:9px 14px;text-align:right">평균 μ</div><div style="padding:9px 14px;text-align:right">표준편차 σ</div><div style="padding:9px 14px;text-align:right">σ편차</div><div style="padding:9px 14px">판정</div></div>
      ${rows}</div>
    <div style="font-size:11px;color:#9aa4b4;margin-top:8px">σ편차 = (결과값 − μ) / σ · ±2σ 이내 정상 · 정성항목(미생물·확인·성상 등)은 σ 판정 대상이 아니어 제외</div></div>`;
}

function ootResults() {
  const lot = S.lot && S.lotSummary ? S.lotSummary.lots.find(l => l.lot === S.lot) : null;
  if (!lot) {
    return `<div style="background:#fff;border:1px dashed #cfd6e0;border-radius:16px;padding:64px 24px;text-align:center">
      <div style="width:64px;height:64px;border-radius:50%;background:#eef1f6;display:flex;align-items:center;justify-content:center;margin:0 auto"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg></div>
      <div style="font-size:15.5px;font-weight:600;color:#5b6573;margin-top:16px">LOT을 선택하면 판정 결과가 표시됩니다</div>
      <div style="font-size:13px;color:#9aa4b4;margin-top:6px">완제품 · 품목코드 · 제조번호 순으로 선택하세요</div></div>`;
  }
  const st = lot.crit > 0 ? 'red' : lot.warn > 0 ? 'yellow' : 'green';
  const TH = { red: { bg: '#fef4f4', bd: '#f6c9c9', fg: '#b91c1c' }, yellow: { bg: '#fffcf2', bd: '#f3dd9f', fg: '#b45309' }, green: { bg: '#f1fbf4', bd: '#bcecca', fg: '#15803d' } }[st];
  const headline = st === 'red' ? `관리이탈 ${lot.crit}건 — 확인 필요` : st === 'yellow' ? `주의 ${lot.warn}건 발생` : '이상 없음';
  const icon = st === 'red'
    ? `<div style="width:48px;height:48px;border-radius:13px;background:#fde0e0;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.2"><path d="M12 8v5"></path><circle cx="12" cy="16.5" r=".6" fill="#dc2626"></circle><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg></div>`
    : st === 'yellow'
      ? `<div style="width:48px;height:48px;border-radius:13px;background:#fdecc8;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.2"><path d="M12 9v4"></path><circle cx="12" cy="16.5" r=".6" fill="#d97706"></circle><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg></div>`
      : `<div style="width:48px;height:48px;border-radius:13px;background:#cdf2da;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.4"><path d="M5 12.5 10 17.5 19.5 7"></path></svg></div>`;
  const kpiBox = 'background:rgba(255,255,255,.6);border:1px solid rgba(20,30,50,.06);border-radius:11px;padding:9px 14px;min-width:66px;text-align:center';
  const kpi = (lab, val, col) => `<div style="${kpiBox}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">${lab}</div><div style="font-family:${MONO};font-size:19px;font-weight:600;color:${col}">${val}</div></div>`;

  const items = lot.items.map(it => {
    const crit = it.status === '관리이탈';
    const z = it.z == null ? 0 : it.z, pos = Math.max(2, Math.min(98, (z + 3) / 6 * 100));
    const C = crit ? { dot: '#ef4444', bg: '#fef2f2', bd: '#fbcaca', tagBg: '#fde0e0', tagFg: '#b91c1c' } : { dot: '#f59e0b', bg: '#fffbeb', bd: '#fbe2a8', tagBg: '#fdedc4', tagFg: '#b45309' };
    return `<div style="display:block;background:${C.bg};border:1px solid ${C.bd};border-radius:13px;padding:16px 17px">
      <div style="display:flex;align-items:center;gap:10px"><span style="width:10px;height:10px;border-radius:50%;flex:0 0 auto;background:${C.dot}"></span>
        <span style="font-size:15px;font-weight:600">${esc(it.name)}</span>
        <span style="margin-left:auto;font-size:11.5px;font-weight:600;padding:4px 11px;border-radius:999px;background:${C.tagBg};color:${C.tagFg}">${crit ? '관리이탈 · ±3σ 초과' : '주의 · ±2σ~±3σ'}</span></div>
      <div style="display:flex;align-items:baseline;gap:20px;margin-top:12px;flex-wrap:wrap">
        <div><span style="font-size:11px;color:#8a94a6;margin-right:7px">결과값</span><span style="font-family:${MONO};font-size:23px;font-weight:600;color:#27303f">${fmt(it.val, 2)}</span></div>
        <div style="font-family:${MONO};font-size:13px;color:#5b6573">μ ${fmt(it.mean, it.mean != null && it.mean < 10 ? 3 : 1)}</div>
        <div style="font-family:${MONO};font-size:13px;color:#5b6573">σ ${fmt(it.sd, it.sd != null && it.sd < 10 ? 3 : 1)}</div>
        <div style="font-family:${MONO};font-size:14px;font-weight:600;color:${C.dot}">${sigStr(it.z)}</div></div>
      <div style="margin-top:15px"><div style="position:relative;height:9px;border-radius:5px;background:linear-gradient(90deg,#fbcaca 0 8.33%,#fde6b0 8.33% 16.67%,#cfecd9 16.67% 83.33%,#fde6b0 83.33% 91.67%,#fbcaca 91.67% 100%)">
        <span style="position:absolute;left:50%;top:-2px;width:1.5px;height:13px;background:#94a3b8;transform:translateX(-50%)"></span>
        <span style="position:absolute;top:-3px;width:3px;height:15px;border-radius:2px;transform:translateX(-50%);left:${pos}%;background:${C.dot}"></span></div>
        <div style="display:flex;justify-content:space-between;margin-top:6px;font-family:${MONO};font-size:10px;color:#9aa4b4"><span>−3σ</span><span>μ</span><span>+3σ</span></div></div></div>`;
  }).join('');

  const ootBlock = lot.items.length ? `<div style="margin-top:18px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px"><span style="font-size:14.5px;font-weight:700">OOT 항목</span><span style="font-family:${MONO};font-size:12px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">${lot.items.length}</span></div>
      <div style="display:flex;flex-direction:column;gap:10px">${items}</div>
      <div style="font-size:12px;color:#9aa4b4;margin-top:12px;line-height:1.5">정상 ${lot.normal}개 항목 · 정성항목(미생물·확인·성상 등) ${lot.qual}개 σ 판정 제외</div></div>`
    : `<div style="margin-top:18px;background:#fff;border:1px solid #e3e7ee;border-radius:13px;padding:16px 18px;display:flex;align-items:center;gap:10px">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.4"><path d="M5 12.5 10 17.5 19.5 7"></path></svg>
      <span style="font-size:14px;font-weight:600;color:#15803d">정상 ${lot.normal}개 항목 · OOT 없음</span>
      <span style="color:#9aa4b4;font-weight:500;margin-left:auto;font-size:12.5px">정성항목 ${lot.qual}개 제외</span></div>`;

  return `<div style="display:flex;gap:18px;align-items:center;padding:22px 24px;border-radius:16px;border:1px solid ${TH.bd};background:${TH.bg};box-shadow:0 1px 3px rgba(20,30,50,.05);flex-wrap:wrap">
      ${icon}
      <div style="flex:1"><div style="color:${TH.fg};font-size:25px;font-weight:700;letter-spacing:-.015em;line-height:1.2">${headline}</div>
        <div style="font-size:13.5px;color:#5b6573;margin-top:7px">LOT ${esc(lot.lot)} · ${esc(S.productName)} · 품목코드 ${esc(S.code)}</div></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-self:stretch">
        ${kpi('관리이탈', lot.crit, '#dc2626')}${kpi('주의', lot.warn, '#d97706')}${kpi('정상', lot.normal, '#16a34a')}${kpi('정성 제외', lot.qual, '#94a3b8')}</div></div>
    <div style="display:flex;align-items:center;gap:12px;margin:13px 2px 0;flex-wrap:wrap">
      <button data-act="jumpStab" style="display:flex;align-items:center;gap:8px;padding:9px 15px;border:1.5px solid #E5310F;border-radius:10px;background:#fff;color:#E5310F;font-size:12.5px;font-weight:600;cursor:pointer">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 7-6 7-4-3-4 5"></path></svg>이 품목 안정성 분석</button>
      <a href="${'http://tableau.ekdp.com/#/home'}" target="_blank" style="font-size:12.5px;color:#8a94a6;display:flex;align-items:center;gap:6px;text-decoration:none">상세 추이·관리도는 Tableau에서 확인<span style="color:#E5310F;font-weight:600">→</span></a></div>
    ${ootBlock}${normalItemsTable(lot)}`;
}

function ootRail() {
  const policyChip = S.alarm.policy === '관리이탈만' ? '관리이탈(±3σ) 발생 시 메일 발송' : '관리이탈·주의 발송';
  return `<aside style="flex:1 1 320px;min-width:300px;display:flex;flex-direction:column;gap:14px">
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;padding:16px 18px;box-shadow:0 1px 3px rgba(20,30,50,.05)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:13px"><span style="width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulseDot 1.8s infinite"></span><span style="font-weight:700;font-size:14.5px">실시간 OOT 알람</span><span style="margin-left:auto;font-size:11px;font-weight:600;color:#15803d;background:#ecfdf3;padding:3px 9px;border-radius:999px">감시 중</span></div>
      <div style="display:flex;flex-direction:column;gap:9px">
        <div style="display:flex;justify-content:space-between;font-size:12.5px"><span style="color:#8a94a6">감시 대상</span><span style="font-weight:600">전체(모든 시험종류)</span></div>
        <div style="display:flex;justify-content:space-between;font-size:12.5px"><span style="color:#8a94a6">조회 주기</span><span style="font-weight:600;font-family:${MONO}">${esc(S.alarm.interval)}</span></div></div>
      <div style="margin-top:12px;padding-top:13px;border-top:1px solid #eef1f5">
        <div style="font-size:11px;color:#8a94a6;margin-bottom:7px">발송 정책</div>
        <span style="font-size:12.5px;font-weight:600;color:#E5310F;background:#fdece8;padding:5px 11px;border-radius:8px">${esc(policyChip)}</span>
        <div style="font-size:11px;color:#9aa4b4;margin-top:11px;line-height:1.55">신규 OOT만 발송(중복 자동 차단). 실시간성은 Tableau extract 갱신 주기에 종속됩니다.</div></div></div>
  </aside>`;
}

function ootPage() {
  const nameColor = S.productName ? '#27303f' : '#b8c0cc';
  return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', 'OOT 빠른 조회', 'Out Of Trend · LOT 판정',
      `데이터 출처: Tableau <span style="font-family:${MONO}">OOT_추출용</span> · ${esc(S.ootTestType)} 온디맨드 조회`)}
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);position:relative;z-index:5">
      <div style="padding:18px 22px;display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end">
        <div style="flex:0 0 auto"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">시험종류</span>
          <div style="position:relative"><select data-act="ootTestType" style="appearance:none;padding:10px 34px 10px 14px;background:#eef1f6;border:1px solid #dde3ec;color:#3a4658;font-size:14px;font-weight:600;border-radius:10px;cursor:pointer">${OOT_TEST_TYPES.map(t => `<option ${t === S.ootTestType ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div></div>
        <div style="flex:1 1 340px;min-width:260px;position:relative">
          <span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:flex;gap:7px;align-items:center">품목코드<span style="background:#fdece8;color:#E5310F;font-weight:600;padding:1px 7px;border-radius:5px;font-size:10px">검색형 · ${S.ootProducts.length.toLocaleString()}개</span></span>
          <input id="oot-search" value="${esc(S.query)}" placeholder="코드 또는 품목명 입력 (예: 21039)" autocomplete="off" style="width:100%;padding:11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:14px;font-family:${MONO};color:#27303f;outline:none;background:#fff">
          <div id="oot-dropdown">${ootDropdown()}</div></div>
        <div style="flex:1 1 260px;min-width:200px"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">품목명 <span style="color:#b8c0cc;font-weight:500">(자동)</span></span>
          <div id="oot-pname" style="width:100%;padding:11px 13px;border:1px solid #e7ebf1;border-radius:10px;font-size:14px;background:#f8fafc;min-height:43px;color:${nameColor}">${esc(S.productName || '품목코드 선택 시 표시')}</div></div>
      </div>
      <div id="oot-lot-section" style="border-top:1px solid #eef1f5;background:#fafbfd;padding:16px 22px;border-radius:0 0 16px 16px">${ootLotControls()}</div>
    </div>
    <div style="display:flex;gap:18px;margin-top:18px;align-items:flex-start;flex-wrap:wrap">
      <div id="oot-results" style="flex:1 1 580px;min-width:340px">${ootResults()}</div>
      ${ootRail()}
    </div>
  </div>`;
}

/* ============================ STABILITY PAGE ============================ */
function buildChartSVG(A) {
  const W = 640, H = 380, ml = 46, mr = 20, mt = 18, mb = 42, pw = W - ml - mr, ph = H - mt - mb;
  const batches = A.batches.filter(b => b.slope != null);
  if (!batches.length) return `<div style="padding:40px;text-align:center;color:#9aa4b4;font-size:13px">회귀 가능한 데이터가 없습니다.</div>`;
  const allPts = batches.flatMap(b => b.pts);
  const allShelf = batches.map(b => b.shelf).filter(s => s != null);
  const maxShelf = allShelf.length ? Math.max(...allShelf) : 24;
  const lastT = Math.max(...allPts.map(p => p[0]));
  const approved = A.approvedMonths || 0;   // 허가 유효기간(개월) — 가이드선·범위에 포함
  let xMax = Math.max(maxShelf, lastT, approved) * 1.12; xMax = Math.ceil(xMax / 3) * 3; if (xMax < 24) xMax = 24;
  const specLow = A.specLow;
  const yMin = Math.min((specLow != null ? specLow - 1 : Infinity), ...allPts.map(p => p[1])) - 1;
  const yMax = Math.max(...allPts.map(p => p[1])) + 1.5;
  const xp = x => ml + x / xMax * pw, yp = y => mt + (yMax - y) / (yMax - yMin) * ph;
  const clampY = y => Math.min(yMax, Math.max(yMin, y));
  const ticks = [0, 3, 6, 9, 12, 18, 24, 36, 48, 60].filter(t => t <= xMax);
  const L = [];
  const yStart = Math.ceil(yMin / 2) * 2;
  for (let gy = yStart; gy <= yMax; gy += 2) {
    L.push(`<line x1="${ml}" x2="${W - mr}" y1="${yp(gy)}" y2="${yp(gy)}" stroke="#eef1f5" stroke-width="1"/>`);
    L.push(`<text x="${ml - 7}" y="${yp(gy) + 3.5}" text-anchor="end" font-size="10" font-family="JetBrains Mono" fill="#9aa4b4">${gy}</text>`);
  }
  ticks.forEach(t => {
    L.push(`<line x1="${xp(t)}" x2="${xp(t)}" y1="${mt}" y2="${H - mb}" stroke="#f4f6f9" stroke-width="1"/>`);
    L.push(`<text x="${xp(t)}" y="${H - mb + 16}" text-anchor="middle" font-size="10" font-family="JetBrains Mono" fill="#9aa4b4">${t}</text>`);
  });
  L.push(`<text x="${ml + pw / 2}" y="${H - 6}" text-anchor="middle" font-size="10.5" fill="#8a94a6">시점 (개월)</text>`);
  if (specLow != null && specLow >= yMin && specLow <= yMax) {
    L.push(`<line x1="${ml}" x2="${W - mr}" y1="${yp(specLow)}" y2="${yp(specLow)}" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="6 4"/>`);
    L.push(`<text x="${W - mr - 4}" y="${yp(specLow) - 5}" text-anchor="end" font-size="10" font-weight="600" fill="#dc2626">규격하한 ${specLow}</text>`);
  }
  const worst = A.worst && A.worst.slope != null ? A.worst : null;
  if (worst) {
    const N = 60, up = [], lo = [];
    for (let i = 0; i <= N; i++) { const x = i / N * xMax; const yh = worst.intercept + worst.slope * x; const m = worst.tcrit * worst.se * Math.sqrt(1 / worst.n + (x - worst.mx) ** 2 / worst.sxx); up.push([x, yh + m]); lo.push([x, yh - m]); }
    let d = `M ${xp(up[0][0])} ${yp(clampY(up[0][1]))}`;
    up.forEach(p => d += ` L ${xp(p[0])} ${yp(clampY(p[1]))}`);
    for (let i = lo.length - 1; i >= 0; i--) d += ` L ${xp(lo[i][0])} ${yp(clampY(lo[i][1]))}`;
    d += ' Z';
    L.push(`<path d="${d}" fill="rgba(229,49,15,0.10)" stroke="none"/>`);
  }
  batches.forEach(b => {
    const x0 = 0, x1 = b.shelf != null ? Math.min(b.shelf + 1.5, xMax) : xMax;
    L.push(`<line x1="${xp(x0)}" y1="${yp(b.intercept + b.slope * x0)}" x2="${xp(x1)}" y2="${yp(clampY(b.intercept + b.slope * x1))}" stroke="${b.color}" stroke-width="2"/>`);
  });
  if (worst && worst.shelf != null) {
    const sx = xp(worst.shelf);
    L.push(`<line x1="${sx}" x2="${sx}" y1="${mt}" y2="${H - mb}" stroke="#16a34a" stroke-width="1.5" stroke-dasharray="2 3"/>`);
    L.push(`<text x="${sx}" y="${mt + 12}" text-anchor="middle" font-size="10" font-weight="600" fill="#16a34a">${worst.shelf.toFixed(1)}개월</text>`);
  }
  // 허가 유효기간 가이드 세로선(주황 점선) — 추정 저장수명과 비교용
  if (approved > 0 && approved <= xMax) {
    const ax = xp(approved);
    L.push(`<line x1="${ax}" x2="${ax}" y1="${mt}" y2="${H - mb}" stroke="#d97706" stroke-width="1.5" stroke-dasharray="6 4"/>`);
    L.push(`<text x="${ax}" y="${mt + 26}" text-anchor="middle" font-size="10" font-weight="600" fill="#b45309">허가 ${approved}개월</text>`);
  }
  batches.forEach(b => {
    const sigma = b.se;
    b.pts.forEach(p => {
      const cx = xp(p[0]), cy = yp(clampY(p[1]));
      if (sigma) { const resid = Math.abs(p[1] - (b.intercept + b.slope * p[0])) / sigma; if (resid > 2) L.push(`<circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="${resid > 3 ? '#dc2626' : '#e67e22'}" stroke-width="2.4"/>`); }
      L.push(`<circle cx="${cx}" cy="${cy}" r="4.5" fill="${b.color}" stroke="#fff" stroke-width="1.5"/>`);
    });
  });
  L.push(`<line x1="${ml}" x2="${ml}" y1="${mt}" y2="${H - mb}" stroke="#cdd5e0" stroke-width="1"/>`);
  L.push(`<line x1="${ml}" x2="${W - mr}" y1="${H - mb}" y2="${H - mb}" stroke="#cdd5e0" stroke-width="1"/>`);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">${L.join('')}</svg>`;
}

function buildPlotly(A) {
  const batches = A.batches.filter(b => b.slope != null);
  const allPts = A.batches.flatMap(b => b.pts);
  if (!allPts.length) return null;
  const allShelf = batches.map(b => b.shelf).filter(s => s != null);
  const maxShelf = allShelf.length ? Math.max(...allShelf) : 24;
  const lastT = Math.max(...allPts.map(p => p[0]));
  const approved = A.approvedMonths || 0;
  let xMax = Math.max(maxShelf, lastT, approved) * 1.12; xMax = Math.ceil(xMax / 3) * 3; if (xMax < 24) xMax = 24;
  const specLow = A.specLow;
  const yMin = Math.min((specLow != null ? specLow - 1 : Infinity), ...allPts.map(p => p[1])) - 1;
  const yMax = Math.max(...allPts.map(p => p[1])) + 1.5;
  const ticks = [0, 3, 6, 9, 12, 18, 24, 36, 48, 60].filter(t => t <= xMax);
  const data = [];
  const worst = A.worst && A.worst.slope != null ? A.worst : null;
  if (worst) {
    const N = 60, xs = [], up = [], lo = [];
    for (let i = 0; i <= N; i++) { const x = i / N * xMax; xs.push(x); const yh = worst.intercept + worst.slope * x; const m = worst.tcrit * worst.se * Math.sqrt(1 / worst.n + (x - worst.mx) ** 2 / worst.sxx); up.push(yh + m); lo.push(yh - m); }
    data.push({ x: xs.concat(xs.slice().reverse()), y: up.concat(lo.slice().reverse()), fill: 'toself', fillcolor: 'rgba(229,49,15,0.10)', line: { width: 0 }, mode: 'lines', name: '95% 신뢰구간', hoverinfo: 'skip', type: 'scatter' });
  }
  batches.forEach(b => {
    const x1 = b.shelf != null ? Math.min(b.shelf + 1.5, xMax) : xMax;
    data.push({ x: [0, x1], y: [b.intercept, b.intercept + b.slope * x1], mode: 'lines', line: { color: b.color, width: 2 }, name: '배치 ' + b.batch, legendgroup: b.batch, hoverinfo: 'skip', type: 'scatter' });
  });
  A.batches.forEach(b => {
    data.push({ x: b.pts.map(p => p[0]), y: b.pts.map(p => p[1]), mode: 'markers', marker: { color: b.color, size: 9, line: { color: '#fff', width: 1.5 } }, name: '배치 ' + b.batch, legendgroup: b.batch, showlegend: false, type: 'scatter', hovertemplate: `배치 ${b.batch}<br>%{x}개월 · 함량 %{y}<extra></extra>` });
    if (b.se) {
      const rx = [], ry = [], rc = [];
      b.pts.forEach(p => { const resid = Math.abs(p[1] - (b.intercept + b.slope * p[0])) / b.se; if (resid > 2) { rx.push(p[0]); ry.push(p[1]); rc.push(resid > 3 ? '#dc2626' : '#e67e22'); } });
      if (rx.length) data.push({ x: rx, y: ry, mode: 'markers', marker: { size: 16, color: 'rgba(0,0,0,0)', line: { color: rc, width: 2.4 } }, showlegend: false, hoverinfo: 'skip', type: 'scatter' });
    }
  });
  const shapes = [], annotations = [];
  if (specLow != null) { shapes.push({ type: 'line', x0: 0, x1: xMax, y0: specLow, y1: specLow, line: { color: '#dc2626', width: 1.5, dash: 'dash' } }); annotations.push({ x: xMax, y: specLow, xanchor: 'right', yanchor: 'bottom', text: '규격하한 ' + specLow, showarrow: false, font: { size: 10, color: '#dc2626' } }); }
  if (worst && worst.shelf != null) { shapes.push({ type: 'line', x0: worst.shelf, x1: worst.shelf, y0: yMin, y1: yMax, line: { color: '#16a34a', width: 1.5, dash: 'dot' } }); annotations.push({ x: worst.shelf, y: yMax, yanchor: 'top', text: worst.shelf.toFixed(1) + '개월', showarrow: false, font: { size: 10, color: '#16a34a' } }); }
  if (approved > 0 && approved <= xMax) { shapes.push({ type: 'line', x0: approved, x1: approved, y0: yMin, y1: yMax, line: { color: '#d97706', width: 1.5, dash: 'dash' } }); annotations.push({ x: approved, y: yMax, yanchor: 'top', text: '허가 ' + approved + '개월', showarrow: false, font: { size: 10, color: '#b45309' } }); }
  const layout = { height: 400, margin: { l: 46, r: 20, t: 26, b: 42 }, xaxis: { title: '시점 (개월)', tickvals: ticks, range: [0, xMax], gridcolor: '#f0f2f6', zeroline: false }, yaxis: { title: '함량(%)', range: [yMin, yMax], gridcolor: '#eef1f5', zeroline: false }, shapes, annotations, legend: { orientation: 'h', y: -0.2 }, plot_bgcolor: '#fff', paper_bgcolor: '#fff', font: { family: 'Pretendard Variable, sans-serif', size: 11 }, hovermode: 'closest' };
  return { data, layout, config: { displayModeBar: false, responsive: true } };
}

function renderStabChart() {
  if (S.nav !== 'stability' || !S.stabData || !S.stabData.ok || !window.Plotly) return;
  const el = document.getElementById('stab-chart');
  if (!el) return;
  const fig = buildPlotly(S.stabData);
  if (fig) window.Plotly.newPlot(el, fig.data, fig.layout, fig.config);
}

function stepsDetails(b) {
  if (!b.steps || !b.steps.length) return '';
  const rows = b.steps.map(s => `<div style="display:grid;grid-template-columns:1.5fr 1fr;border-top:1px solid #f5f6f9">
    <div style="padding:5px 10px;font-size:11px;color:#5b6573">${esc(s.k)}</div>
    <div style="padding:5px 10px;text-align:right;font-family:${MONO};font-size:11px;color:#27303f">${s.v == null ? '—' : (typeof s.v === 'number' ? s.v.toLocaleString('en-US', { maximumFractionDigits: 6 }) : esc(s.v))}</div></div>`).join('');
  return `<details style="margin-top:10px"><summary style="cursor:pointer;font-size:11.5px;font-weight:600;color:#E5310F;user-select:none">📐 계산 검증 (단계별 수치)</summary>
    <div style="margin-top:8px;border:1px solid #eef1f5;border-radius:8px;overflow:hidden">${rows}</div></details>`;
}

function stabComparisonTable() {
  const t = S.stabTables;
  if (!t || !t.ok || !t.comparison.length) return '';
  const rows = t.comparison.map(r => {
    const diffColor = r.diff == null ? '#9aa4b4' : (r.diff > 0 ? '#15803d' : r.diff < 0 ? '#b45309' : '#5b6573');
    return `<div style="display:grid;grid-template-columns:1.8fr .9fr 1fr 1fr 1fr;border-top:1px solid #f2f4f8">
      <div style="padding:9px 14px;font-size:12.5px;color:#27303f">${esc(r.component)}</div>
      <div style="padding:9px 14px;font-family:${MONO};font-size:12.5px;color:#5b6573">${esc(r.batch)}</div>
      <div style="padding:9px 14px;text-align:right;font-family:${MONO};font-size:12.5px;font-weight:600;color:#15803d">${r.pooled == null ? '산출불가' : r.pooled.toFixed(1)}</div>
      <div style="padding:9px 14px;text-align:right;font-family:${MONO};font-size:12.5px;color:#5b6573">${r.indep == null ? '산출불가' : r.indep.toFixed(1)}</div>
      <div style="padding:9px 14px;text-align:right;font-family:${MONO};font-size:12.5px;font-weight:600;color:${diffColor}">${r.diff == null ? '—' : (r.diff >= 0 ? '+' : '') + r.diff.toFixed(1)}</div></div>`;
  }).join('');
  const wp = t.worstPooled, wi = t.worstIndep;
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <div style="display:flex;align-items:center;gap:9px;margin-bottom:4px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">🔬 두 방식 비교 (유효기간, 개월)</span><span style="font-size:11.5px;color:#9aa4b4">통합(ICH Q1E·미니탭) vs 배치별 독립 · 전 시험항목×배치</span>
      <span style="margin-left:auto;font-size:11.5px;font-weight:600;color:#5b6573">종합판정 통합 <b style="color:#15803d">${wp == null ? '—' : wp + '개월'}</b> · 독립 <b style="color:#b45309">${wi == null ? '—' : wi + '개월'}</b></span></div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden;margin-top:8px">
      <div style="display:grid;grid-template-columns:1.8fr .9fr 1fr 1fr 1fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:9px 14px">시험항목</div><div style="padding:9px 14px">제조번호</div><div style="padding:9px 14px;text-align:right">통합(권장)</div><div style="padding:9px 14px;text-align:right">배치별 독립</div><div style="padding:9px 14px;text-align:right">차이</div></div>
      ${rows}</div>
    <div style="font-size:11.5px;color:#9aa4b4;margin-top:10px;line-height:1.5">시점이 배치당 적을수록 배치별 독립은 자유도가 작아 보수적(짧게) 산출됩니다. ICH Q1E·미니탭은 통합 방식을 사용합니다.</div></div>`;
}

function stabSummaryTable() {
  const t = S.stabTables;
  if (!t || !t.ok) return '';
  const list = S.method === 'pooled' ? t.summaryPooled : t.summaryIndep;
  if (!list || !list.length) return '';
  const rows = list.map(r => `<div style="display:grid;grid-template-columns:1.7fr .8fr .6fr .8fr .8fr .7fr .8fr .9fr;border-top:1px solid #f2f4f8;font-size:12px">
    <div style="padding:8px 12px;color:#27303f">${esc(r.component)}</div>
    <div style="padding:8px 12px;font-family:${MONO};color:#5b6573">${esc(r.batch)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.n}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.slope == null ? '—' : r.slope.toFixed(4)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.intercept == null ? '—' : r.intercept.toFixed(2)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.r2 == null ? '—' : r.r2.toFixed(4)}</div>
    <div style="padding:8px 12px;color:#5b6573">${esc(r.trend)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};font-weight:600;color:#15803d">${r.shelf == null ? '산출불가' : r.shelf.toFixed(1)}</div></div>`).join('');
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <div style="font-size:14.5px;font-weight:700;margin-bottom:4px">선택 방식(${S.method === 'pooled' ? '통합' : '배치별 독립'}) 상세 요약 <span style="font-size:11.5px;font-weight:500;color:#9aa4b4">전 시험항목×배치</span></div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden;margin-top:8px">
      <div style="display:grid;grid-template-columns:1.7fr .8fr .6fr .8fr .8fr .7fr .8fr .9fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:8px 12px">시험항목</div><div style="padding:8px 12px">제조번호</div><div style="padding:8px 12px;text-align:right">데이터수</div><div style="padding:8px 12px;text-align:right">기울기 b</div><div style="padding:8px 12px;text-align:right">절편 a</div><div style="padding:8px 12px;text-align:right">R²</div><div style="padding:8px 12px">추세</div><div style="padding:8px 12px;text-align:right">유효기간</div></div>
      ${rows}</div></div>`;
}

function stabRawTable() {
  const t = S.stabTables;
  if (!t || !t.ok || !t.raw.length) return '';
  const rows = t.raw.map(r => `<div style="display:grid;grid-template-columns:.9fr 1.8fr 1fr .8fr .9fr .9fr .9fr;border-top:1px solid #f2f4f8;font-size:12px">
    <div style="padding:7px 12px;font-family:${MONO};color:#5b6573">${esc(r.제조번호)}</div>
    <div style="padding:7px 12px;color:#27303f">${esc(r.시험항목)}</div>
    <div style="padding:7px 12px;color:#5b6573">${esc(r.대분류)}</div>
    <div style="padding:7px 12px;text-align:right;font-family:${MONO};color:#27303f">${r.시점}</div>
    <div style="padding:7px 12px;text-align:right;font-family:${MONO};color:#27303f">${fmt(r.결과값, 2)}</div>
    <div style="padding:7px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.규격하한 == null ? '—' : r.규격하한}</div>
    <div style="padding:7px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.규격상한 == null ? '—' : r.규격상한}</div></div>`).join('');
  const xlsParams = new URLSearchParams({ code: S.stabCode, test_type: S.stabTestType, spec_low: S.specLow || '90', spec_high: S.specHigh || '150' });
  if (S.stabBatch) xlsParams.set('batch', S.stabBatch);
  const xlsUrl = `/api/stability/excel?` + xlsParams;
  return `<details style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <summary style="cursor:pointer;font-size:14.5px;font-weight:700;user-select:none;display:flex;align-items:center;gap:9px">📄 원자료 <span style="font-size:11.5px;font-weight:500;color:#9aa4b4">분석 입력 데이터 ${t.raw.length}행 (0개월=완제품 출하 포함)</span>
      <a href="${xlsUrl}" style="margin-left:auto;display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border:1.5px solid #E5310F;border-radius:9px;background:#fff;color:#E5310F;font-size:12px;font-weight:600;text-decoration:none" onclick="event.stopPropagation()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5"></path><path d="M12 15V3"></path></svg>Excel 다운로드</a></summary>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden;margin-top:12px;max-height:420px;overflow-y:auto">
      <div style="display:grid;grid-template-columns:.9fr 1.8fr 1fr .8fr .9fr .9fr .9fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6;position:sticky;top:0">
        <div style="padding:8px 12px">제조번호</div><div style="padding:8px 12px">시험항목</div><div style="padding:8px 12px">대분류</div><div style="padding:8px 12px;text-align:right">시점(개월)</div><div style="padding:8px 12px;text-align:right">결과값</div><div style="padding:8px 12px;text-align:right">규격하한</div><div style="padding:8px 12px;text-align:right">규격상한</div></div>
      ${rows}</div></details>`;
}

function stabPage() {
  const A = S.stabData;
  const fromOot = S.stabFromOot ? `<span style="display:inline-flex;align-items:center;gap:5px;background:#fdece8;color:#E5310F;font-weight:600;padding:2px 9px;border-radius:6px;font-size:10.5px"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2.4"><path d="M5 12h14"></path><path d="m13 6 6 6-6 6"></path></svg>OOT에서 연동됨</span>` : '';
  const batchChip = S.stabBatch ? `<span style="display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid #E5310F;color:#E5310F;font-weight:600;padding:2px 4px 2px 10px;border-radius:999px;font-size:10.5px;letter-spacing:0">배치 ${esc(S.stabBatch)}만 표시<button data-act="clearStabBatch" title="전체 배치 보기" style="border:none;background:#fdece8;color:#E5310F;cursor:pointer;border-radius:50%;width:16px;height:16px;line-height:1;font-size:12px;padding:0">×</button></span>` : '';
  const eyebrow = `광동제약 · 품질·시험 ${fromOot} ${batchChip}`;
  const head = `<div style="margin-bottom:20px">
    <div style="font-size:11.5px;font-weight:600;letter-spacing:.04em;color:#E5310F;margin-bottom:8px;display:flex;align-items:center;gap:9px">${eyebrow}</div>
    <h1 style="margin:0;font-size:26px;font-weight:700;letter-spacing:-.02em;display:flex;align-items:baseline;gap:11px">안정성 회귀분석<span style="color:#8a94a6;font-weight:500;font-size:15px">Shelf-life · ICH Q1E 유효기간</span></h1>
    <div style="font-size:12.5px;color:#9aa4b4;margin-top:7px">데이터 출처: Tableau <span style="font-family:${MONO}">OOT_추출용</span> · <span style="font-family:${MONO}">의뢰 특이사항</span> → 시점(개월) · 함량 = <span style="font-family:${MONO}">LOT결과_0제외</span></div></div>`;

  const prodOptions = S.stabProducts.map(p => `<option value="${esc(p.code)}" ${p.code === S.stabCode ? 'selected' : ''}>${esc(p.code)}  ${esc(p.name)}</option>`).join('');
  const methodChips = [['pooled', '통합 (ICH Q1E)'], ['independent', '배치별 독립']].map(([k, l]) => {
    const sel = S.method === k, b = `font-size:12px;font-weight:600;padding:6px 13px;border-radius:7px;cursor:pointer;border:none`;
    return `<button data-act="method" data-method="${k}" style="${b};${sel ? 'background:#fff;color:#27303f;box-shadow:0 1px 2px rgba(20,30,50,.12)' : 'background:transparent;color:#7a8699'}">${l}</button>`;
  }).join('');
  const methodHint = S.method === 'pooled' ? '같은 성분의 여러 배치 오차를 통합해 자유도를 확보합니다(미니탭 일치·권장).' : '각 배치 데이터만으로 계산 — 시점이 적으면 보수적으로(짧게) 산출됩니다.';
  const itemOptions = A && A.ok ? A.testItems.map(t => `<option value="${esc(t)}" ${t === A.testItem ? 'selected' : ''}>${esc(t)}</option>`).join('') : '';

  const control = `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);overflow:hidden">
    <div style="padding:18px 22px;display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end">
      <div style="flex:1 1 230px;min-width:200px"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">시험종류</span>
        <div style="position:relative"><select data-act="stabTestType" style="width:100%;padding:11px 36px 11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-weight:600;color:#27303f;background:#fff;appearance:none;cursor:pointer">${(S.stabTestTypes || STAB_TYPES_FALLBACK).map(t => `<option ${t === S.stabTestType ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div></div>
      <div style="flex:1 1 320px;min-width:240px"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">품목</span>
        <div style="position:relative"><select data-act="stabProduct" style="width:100%;padding:11px 36px 11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-weight:600;color:#27303f;background:#fff;appearance:none;cursor:pointer">${prodOptions || '<option>로딩…</option>'}</select>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div></div>
      <div style="flex:0 0 auto"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">함량 규격 (%)</span>
        <div style="display:flex;align-items:center;gap:8px">
          <input data-act="specLow" value="${esc(S.specLow)}" style="width:72px;padding:10px 11px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-family:${MONO};text-align:center;outline:none">
          <span style="color:#b8c0cc;font-weight:600">~</span>
          <input data-act="specHigh" value="${esc(S.specHigh)}" style="width:72px;padding:10px 11px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-family:${MONO};text-align:center;outline:none"></div></div>
    </div>
    <div style="border-top:1px solid #eef1f5;background:#fafbfd;padding:14px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
      <span style="font-size:11px;font-weight:600;color:#8a94a6">분석 방식</span>
      <div style="display:flex;gap:3px;background:#eef1f6;border:1px solid #e2e7ef;border-radius:9px;padding:3px">${methodChips}</div>
      <span style="font-size:11.5px;color:#9aa4b4;line-height:1.5;flex:1 1 240px;min-width:200px">${methodHint}</span>
      ${A && A.ok ? `<div style="display:flex;align-items:center;gap:8px;margin-left:auto"><span style="font-size:11px;font-weight:600;color:#8a94a6">시험항목</span>
        <select data-act="testItem" style="padding:7px 28px 7px 10px;border:1px solid #d7dce4;border-radius:8px;font-size:12px;font-weight:600;color:#27303f;background:#fff;appearance:none;cursor:pointer">${itemOptions}</select></div>` : ''}
    </div></div>`;

  if (S.stabLoading) return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">${head}${control}<div style="padding:60px;text-align:center;color:#9aa4b4">분석 중…</div></div>`;
  if (!A || !A.ok) return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">${head}${control}<div style="background:#fff;border:1px dashed #cfd6e0;border-radius:16px;padding:48px;text-align:center;margin-top:18px;color:#9aa4b4;font-size:14px">${A ? esc(A.reason || '분석 불가') : '품목을 선택하세요.'}</div></div>`;

  const worst = A.worst;
  const bGood = !!worst;
  const bTH = bGood ? { bg: '#f1fbf4', bd: '#bcecca', fg: '#15803d', tile: '#cdf2da', icon: '#16a34a' } : { bg: '#fef4f4', bd: '#f6c9c9', fg: '#b91c1c', tile: '#fde0e0', icon: '#dc2626' };
  const skpi = 'background:rgba(255,255,255,.6);border:1px solid rgba(20,30,50,.06);border-radius:11px;padding:9px 14px;min-width:72px;text-align:center';
  const skpiBox = (lab, val, col, sz) => `<div style="${skpi}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">${lab}</div><div style="font-family:${MONO};font-size:${sz || 19}px;font-weight:600;color:${col}">${val}</div></div>`;
  const ootColor = A.nOot > 0 ? '#dc2626' : A.nWarn > 0 ? '#d97706' : '#16a34a';
  const shortWarn = A.approvedShort && worst;
  const shelfKpiColor = shortWarn ? '#b45309' : '#15803d';
  const apprStr = A.approvedMonths != null ? A.approvedMonths + '개월' : '—';
  const banner = `<div style="display:flex;gap:18px;align-items:center;padding:22px 24px;border-radius:16px;margin-top:18px;border:1px solid ${bTH.bd};background:${bTH.bg};box-shadow:0 1px 3px rgba(20,30,50,.05);flex-wrap:wrap">
    <div style="width:48px;height:48px;border-radius:13px;display:flex;align-items:center;justify-content:center;flex:0 0 auto;background:${bTH.tile}"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="${bTH.icon}" stroke-width="2.2"><path d="M5 12.5 10 17.5 19.5 7"></path></svg></div>
    <div style="flex:1;min-width:200px"><div style="font-size:11.5px;font-weight:600;color:#8a94a6;margin-bottom:5px">종합 판정 · worst-case</div>
      <div style="color:${bTH.fg};font-size:24px;font-weight:700;letter-spacing:-.015em;line-height:1.2">${worst ? worst.shelf.toFixed(1) + '개월까지 안정성 유효' : '측정기간 내 규격 이탈 없음(적합)'}</div>
      <div style="font-size:13px;color:#5b6573;margin-top:7px">제한 배치 <span style="font-family:${MONO};font-weight:600">${worst ? esc(worst.batch) : '—'}</span> · ${esc(A.testItem)} · ${worst ? '규격하한 ' + (A.specLow != null ? A.specLow : '—') + ' (CI 하한 교차)' : '추세·σ만 표시'}</div>
      ${shortWarn ? `<div style="margin-top:9px;display:inline-flex;align-items:center;gap:7px;background:#fffbeb;border:1px solid #f3dd9f;color:#b45309;font-size:12px;font-weight:600;padding:5px 11px;border-radius:9px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.2"><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path><path d="M12 9v4"></path><circle cx="12" cy="16.5" r=".5" fill="#d97706"></circle></svg>추정 저장수명(${worst.shelf.toFixed(1)}개월)이 허가 유효기간(${A.approvedMonths}개월)보다 짧습니다 — CI 기준 라벨 미충족 가능</div>` : ''}</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-self:stretch">
      ${skpiBox('추정 저장수명', worst ? worst.shelf.toFixed(1) : '—', shelfKpiColor)}
      <div style="${skpi}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">허가 유효기간</div><div style="font-family:${MONO};font-size:19px;font-weight:600;color:#5b6573">${apprStr}</div></div>
      ${skpiBox('배치 수', A.batchCount, '#27303f')}
      <div style="${skpi}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">추세</div><div style="font-size:15px;font-weight:600;color:#d97706;padding-top:3px">${worst ? esc(worst.trend) : '—'}</div></div>
      ${skpiBox('시점간 OOT', A.nOot + A.nWarn, ootColor)}</div></div>`;

  // ANCOVA
  const anc = A.ancova;
  let ancovaPanel;
  if (anc) {
    const rows = anc.rows.map(r => {
      const hl = r.interaction;
      const pColor = r.p == null ? '#9aa4b4' : (r.p < 0.25 ? '#b45309' : '#16a34a');
      return `<div style="display:grid;grid-template-columns:1.6fr .7fr 1fr .9fr .9fr;border-top:1px solid #f2f4f8;${hl ? 'background:#fffcf2' : 'background:#fff'}">
        <div style="padding:10px 14px;font-weight:${hl ? 700 : 500};color:${hl ? '#27303f' : '#46536a'}">${esc(r.source)}</div>
        <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#5b6573">${r.df}</div>
        <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#5b6573">${r.ss}</div>
        <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#5b6573">${r.f == null ? '—' : r.f}</div>
        <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-weight:${hl ? 700 : 500};color:${pColor}">${r.p == null ? '—' : r.p.toFixed(3)}</div></div>`;
    }).join('');
    const badge = `margin-left:auto;font-size:11.5px;font-weight:600;padding:4px 12px;border-radius:999px;${anc.poolable ? 'background:#ecfdf3;color:#15803d' : 'background:#fdedc4;color:#b45309'}`;
    ancovaPanel = `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:4px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">합산성 검정 (ANCOVA)</span>
        <span style="font-family:${MONO};font-size:11px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">α = 0.25</span>
        <span style="font-size:11.5px;color:#9aa4b4">ICH Q1E · 미니탭 정합</span><span style="${badge}">${esc(anc.verdict)}</span></div>
      <div style="font-size:12px;color:#8a94a6;margin-bottom:14px;line-height:1.5">함량 = 시간 + 제조번호 + 시간×제조번호 · 교호작용 p ≥ 0.25 → 기울기 공통, p &lt; 0.25 → 배치별 개별 회귀</div>
      <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden">
        <div style="display:grid;grid-template-columns:1.6fr .7fr 1fr .9fr .9fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
          <div style="padding:9px 14px">요인 (Source)</div><div style="padding:9px 14px;text-align:right">DF</div><div style="padding:9px 14px;text-align:right">Seq SS</div><div style="padding:9px 14px;text-align:right">F</div><div style="padding:9px 14px;text-align:right">P</div></div>
        ${rows}</div>
      <div style="font-size:12px;color:#5b6573;margin-top:12px;line-height:1.55">${esc(anc.note)}</div></div>`;
  } else {
    ancovaPanel = `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;padding:18px 22px;margin-top:18px">
      <div style="display:flex;align-items:center;gap:9px"><span style="font-size:14.5px;font-weight:700">합산성 검정 (ANCOVA)</span><span style="font-size:11.5px;color:#9aa4b4">ICH Q1E · α=0.25</span></div>
      <div style="font-size:12.5px;color:#9aa4b4;margin-top:10px;line-height:1.55">데이터가 부족해 합산성 검정을 산출할 수 없습니다(배치 2개 이상·각 배치 시점 2개 이상 + 잔차자유도 ≥1 필요). 현재는 선택한 분석 방식으로 유효기간을 산출합니다.</div></div>`;
  }

  const legend = A.batches.map(b => `<div style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:3px;border-radius:2px;background:${b.color}"></span><span style="font-family:${MONO};font-size:11.5px;color:#5b6573">배치 ${esc(b.batch)}</span></div>`).join('');
  const batchCards = A.batches.map(b => {
    const isW = worst && b.batch === worst.batch;
    const bShort = b.shelf != null && b.approved != null && b.shelf < b.approved;
    const shelfText = b.shelf != null ? b.shelf.toFixed(1) + '개월' : '산출불가';
    const shelfColor = bShort ? '#dc2626' : (b.shelf != null ? (isW ? '#b45309' : '#15803d') : '#9aa4b4');
    return `<div style="background:#fff;border:1px solid ${isW ? '#f3dd9f' : '#dfe4ec'};border-radius:14px;padding:15px 17px;box-shadow:0 1px 3px rgba(20,30,50,.05)">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:12px"><span style="width:10px;height:10px;border-radius:50%;flex:0 0 auto;background:${b.color}"></span><span style="font-family:${MONO};font-size:14px;font-weight:600">${esc(b.batch)}</span>
        <span style="font-size:10.5px;font-weight:600;padding:2px 9px;border-radius:999px;${isW ? 'background:#fdedc4;color:#b45309' : 'background:#eef1f5;color:#5b6573'}">${isW ? '제한 배치' : esc(b.trend)}</span>
        <span style="margin-left:auto;font-family:${MONO};font-size:16px;font-weight:600;color:${shelfColor}">${shelfText}</span></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;font-size:12px">
        <div style="display:flex;justify-content:space-between"><span style="color:#8a94a6">기울기 b</span><span style="font-family:${MONO};font-weight:600">${b.slope == null ? '—' : b.slope.toFixed(4)}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:#8a94a6">R²</span><span style="font-family:${MONO};font-weight:600">${b.r2 == null ? '—' : b.r2.toFixed(4)}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:#8a94a6">절편 a</span><span style="font-family:${MONO};font-weight:600">${b.intercept == null ? '—' : b.intercept.toFixed(2)}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:#8a94a6">시점 n</span><span style="font-family:${MONO};font-weight:600">${b.n}</span></div></div>
      <div style="margin-top:11px;padding-top:11px;border-top:1px solid #eef1f5;display:flex;justify-content:space-between;align-items:center">
        <span style="font-family:${MONO};font-size:11.5px;color:#5b6573">함량(%) = ${b.intercept == null ? '—' : b.intercept.toFixed(2)} + (${b.slope == null ? '—' : b.slope.toFixed(4)})·t</span>
        ${b.approved != null ? `<span style="font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:999px;${bShort ? 'background:#fde0e0;color:#b91c1c' : 'background:#eef1f5;color:#5b6573'}">허가 ${b.approved}개월${bShort ? ' ⚠' : ''}</span>` : ''}</div>${stepsDetails(b)}</div>`;
  }).join('');

  const chartBlock = `<div style="display:flex;gap:18px;margin-top:18px;align-items:flex-start;flex-wrap:wrap">
    <div style="flex:1 1 600px;min-width:380px;background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 20px">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:6px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">배치별 저장수명도</span><span style="font-size:11.5px;color:#9aa4b4">함량(%) vs 시점(개월) · 적합선 + 95% CI + 규격 + 유효기간</span></div>
      <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px">${legend}<div style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:0;border-top:2px dashed #dc2626"></span><span style="font-size:11.5px;color:#5b6573">규격하한</span></div><div style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:0;border-top:2px dotted #16a34a"></span><span style="font-size:11.5px;color:#5b6573">추정 유효기간</span></div>${A.approvedMonths != null ? `<div style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:0;border-top:2px dashed #d97706"></span><span style="font-size:11.5px;color:#5b6573">허가 유효기간</span></div>` : ''}</div>
      <div id="stab-chart" style="min-height:380px">${buildChartSVG(A)}</div></div>
    <aside style="flex:1 1 330px;min-width:300px;display:flex;flex-direction:column;gap:14px">${batchCards}</aside></div>`;

  // timepoint OOT table
  const tpRows = A.tpRows.map(t => {
    const oot = t.judge.startsWith('⚠'), warn = t.judge.startsWith('주의');
    const C = oot ? { bg: '#fef2f2', fg: '#b91c1c', tb: '#fde0e0' } : warn ? { bg: '#fffbeb', fg: '#b45309', tb: '#fdedc4' } : { bg: '#fff', fg: '#15803d', tb: '#ecfdf3' };
    const devColor = oot ? '#dc2626' : warn ? '#d97706' : '#5b6573';
    return `<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1.3fr;border-top:1px solid #f2f4f8;background:${C.bg}">
      <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#27303f">${t.time}</div>
      <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#27303f">${t.meas}</div>
      <div style="padding:10px 14px;text-align:right;font-family:${MONO};color:#5b6573">${t.pred}</div>
      <div style="padding:10px 14px;text-align:right;font-family:${MONO};font-weight:600;color:${devColor}">${(t.dev >= 0 ? '+' : '−') + Math.abs(t.dev).toFixed(2)}</div>
      <div style="padding:10px 14px"><span style="font-size:11.5px;font-weight:600;padding:3px 10px;border-radius:999px;background:${C.tb};color:${C.fg}">${esc(t.judge)}</span></div></div>`;
  }).join('');
  const sumBase = 'margin-top:13px;padding:11px 15px;border-radius:11px;font-size:12.5px;font-weight:600;display:flex;align-items:center;gap:8px;';
  let sum, sumStyle;
  if (A.nOot) { sum = `OOT ${A.nOot}건 — ±3σ 관리한계 이탈. 원인조사 대상.`; sumStyle = sumBase + 'background:#fef2f2;color:#b91c1c'; }
  else if (A.nWarn) { sum = `주의 ${A.nWarn}건 — 2~3σ 구간. 모니터링 필요.`; sumStyle = sumBase + 'background:#fffbeb;color:#b45309'; }
  else { const mx = A.tpRows.length ? Math.max(...A.tpRows.map(t => Math.abs(t.dev))) : 0; sum = `OOT 없음 — 모든 시점이 ±2σ 이내 (최대 편차 ${mx.toFixed(2)}σ).`; sumStyle = sumBase + 'background:#f1fbf4;color:#15803d'; }
  const tpTable = `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <div style="display:flex;align-items:center;gap:9px;margin-bottom:4px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">시점간 OOT 판정</span><span style="font-size:11.5px;color:#9aa4b4">추세선 ±2σ 주의 / ±3σ 관리한계 · σ = ${A.sigma == null ? '—' : A.sigma} (${esc(A.sigmaBase)})</span><span style="margin-left:auto;font-family:${MONO};font-size:11px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">배치 ${esc(A.tpBatch)}</span></div>
    <div style="font-size:12px;color:#8a94a6;margin-bottom:14px;line-height:1.5">각 시점이 자기 추세선에서 얼마나 벗어났는지 봅니다. OOT(추세 이탈)와 OOS(규격 이탈)는 별개이며, 규격 안이어도 ±3σ를 벗어나면 조사 대상입니다.</div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1.3fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:9px 14px;text-align:right">시점(개월)</div><div style="padding:9px 14px;text-align:right">측정값</div><div style="padding:9px 14px;text-align:right">추세예측</div><div style="padding:9px 14px;text-align:right">편차(σ)</div><div style="padding:9px 14px">판정</div></div>
      ${tpRows}</div>
    <div style="${sumStyle}">${esc(sum)}</div></div>`;

  const footer = `<div style="font-size:12px;color:#9aa4b4;margin-top:18px;line-height:1.6;display:flex;gap:8px;align-items:flex-start">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#b8c0cc" stroke-width="2" style="flex:0 0 auto;margin-top:1px"><circle cx="12" cy="12" r="9"></circle><path d="M12 8v5"></path><circle cx="12" cy="16" r=".6" fill="#b8c0cc"></circle></svg>
    본 결과는 자동 산출 참고값입니다. 최종 유효기간은 QC 책임자 검토·승인 및 ICH Q1A/Q1E·사내 SOP 확인이 필요합니다. 규격하한/상한이 데이터에 없을 경우 수동 입력값(기본 90/150)을 사용합니다.</div>`;

  const subInfo = `<span style="font-size:11.5px;color:#9aa4b4;font-family:${MONO};margin-left:auto">시험항목 ${esc(A.testItem)} · 배치 ${A.batchCount} · 시점쌍 ${A.pairCount}</span>`;
  return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">${head}${control}${banner}${ancovaPanel}${chartBlock}${stabComparisonTable()}${stabSummaryTable()}${tpTable}${stabRawTable()}${footer}</div>`;
}

/* ============================ ALARM PAGE ============================ */
function alarmGate() {
  return `<div style="padding:26px 30px 60px;max-width:880px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', '알림 설정', '', '실시간 OOT 메일 알람 정책 · 수신자 · 조회 주기')}
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:40px 24px;max-width:420px;margin:8px auto;text-align:center">
      <div style="width:56px;height:56px;border-radius:14px;background:#fdece8;display:flex;align-items:center;justify-content:center;margin:0 auto"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V7a4 4 0 0 1 8 0v4"></path></svg></div>
      <div style="font-size:16px;font-weight:700;margin-top:16px">보호된 페이지</div>
      <div style="font-size:12.5px;color:#9aa4b4;margin-top:6px">알림 설정은 비밀번호 입력 후 접근할 수 있습니다.</div>
      <input id="alarm-pw" type="password" placeholder="비밀번호" style="width:100%;margin-top:18px;padding:11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:14px;font-family:${MONO};text-align:center;outline:none">
      <div id="alarm-pw-err" style="color:#dc2626;font-size:12px;font-weight:600;height:16px;margin-top:8px"></div>
      <button data-act="alarmUnlock" style="width:100%;margin-top:6px;padding:11px;border:none;border-radius:10px;background:#E5310F;color:#fff;font-size:13.5px;font-weight:600;cursor:pointer">잠금 해제</button>
    </div></div>`;
}

function alarmPage() {
  if (!S.alarmAuthed) return alarmGate();
  const al = S.alarm;
  const polCards = [['관리이탈만', '관리이탈만 (±3σ)', '±3σ 관리한계 이탈 시에만 발송'], ['주의+관리이탈', '주의 포함 (±2σ~)', '주의·관리이탈 모두 발송']].map(([k, t, d]) => {
    const sel = al.policy === k;
    return `<button data-act="policy" data-policy="${k}" style="flex:1 1 220px;text-align:left;padding:14px 16px;border-radius:12px;cursor:pointer;${sel ? 'border:1.5px solid #E5310F;background:#fdece8;color:#1a2230' : 'border:1px solid #e0e5ec;background:#fff;color:#46536a'}">
      <div style="font-size:13.5px;font-weight:600">${t}</div><div style="font-size:11.5px;margin-top:4px;opacity:.85">${d}</div></button>`;
  }).join('');
  const recips = al.recipients.length ? al.recipients.map(m => `<span style="display:inline-flex;align-items:center;gap:8px;background:#fdece8;border:1px solid #f3d3c8;color:#E5310F;font-size:12.5px;font-weight:600;padding:7px 12px;border-radius:999px">${esc(m)}<button data-act="rmRecip" data-mail="${esc(m)}" style="border:none;background:transparent;color:#E5310F;cursor:pointer;font-size:14px;line-height:1;padding:0">×</button></span>`).join('') : `<span style="font-size:12.5px;color:#9aa4b4">등록된 수신자가 없습니다.</span>`;
  const intChips = ['5분', '10분', '15분'].map(i => {
    const sel = al.interval === i, b = `font-family:${MONO};font-size:12.5px;font-weight:600;padding:7px 14px;border-radius:7px;cursor:pointer;border:none`;
    return `<button data-act="interval" data-interval="${i}" style="${b};${sel ? 'background:#fff;color:#27303f;box-shadow:0 1px 2px rgba(20,30,50,.12)' : 'background:transparent;color:#7a8699'}">${i}</button>`;
  }).join('');
  const nightTrack = `position:relative;width:44px;height:26px;border-radius:999px;border:none;cursor:pointer;background:${al.night ? '#E5310F' : '#cdd5e0'}`;
  const nightKnob = `position:absolute;top:3px;left:${al.night ? '21px' : '3px'};width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.2)`;
  return `<div style="padding:26px 30px 60px;max-width:880px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', '알림 설정', '', '실시간 OOT 메일 알람 정책 · 수신자 · 조회 주기')}
    <div style="display:flex;gap:10px;margin:-6px 0 16px;flex-wrap:wrap;align-items:center">
      <button data-act="saveAlarm" style="display:flex;align-items:center;gap:7px;padding:9px 16px;border:none;border-radius:10px;background:#E5310F;color:#fff;font-size:12.5px;font-weight:600;cursor:pointer"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path></svg>저장</button>
      <span id="alarm-status" style="font-size:12px;font-weight:600;color:${S.alarmDirty ? '#b45309' : '#9aa4b4'}">${S.alarmDirty ? '● 저장되지 않은 변경사항' : '모든 변경사항 저장됨'}</span>
      <button data-act="alarmTest" style="margin-left:auto;display:flex;align-items:center;gap:7px;padding:9px 14px;border:1.5px solid #E5310F;border-radius:10px;background:#fff;color:#E5310F;font-size:12.5px;font-weight:600;cursor:pointer"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="m3 7 9 6 9-6"></path></svg>테스트 발송</button>
      <span id="alarm-test-msg" style="font-size:12px;font-weight:600;color:#5b6573"></span>
      <button data-act="alarmLock" style="display:flex;align-items:center;gap:7px;padding:9px 14px;border:1px solid #d7dce4;border-radius:10px;background:#fff;color:#5b6573;font-size:12.5px;font-weight:600;cursor:pointer"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5b6573" stroke-width="2"><rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V7a4 4 0 0 1 8 0v4"></path></svg>잠금</button>
    </div>
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px;margin-bottom:16px">
      <div style="font-size:13.5px;font-weight:700;margin-bottom:14px">발송 정책</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">${polCards}</div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:16px;padding:13px 15px;background:#f8fafc;border:1px solid #eef1f5;border-radius:11px">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8a94a6" stroke-width="2"><circle cx="12" cy="12" r="9"></circle><path d="M12 8v5"></path><circle cx="12" cy="16" r=".6" fill="#8a94a6"></circle></svg>
        <span style="font-size:12px;color:#5b6573;line-height:1.5">중복 발송은 (품목코드·제조번호·시험항목)+분류 키의 발송 이력으로 차단됩니다.</span></div></div>
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px;margin-bottom:16px">
      <div style="font-size:13.5px;font-weight:700;margin-bottom:6px">수신자</div>
      <div style="font-size:12px;color:#9aa4b4;margin-bottom:14px">신규 OOT 발생 시 메일을 받는 그룹입니다.</div>
      <div style="display:flex;gap:9px;flex-wrap:wrap;margin-bottom:14px;align-items:center">${recips}</div>
      <div style="display:flex;gap:8px"><input id="recip-input" placeholder="email@ekdp.com" style="flex:1;max-width:280px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;font-family:${MONO};outline:none">
        <button data-act="addRecip" style="display:flex;align-items:center;gap:7px;padding:9px 14px;border:1.5px dashed #c3cdda;border-radius:10px;background:#fff;color:#5b6573;font-size:12.5px;font-weight:600;cursor:pointer"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>수신자 추가</button></div></div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">
      <div style="flex:1 1 240px;background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px">
        <div style="font-size:13.5px;font-weight:700;margin-bottom:14px">조회 주기</div>
        <div style="display:flex;gap:3px;background:#eef1f6;border:1px solid #e2e7ef;border-radius:9px;padding:3px;width:fit-content">${intChips}</div>
        <div style="font-size:11.5px;color:#9aa4b4;margin-top:12px;line-height:1.55">실시간성 상한은 Tableau extract 갱신 주기에 종속됩니다.</div></div>
      <div style="flex:1 1 240px;background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px">
        <div style="font-size:13.5px;font-weight:700;margin-bottom:14px">야간·주말 발송</div>
        <div style="display:flex;align-items:center;justify-content:space-between"><span style="font-size:13px;color:#46536a">업무 외 시간 즉시 발송</span>
          <button data-act="toggleNight" style="${nightTrack}"><span style="${nightKnob}"></span></button></div>
        <div style="font-size:11.5px;color:#9aa4b4;margin-top:12px;line-height:1.55">${al.night ? '업무 외 시간에도 신규 OOT 발생 즉시 발송합니다.' : '업무 외 시간 발송은 다음 업무일 오전으로 보류됩니다.'}</div></div></div>
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px;margin-top:16px">
      <div style="font-size:13.5px;font-weight:700;margin-bottom:6px">비밀번호 변경</div>
      <div style="font-size:12px;color:#9aa4b4;margin-bottom:14px">${S.alarmFromEnv ? '⚠ 비밀번호가 .env(OOT_ALERT_PASSWORD)로 고정되어 있어 화면에서 변경할 수 없습니다.' : '알림 설정 진입 비밀번호를 변경합니다.'}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <input id="pw-cur" type="password" placeholder="현재 비밀번호" ${S.alarmFromEnv ? 'disabled' : ''} style="width:150px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;font-family:${MONO};outline:none">
        <input id="pw-new" type="password" placeholder="새 비밀번호(4자+)" ${S.alarmFromEnv ? 'disabled' : ''} style="width:150px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;font-family:${MONO};outline:none">
        <button data-act="changePw" ${S.alarmFromEnv ? 'disabled' : ''} style="padding:9px 16px;border:none;border-radius:10px;background:${S.alarmFromEnv ? '#cbd2dc' : '#E5310F'};color:#fff;font-size:12.5px;font-weight:600;cursor:${S.alarmFromEnv ? 'default' : 'pointer'}">변경</button>
        <span id="pw-msg" style="font-size:12px;font-weight:600"></span></div></div>
  </div>`;
}

/* ============================ RENDER + EVENTS ============================ */
function render() {
  const page = S.nav === 'oot' ? ootPage() : S.nav === 'stability' ? stabPage() : alarmPage();
  $('#app').innerHTML = sidebar() + `<div style="flex:1;min-width:0;display:flex;flex-direction:column">${topbar()}${page}</div>`;
  bindInputs();
}

function bindInputs() {
  const search = $('#oot-search');
  if (search) {
    search.addEventListener('input', e => {
      S.query = e.target.value; S.open = true;
      // 검색어가 선택된 품목과 더이상 일치하지 않으면 선택 해제(품목명·LOT·결과 동기화)
      if (S.code && S.query !== `${S.code}  ${S.productName}`) {
        S.code = null; S.productName = ''; S.lot = null; S.lotSummary = null; S.years = ['전체']; S.yearFilter = '전체'; S.lotQuery = '';
        const pn = $('#oot-pname'); if (pn) { pn.textContent = '품목코드 선택 시 표시'; pn.style.color = '#b8c0cc'; }
        const ls = $('#oot-lot-section'); if (ls) ls.innerHTML = ootLotControls();
        const rs = $('#oot-results'); if (rs) rs.innerHTML = ootResults();
      }
      $('#oot-dropdown').innerHTML = ootDropdown();
    });
    search.addEventListener('focus', () => { S.open = true; $('#oot-dropdown').innerHTML = ootDropdown(); });
    search.addEventListener('blur', () => setTimeout(() => { S.open = false; const d = $('#oot-dropdown'); if (d) d.innerHTML = ''; }, 160));
  }
  const lotSearch = $('#lot-search');
  if (lotSearch) lotSearch.addEventListener('input', e => {
    S.lotQuery = e.target.value; const c = $('#lot-chips'); if (c) c.innerHTML = lotChips();
    const lots = S.lotSummary.lots.filter(l => (S.yearFilter === '전체' || l.year === S.yearFilter) && (!S.lotQuery || l.lot.toLowerCase().includes(S.lotQuery.toLowerCase())));
    const cnt = $('#lot-count'); if (cnt) cnt.textContent = `표시 ${lots.length} / 전체 ${S.lotSummary.lots.length}`;
  });
  ['specLow', 'specHigh'].forEach(k => { const el = document.querySelector(`[data-act="${k}"]`); if (el) el.addEventListener('change', e => { S[k] = e.target.value; loadStability(); }); });
  const apw = $('#alarm-pw');
  if (apw) { apw.focus(); apw.addEventListener('keydown', e => { if (e.key === 'Enter') unlockAlarm(); }); }
  const pwNew = $('#pw-new');
  if (pwNew) pwNew.addEventListener('keydown', e => { if (e.key === 'Enter') changePw(); });
  renderStabChart();   // Plotly 인터랙티브 차트(가능 시 SVG 대체)
}

document.addEventListener('mousedown', e => {
  const t = e.target.closest('[data-act="pickProduct"]');
  if (t) { e.preventDefault(); pickProduct(t.dataset.code, t.dataset.name); }
});

document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;
  if (act === 'home') { goHome(); }
  else if (act === 'nav') { S.nav = el.dataset.nav; if (S.nav === 'alarm') S.alarmAuthed = false; render(); if (S.nav === 'stability') ensureStability(); if (S.nav === 'alarm') loadAlarm(); }
  else if (act === 'alarmUnlock') { unlockAlarm(); }
  else if (act === 'alarmLock') { S.alarmAuthed = false; render(); }
  else if (act === 'alarmTest') { testSend(); }
  else if (act === 'changePw') { changePw(); }
  else if (act === 'refresh') { location.reload(); }
  else if (act === 'pickYear') { S.yearFilter = el.dataset.year; render(); }
  else if (act === 'pickLot') { S.lot = el.dataset.lot; render(); }
  else if (act === 'jumpStab') {
    S.stabFromOot = true; S.stabCode = S.code; S.stabBatch = S.lot;   // 선택 LOT만 분석
    if (S.ootTestType && S.ootTestType.includes('안정성')) S.stabTestType = S.ootTestType;
    S.stabTestItem = null; S.stabData = null; S.stabTables = null; S.stabTablesKey = '';
    S.nav = 'stability'; render(); loadStabProducts();
  }
  else if (act === 'clearStabBatch') { S.stabBatch = null; S.stabTestItem = null; S.stabData = null; S.stabTables = null; S.stabTablesKey = ''; loadStability(); }
  else if (act === 'method') { S.method = el.dataset.method; loadStability(); }
  else if (act === 'policy') { S.alarm.policy = el.dataset.policy; S.alarmDirty = true; render(); }
  else if (act === 'interval') { S.alarm.interval = el.dataset.interval; S.alarmDirty = true; render(); }
  else if (act === 'toggleNight') { S.alarm.night = !S.alarm.night; S.alarmDirty = true; render(); }
  else if (act === 'addRecip') { const i = $('#recip-input'); const v = i ? i.value.trim() : ''; if (v) { if (!S.alarm.recipients.includes(v)) S.alarm.recipients.push(v); S.alarmDirty = true; render(); } }
  else if (act === 'rmRecip') { S.alarm.recipients = S.alarm.recipients.filter(m => m !== el.dataset.mail); S.alarmDirty = true; render(); }
  else if (act === 'saveAlarm') { saveAlarm(); }
});

document.addEventListener('change', e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  if (el.dataset.act === 'ootTestType') { S.ootTestType = el.value; S.code = null; S.productName = ''; S.lot = null; S.lotSummary = null; S.query = ''; loadOotProducts(); }
  else if (el.dataset.act === 'stabTestType') { S.stabTestType = el.value; S.stabCode = null; S.stabData = null; S.stabBatch = null; S.stabFromOot = false; loadStabProducts(); }
  else if (el.dataset.act === 'stabProduct') { S.stabCode = el.value; S.stabTestItem = null; S.stabFromOot = false; S.stabBatch = null; loadStability(); }
  else if (el.dataset.act === 'testItem') { S.stabTestItem = el.value; loadStability(); }
});

/* ============================ DATA ACTIONS ============================ */
function goHome() {
  // 홈 = OOT 빠른 조회 초기 화면. 모든 선택·필터·인증 초기화.
  S.nav = 'oot'; S.ootTestType = '완제품';
  S.code = null; S.productName = ''; S.query = ''; S.open = false;
  S.lot = null; S.lotSummary = null; S.years = ['전체']; S.yearFilter = '전체'; S.lotQuery = '';
  S.alarmAuthed = false; S.alarmDirty = false;
  S.stabBatch = null; S.stabFromOot = false;
  render();
  loadOotProducts();   // 완제품 품목 목록 보장(+재렌더)
}
async function loadOotProducts() {
  try { const d = await getJSON(`/api/oot/products?test_type=${encodeURIComponent(S.ootTestType)}`); S.ootProducts = d.products; OOT_TEST_TYPES = d.testTypes; }
  catch (e) { S.ootProducts = []; }
  render();
}
async function pickProduct(code, name) {
  S.code = code; S.productName = name; S.query = `${code}  ${name}`; S.open = false; S.lot = null; S.yearFilter = '전체'; S.lotQuery = '';
  render();
  try { S.lotSummary = await getJSON(`/api/oot/lots?code=${encodeURIComponent(code)}&test_type=${encodeURIComponent(S.ootTestType)}`); S.years = S.lotSummary.years; }
  catch (e) { S.lotSummary = { lots: [], years: ['전체'] }; S.years = ['전체']; }
  render();
}
async function loadStabProducts() {
  try { const d = await getJSON(`/api/stability/products?test_type=${encodeURIComponent(S.stabTestType)}`); S.stabProducts = d.products; S.stabTestTypes = d.testTypes; if (!S.stabCode && d.products.length) S.stabCode = d.products[0].code; }
  catch (e) { S.stabProducts = []; }
  loadStability();
}
async function ensureStability(force) {
  if (!S.stabProducts.length) { await loadStabProducts(); return; }
  if (force || !S.stabData) loadStability();
}
async function loadStability() {
  if (!S.stabCode) { render(); return; }
  S.stabLoading = true; render();
  const p = new URLSearchParams({ code: S.stabCode, test_type: S.stabTestType, spec_low: S.specLow || '90', spec_high: S.specHigh || '150', method: S.method });
  if (S.stabTestItem) p.set('test_item', S.stabTestItem);
  if (S.stabBatch) p.set('batch', S.stabBatch);
  try { S.stabData = await getJSON(`/api/stability?${p}`); if (S.stabData.ok) { S.stabName = ''; S.stabTestItem = S.stabData.testItem; } }
  catch (e) { S.stabData = { ok: false, reason: '분석 실패: ' + e.message }; }
  S.stabLoading = false; render();
  loadStabTables();
}
async function loadStabTables() {
  if (!S.stabCode) return;
  const key = `${S.stabCode}|${S.specLow}|${S.specHigh}|${S.stabTestType}|${S.stabBatch || ''}`;
  if (key === S.stabTablesKey && S.stabTables) return;   // 동일 조건이면 재요청 안 함
  S.stabTablesKey = key;
  try {
    const p = new URLSearchParams({ code: S.stabCode, test_type: S.stabTestType, spec_low: S.specLow || '90', spec_high: S.specHigh || '150' });
    if (S.stabBatch) p.set('batch', S.stabBatch);
    S.stabTables = await getJSON(`/api/stability/tables?${p}`);
  } catch (e) { S.stabTables = null; }
  render();
}
async function loadAlarm() {
  try { S.alarm = await getJSON('/api/alarm/config'); } catch (e) {}
  S.alarmDirty = false;
  render();
}
async function saveAlarm() {
  try {
    await postJSON('/api/alarm/config', S.alarm);
    S.alarmDirty = false; render();
    const s = $('#alarm-status'); if (s) { s.textContent = '✓ 저장되었습니다'; s.style.color = '#15803d'; }
  } catch (e) {
    const s = $('#alarm-status'); if (s) { s.textContent = '저장 실패: ' + e.message; s.style.color = '#dc2626'; }
  }
}
async function unlockAlarm() {
  const i = $('#alarm-pw'); if (!i) return;
  try {
    const r = await postJSON('/api/alarm/auth', { password: i.value });
    if (r.ok) { S.alarmAuthed = true; S.alarmFromEnv = r.fromEnv; render(); }
    else { const e = $('#alarm-pw-err'); if (e) e.textContent = '비밀번호가 일치하지 않습니다.'; i.value = ''; i.focus(); }
  } catch (e) { const el = $('#alarm-pw-err'); if (el) el.textContent = '확인 실패: ' + e.message; }
}
async function testSend() {
  const m = $('#alarm-test-msg'); if (m) { m.textContent = '발송 중…'; m.style.color = '#5b6573'; }
  try { const r = await postJSON('/api/alarm/test', {}); if (m) { m.textContent = (r.ok ? '✓ ' : '✗ ') + r.msg; m.style.color = r.ok ? '#15803d' : '#dc2626'; } }
  catch (e) { if (m) { m.textContent = '발송 실패: ' + e.message; m.style.color = '#dc2626'; } }
}
async function changePw() {
  const cur = $('#pw-cur'), nw = $('#pw-new'), msg = $('#pw-msg');
  if (!cur || !nw) return;
  try {
    const r = await postJSON('/api/alarm/password', { current: cur.value, new: nw.value });
    if (msg) { msg.textContent = (r.ok ? '✓ ' : '✗ ') + (r.msg || ''); msg.style.color = r.ok ? '#15803d' : '#dc2626'; }
    if (r.ok) { cur.value = ''; nw.value = ''; }
  } catch (e) { if (msg) { msg.textContent = '변경 실패: ' + e.message; msg.style.color = '#dc2626'; } }
}

/* ============================ INIT ============================ */
loadOotProducts();
getJSON('/api/alarm/config').then(c => { S.alarm = c; if (S.nav === 'oot') render(); }).catch(() => {});
