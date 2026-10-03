/* 광동 품질·시험 통합 대시보드 — 프론트엔드 (vanilla JS, 디자인 1:1 재현) */
'use strict';

const S = {
  nav: 'oot',
  // OOT
  ootTestType: '완제품', ootProducts: [], query: '', open: false, ootProdLoading: false,
  code: null, productName: '', lotSummary: null, years: ['전체'], lotsLoading: false,
  yearFilter: '전체', lotQuery: '', lot: null, ootComp: null,
  ootStabData: null, ootStabKey: '', ootStabLoading: false,
  // Stability
  stabTestType: '시판후 안정성시험(Ongoing Stability)', stabProducts: [],
  stabCode: null, stabName: '', stabFromOot: false,
  specLow: '90', specHigh: '150', method: 'pooled', stabTestItem: null,
  stabData: null, stabLoading: false, stabTables: null, stabTablesKey: '', stabBatch: null,
  // Alarm
  alarm: { policy: '관리이탈만', recipients: [], interval: '매일 07:30', night: true,
           schedule: { mode: 'daily', daily_time: '07:30', interval_min: 10 } },
  alarmAuthed: false, alarmFromEnv: false, alarmDirty: false,
  // 알람·발송 이력 패널
  hist: null, histLoading: false, histErr: '', histDays: 30, histTab: 'sent', histTT: '', histQ: '',
  histKind: 'key', histOpen: {}, histLimit: 200,
  // 수신자 마스터 DB + 시험종류별 그룹
  recipDb: [], groups: {}, recipTestTypes: [], activeTT: '완제품', recipDirty: false, dbSearch: '',
  // 동일품목군 (APQR 풀링 OOT)
  groupTestType: '완제품', groupCatalog: [], groupCatalogKey: '', groupQuery: '', groupOpen: false,
  groupMembers: [], groupItems: [], groupItem: '', groupList: [], groupName: '',
  groupYear: String(new Date().getFullYear()), groupYears: [],   // 기본 = 당해년도
  groupResults: [], groupPooledLoading: false, groupMsg: '', groupProg: null,   // 전 시험항목 풀링 결과 + 진행률
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
// ── 로딩/진행 상태 공통 UI ─────────────────────────────────────────
function spinnerHTML(sz) { const s = sz || 20, bw = Math.max(2, Math.round(s / 9)); return `<span style="width:${s}px;height:${s}px;border:${bw}px solid #f0d5cd;border-top-color:#E5310F;border-radius:50%;display:inline-block;animation:spin .8s linear infinite;flex:0 0 auto"></span>`; }
function loadingCard(msg, sub) {
  return `<div style="background:#fff;border:1px solid #e2e7ef;border-radius:16px;padding:38px 26px;text-align:center;margin-top:16px">
    <div style="margin:0 auto;width:34px;height:34px;border:3px solid #f0d5cd;border-top-color:#E5310F;border-radius:50%;animation:spin .8s linear infinite"></div>
    <div style="font-size:14px;font-weight:600;color:#46536a;margin-top:15px">${esc(msg)}</div>
    ${sub ? `<div style="font-size:12px;color:#9aa4b4;margin-top:6px">${esc(sub)}</div>` : ''}</div>`;
}
function loadingRow(msg) { return `<div style="display:flex;align-items:center;gap:9px;font-size:13px;font-weight:600;color:#5b6573;padding:5px 0">${spinnerHTML(16)}<span>${esc(msg)}</span></div>`; }

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
    <div data-act="home" title="홈으로" style="display:flex;flex-direction:column;align-items:stretch;gap:11px;padding:4px 2px 0;cursor:pointer">
      <div style="width:100%;background:#fff;border-radius:12px;padding:13px 16px;box-shadow:0 4px 12px rgba(0,0,0,.22);display:flex;align-items:center;justify-content:center">
        <img src="./kwangdong_logo.png" alt="광동제약 CI" draggable="false" style="width:100%;height:auto;display:block">
      </div>
      <div><div style="color:#fff;font-weight:700;font-size:19px;letter-spacing:-.01em">광동제약</div>
        <div style="font-size:13px;color:#8c98ae;font-weight:600;margin-top:3px;letter-spacing:-.01em">품질관리팀 OOT 관리 플랫폼</div></div>
    </div>
    <button data-act="home" style="margin-top:16px;display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:10px;border:1px solid #2c2f38;border-radius:10px;background:#20232b;color:#cdd8ea;font-size:13px;font-weight:600;cursor:pointer">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FF8A5C" stroke-width="2.2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M9 22V12h6v10"></path></svg>홈</button>
    <div style="margin-top:18px">
      <div style="font-size:10.5px;font-weight:600;letter-spacing:.08em;color:#5d6b86;padding:0 8px 10px">모니터링</div>
      <button data-act="nav" data-nav="oot" style="${navBtn(n === 'oot')}"><span style="${navBar(n === 'oot')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'oot')}" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>OOT 빠른 조회</button>
      <button data-act="nav" data-nav="stability" style="${navBtn(n === 'stability')}"><span style="${navBar(n === 'stability')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'stability')}" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 7-6 7-4-3-4 5"></path></svg>안정성 회귀분석</button>
      <button data-act="nav" data-nav="group" style="${navBtn(n === 'group')}"><span style="${navBar(n === 'group')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'group')}" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>APQR용 조회(참고용)</button>
    </div>
    <div style="margin-top:18px">
      <div style="font-size:10.5px;font-weight:600;letter-spacing:.08em;color:#5d6b86;padding:0 8px 10px">설정</div>
      <button data-act="nav" data-nav="alarm" style="${navBtn(n === 'alarm')}"><span style="${navBar(n === 'alarm')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'alarm')}" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>알림 설정</button>
      <button data-act="nav" data-nav="history" style="${navBtn(n === 'history')}"><span style="${navBar(n === 'history')}"></span>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="${navIcon(n === 'history')}" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"></path><path d="M3 3v5h5"></path><path d="M12 7v5l3 2"></path></svg>알람 발송 이력</button>
    </div>
    <button data-act="refresh" style="margin-top:22px;display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:11px;border:1px solid #2c2f38;border-radius:10px;background:#20232b;color:#cdd8ea;font-size:13px;font-weight:600;cursor:pointer">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FF8A5C" stroke-width="2.2"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>데이터 새로고침</button>
    <div style="margin-top:auto;background:#1f2128;border:1px solid #2c2f38;border-radius:12px;padding:13px 14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px"><span style="width:7px;height:7px;border-radius:50%;background:#34d27b;animation:pulseDot 1.8s infinite"></span><span style="font-size:12px;font-weight:600;color:#dbe3f0">알람 감시 정상</span></div>
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px"><span style="color:#6b7a96">데이터원</span><span style="color:#c3cee0;font-family:${MONO}">광동제약_gmp_lims</span></div>
      <div style="display:flex;justify-content:space-between;font-size:11px"><span style="color:#6b7a96">서버</span><span style="color:#c3cee0;font-family:${MONO}">Databricks</span></div>
    </div>
  </aside>`;
}

function topbar() {
  const crumb = S.nav === 'oot' ? ['OOT 관리', '빠른 조회'] : S.nav === 'stability' ? ['안정성', '회귀분석'] : S.nav === 'history' ? ['설정', '알람 발송 이력'] : ['설정', '알림'];
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

/* 처음 사용자 안내 — 상단 단계 바 */
function stepGuide(steps, active) {
  return `<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:-6px 0 16px;padding:10px 15px;background:#f7f9fc;border:1px solid #e5eaf1;border-radius:12px">
    <span style="font-size:11px;font-weight:700;color:#8a94a6;letter-spacing:.03em;margin-right:2px">사용 순서</span>
    ${steps.map((s, i) => {
      const cur = i === active, done = i < active;
      return `<span style="display:inline-flex;align-items:center;gap:6px">
        <span style="display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;border-radius:50%;font-size:11px;font-weight:700;${cur ? 'background:#E5310F;color:#fff' : done ? 'background:#f6d5cb;color:#E5310F' : 'background:#e2e7ef;color:#98a2b3'}">${i + 1}</span>
        <span style="font-size:12px;font-weight:${cur ? '700' : '500'};color:${cur ? '#27303f' : done ? '#5b6573' : '#9aa4b4'}">${esc(s)}</span>
      </span>${i < steps.length - 1 ? '<span style="color:#c3cdda">→</span>' : ''}`;
    }).join('')}
  </div>`;
}

/* 처음 사용자 안내 — 빈 화면 시작 가이드(단계 카드). steps는 HTML 허용. */
function startGuide(title, steps) {
  return `<div style="background:#fff;border:1px dashed #cfd6e0;border-radius:16px;padding:38px 28px;text-align:center">
    <div style="width:54px;height:54px;border-radius:50%;background:#fdece8;display:flex;align-items:center;justify-content:center;margin:0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg></div>
    <div style="font-size:15.5px;font-weight:700;color:#27303f;margin-top:14px">${esc(title)}</div>
    <div style="display:inline-flex;flex-direction:column;gap:9px;margin-top:15px;text-align:left">
      ${steps.map((s, i) => `<div style="display:flex;align-items:center;gap:10px"><span style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:#E5310F;color:#fff;font-size:12px;font-weight:700;flex:0 0 auto">${i + 1}</span><span style="font-size:13px;color:#46536a">${s}</span></div>`).join('')}
    </div></div>`;
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
  if (S.lotsLoading || (S.code && !S.lotSummary)) return loadingRow('제조번호(LOT) 조회 중…');
  if (!S.code || !S.lotSummary) return `<div style="font-size:13px;color:#9aa4b4;padding:2px 0">품목코드를 먼저 선택하세요.</div>`;
  const segBase = `font-family:${MONO};font-size:12px;font-weight:600;padding:5px 11px;border-radius:7px;cursor:pointer;border:none`;
  const yearChips = S.years.map(y => {
    const sel = S.yearFilter === y;
    const st = sel ? segBase + ';background:#fff;color:#27303f;box-shadow:0 1px 2px rgba(20,30,50,.12)' : segBase + ';background:transparent;color:#7a8699';
    return `<button data-act="pickYear" data-year="${esc(y)}" style="${st}">${esc(y)}</button>`;
  }).join('');
  const lots = S.lotSummary.lots;
  const yq = (S.yearFilter && S.yearFilter !== '전체') ? `&year=${encodeURIComponent(S.yearFilter)}` : '';
  const xlsUrl = `/api/oot/excel?code=${encodeURIComponent(S.code)}&test_type=${encodeURIComponent(S.ootTestType)}${yq}`;
  return `<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:13px">
      <span style="font-size:11px;font-weight:600;color:#8a94a6;letter-spacing:.02em">제조번호 (LOT)</span>
      <div style="display:flex;gap:3px;background:#eef1f6;border:1px solid #e2e7ef;border-radius:9px;padding:3px">${yearChips}</div>
      <div style="position:relative;margin-left:2px">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#a6b0c0" stroke-width="2.2" style="position:absolute;left:10px;top:50%;transform:translateY(-50%)"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
        <input id="lot-search" value="${esc(S.lotQuery)}" placeholder="LOT 검색" style="width:128px;padding:7px 10px 7px 29px;border:1px solid #d7dce4;border-radius:8px;font-size:12.5px;font-family:${MONO};outline:none;background:#fff"></div>
      <div style="margin-left:auto;display:flex;align-items:center;gap:10px">
        <span id="lot-count" style="font-size:11.5px;color:#9aa4b4;font-family:${MONO}">표시 ${lots.length} / 전체 ${lots.length}</span>
        <a href="${xlsUrl}" title="현재 조회(연도 반영) 엑셀 리포트" style="display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border:1.5px solid #E5310F;border-radius:9px;background:#fff;color:#E5310F;font-size:12px;font-weight:600;text-decoration:none"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5"></path><path d="M12 15V3"></path></svg>엑셀 다운로드(${S.yearFilter === '전체' ? '전체기간' : S.yearFilter + '년'})</a>
      </div>
    </div>
    <div class="lotscroll" style="max-height:104px;overflow-y:auto;border:1px solid #e7ebf1;border-radius:10px;background:#fff;padding:11px 12px"><div id="lot-chips" style="display:flex;gap:7px;flex-wrap:wrap">${lotChips()}</div></div>`;
}

function lotChips() {
  // 연도 필터는 백엔드(롤링 윈도우)가 이미 반영 → 프론트는 LOT 검색만 적용.
  const lots = (S.lotSummary ? S.lotSummary.lots : []).filter(l =>
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

// 조회문 규칙이 계산에서 뺀 줄 각주(서버 lots[].excluded = {까닭: 건수}).
function excludedNote(lot) {
  const ex = lot.excluded || {};
  const parts = [];
  if (ex['재시험 원값(잠정)']) parts.push(`재시험 원값 ${ex['재시험 원값(잠정)']}건 계산 제외(잠정 규칙: 적부 N/A 원시험 무효)`);
  if (ex['거짓 0']) parts.push(`거짓 0 ${ex['거짓 0']}건 제외(원문은 숫자인데 저장값만 0)`);
  return parts.length ? `<div style="font-size:11.5px;color:#9aa4b4;margin-top:6px;line-height:1.5">${parts.map(esc).join('<br>')}</div>` : '';
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

// σ가 판정에 쓸 수 있을 만큼 유효한지(0/부동소수점 잡음 방지). 아니면 null.
// 측정값이 추세선에 완전 일치하면 잔차 se≈0 → σ로 나누면 잡음이 폭증하므로 제외.
function usableSigma(A, b) {
  for (const s of [A && A.sigma, b && b.se]) {
    if (s != null && isFinite(s) && s > 1e-6) return s;
  }
  return null;
}

function ootStabSummary() {
  if (!S.ootComp || S.ootStabLoading) return { ready: false };
  const A = S.ootStabData;
  if (!A || !A.ok) return { ready: false };
  const use = ootStabBatches();
  if (!use.length) return { ready: false };
  let crit = 0, warn = 0, normal = 0;
  use.forEach(b => {
    const sg = usableSigma(A, b);
    b.pts.forEach(p => {
      if (b.slope != null && sg) {
        const az = Math.abs((p[1] - (b.intercept + b.slope * p[0])) / sg);
        if (az > 3) crit++; else if (az > 2) warn++; else normal++;
      } else normal++;   // σ≈0(추세 완전일치) 또는 회귀불가 → 정상 처리
    });
  });
  return { ready: true, crit, warn, normal, n: crit + warn + normal };
}

function ootStabTpTable() {
  const box = (msg) => `<div style="margin-top:18px;background:#fff;border:1px dashed #cfd6e0;border-radius:13px;padding:28px;text-align:center;color:#9aa4b4;font-size:13px">${msg}</div>`;
  if (!S.ootComp) return box('위 <b>시점별 OOT 관리도</b>에서 성분(시험항목)을 선택하면 시점별 판정이 표시됩니다.');
  if (S.ootStabLoading) return box('시점 데이터 불러오는 중…');
  const A = S.ootStabData;
  if (!A || !A.ok) return box(A && A.reason ? esc(A.reason) : '시점 데이터를 산출할 수 없습니다.');
  const use = ootStabBatches();
  if (!use.length) return box('선택한 배치의 시점 데이터가 없습니다.');
  let nOot = 0, nWarn = 0, sigZero = false;
  const multi = use.length > 1;
  const rowsHtml = use.flatMap(b => {
    const sg = usableSigma(A, b);
    return b.pts.map(p => {
      const m = p[0], v = p[1];
      const pred = b.slope != null ? b.intercept + b.slope * m : null;
      let dev = null, az = 0, judge;
      if (pred == null) {
        judge = '판정불가';
      } else if (!sg) {                    // σ≈0: 측정값이 추세선에 완전 일치 → 정상
        sigZero = true; judge = '정상';
      } else {
        dev = (v - pred) / sg; az = Math.abs(dev);
        if (az > 3) { nOot++; judge = '⚠ OOT'; } else if (az > 2) { nWarn++; judge = '주의'; } else { judge = '정상'; }
      }
      const C = az > 3 ? { fg: '#b91c1c', bg: '#fef2f2', tb: '#fde0e0' } : az > 2 ? { fg: '#b45309', bg: '#fffbeb', tb: '#fdedc4' } : { fg: '#15803d', bg: '#fff', tb: '#ecfdf3' };
      const devColor = az > 3 ? '#dc2626' : az > 2 ? '#d97706' : '#5b6573';
      const devTxt = dev == null ? (pred == null ? '—' : '≈0') : (dev >= 0 ? '+' : '−') + Math.abs(dev).toFixed(2) + 'σ';
      return `<div style="display:grid;grid-template-columns:.8fr 1fr 1fr 1fr 1fr 1.2fr;border-top:1px solid #f2f4f8;background:${C.bg};font-size:12.5px">
        <div style="padding:10px 12px;font-family:${MONO};color:#5b6573">${multi ? esc(b.batch) : '·'}</div>
        <div style="padding:10px 12px;text-align:right;font-family:${MONO};color:#27303f">${m}</div>
        <div style="padding:10px 12px;text-align:right;font-family:${MONO};color:#27303f">${fmt(v, 2)}</div>
        <div style="padding:10px 12px;text-align:right;font-family:${MONO};color:#5b6573">${pred == null ? '—' : fmt(pred, 2)}</div>
        <div style="padding:10px 12px;text-align:right;font-family:${MONO};font-weight:600;color:${devColor}">${devTxt}</div>
        <div style="padding:10px 12px"><span style="font-size:11.5px;font-weight:600;padding:3px 10px;border-radius:999px;background:${C.tb};color:${C.fg}">${judge}</span></div></div>`;
    });
  }).join('');
  const ss = 'margin-top:13px;padding:11px 15px;border-radius:11px;font-size:12.5px;font-weight:600';
  const sum = nOot ? `<div style="${ss};background:#fef2f2;color:#b91c1c">⚠ OOT ${nOot}건 — ±3σ 관리한계 이탈. 원인조사 대상.</div>`
    : nWarn ? `<div style="${ss};background:#fffbeb;color:#b45309">주의 ${nWarn}건 — 추세선 ±2σ~±3σ 구간.</div>`
      : sigZero ? `<div style="${ss};background:#eef2ff;color:#3730a3">σ≈0 — 측정값이 추세선에 완전 일치(직선). 잔차분산이 0이라 ±2σ/±3σ 관리한계·σ편차 판정은 적용할 수 없어 <b>정상</b> 처리합니다. (규격 이탈 여부는 규격선 기준으로 판단)</div>`
      : `<div style="${ss};background:#f1fbf4;color:#15803d">시점간 OOT 없음 — 모든 시점이 추세선 ±2σ 이내.</div>`;
  return `<div style="margin-top:18px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">시점별 시험결과</span><span style="font-size:11.5px;color:#9aa4b4">${esc(A.testItem)} · 추세선 대비 ±2σ(주의)/±3σ(관리한계) 판정</span></div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden">
      <div style="display:grid;grid-template-columns:.8fr 1fr 1fr 1fr 1fr 1.2fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:9px 12px">배치</div><div style="padding:9px 12px;text-align:right">시점(개월)</div><div style="padding:9px 12px;text-align:right">측정값</div><div style="padding:9px 12px;text-align:right">추세예측</div><div style="padding:9px 12px;text-align:right">σ편차</div><div style="padding:9px 12px">판정</div></div>
      ${rowsHtml}</div>${sum}</div>`;
}

function ootResults() {
  if (S.lotsLoading || (S.code && !S.lotSummary)) return loadingCard('데이터 조회 · 결과 계산 중…', '선택 연도 기준으로 관리한계(평균·±3σ)를 재계산하고 있습니다.');
  const lot = S.lot && S.lotSummary ? S.lotSummary.lots.find(l => l.lot === S.lot) : null;
  if (!lot) {
    if (!S.code) return startGuide('품목을 선택하면 OOT 판정이 표시됩니다', [
      '상단에서 <b>시험종류</b> 선택',
      '<b>품목코드·품목명</b>으로 검색 후 선택',
      '<b>연도</b>를 고르면 그 해 기준으로 관리한계 재계산',
      '<b>제조번호(LOT)</b> 클릭 → 판정 확인 · <b>엑셀 다운로드</b>',
    ]);
    return `<div style="background:#fff;border:1px dashed #cfd6e0;border-radius:16px;padding:48px 24px;text-align:center">
      <div style="width:56px;height:56px;border-radius:50%;background:#eef1f6;display:flex;align-items:center;justify-content:center;margin:0 auto"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg></div>
      <div style="font-size:15px;font-weight:600;color:#5b6573;margin-top:14px">위의 <b>제조번호(LOT)</b>를 클릭하면 판정 결과가 표시됩니다</div>
      <div style="font-size:13px;color:#9aa4b4;margin-top:6px">연도 선택 시 그 해 데이터로 관리한계가 재계산됩니다</div></div>`;
  }
  // 배너 집계: 완제품 등은 로트별(lotSummary), 안정성은 선택성분의 시점별 판정 기준
  const stab = isStabType(S.ootTestType);
  const sm = stab ? ootStabSummary() : null;
  let kpiVals, lastKpi;
  if (stab && sm && sm.ready) { kpiVals = { crit: sm.crit, warn: sm.warn, normal: sm.normal }; lastKpi = ['시점 수', sm.n, '#94a3b8']; }
  else if (stab) { kpiVals = { crit: 0, warn: 0, normal: 0 }; lastKpi = ['시점 수', 0, '#94a3b8']; }
  else { kpiVals = { crit: lot.crit, trend: lot.trend || 0, warn: lot.warn, normal: lot.normal }; lastKpi = ['정성 제외', lot.qual, '#94a3b8']; }
  const trendN = kpiVals.trend || 0;
  const st = kpiVals.crit > 0 ? 'red' : (kpiVals.warn > 0 || trendN > 0) ? 'yellow' : 'green';
  const TH = { red: { bg: '#fef4f4', bd: '#f6c9c9', fg: '#b91c1c' }, yellow: { bg: '#fffcf2', bd: '#f3dd9f', fg: '#b45309' }, green: { bg: '#f1fbf4', bd: '#bcecca', fg: '#15803d' } }[st];
  const headline = (stab && !(sm && sm.ready))
    ? '성분(시험항목)을 선택하면 시점별 판정이 표시됩니다'
    : st === 'red' ? `관리이탈 ${kpiVals.crit}건 — 확인 필요`
      : st === 'yellow' ? (trendN > 0 && kpiVals.warn === 0 ? `경향이탈 ${trendN}건 발생` : `주의 ${kpiVals.warn}건${trendN > 0 ? ' · 경향 ' + trendN + '건' : ''} 발생`)
        : (stab ? '시점간 이상 없음' : '이상 없음');
  const icon = st === 'red'
    ? `<div style="width:48px;height:48px;border-radius:13px;background:#fde0e0;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.2"><path d="M12 8v5"></path><circle cx="12" cy="16.5" r=".6" fill="#dc2626"></circle><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg></div>`
    : st === 'yellow'
      ? `<div style="width:48px;height:48px;border-radius:13px;background:#fdecc8;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.2"><path d="M12 9v4"></path><circle cx="12" cy="16.5" r=".6" fill="#d97706"></circle><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg></div>`
      : `<div style="width:48px;height:48px;border-radius:13px;background:#cdf2da;display:flex;align-items:center;justify-content:center;flex:0 0 auto"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.4"><path d="M5 12.5 10 17.5 19.5 7"></path></svg></div>`;
  const kpiBox = 'background:rgba(255,255,255,.6);border:1px solid rgba(20,30,50,.06);border-radius:11px;padding:9px 14px;min-width:66px;text-align:center';
  const kpi = (lab, val, col) => `<div style="${kpiBox}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">${lab}</div><div style="font-family:${MONO};font-size:19px;font-weight:600;color:${col}">${val}</div></div>`;

  const items = lot.items.map(it => {
    const crit = it.status === '관리이탈', trend = it.status === '경향이탈';
    const z = it.z == null ? 0 : it.z, pos = Math.max(2, Math.min(98, (z + 3) / 6 * 100));
    const C = crit ? { dot: '#ef4444', bg: '#fef2f2', bd: '#fbcaca', tagBg: '#fde0e0', tagFg: '#b91c1c' }
      : trend ? { dot: '#8b5cf6', bg: '#f7f5ff', bd: '#ddd3fb', tagBg: '#ece5fd', tagFg: '#6d28d9' }
        : { dot: '#f59e0b', bg: '#fffbeb', bd: '#fbe2a8', tagBg: '#fdedc4', tagFg: '#b45309' };
    const tagTxt = crit ? '관리이탈 · ±3σ 초과'
      : trend ? '경향이탈 · ' + (it.rules || []).join(', ')
        : '주의 · ±2σ~±3σ';
    return `<div style="display:block;background:${C.bg};border:1px solid ${C.bd};border-radius:13px;padding:16px 17px">
      <div style="display:flex;align-items:center;gap:10px"><span style="width:10px;height:10px;border-radius:50%;flex:0 0 auto;background:${C.dot}"></span>
        <span style="font-size:15px;font-weight:600">${esc(it.name)}</span>
        <span style="margin-left:auto;font-size:11.5px;font-weight:600;padding:4px 11px;border-radius:999px;background:${C.tagBg};color:${C.tagFg}">${esc(tagTxt)}</span></div>
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

  const si = S.lotSummary ? S.lotSummary.sampleInfo : null;
  const sampleBanner = (si && si.short) ? `<div style="margin:13px 2px 0;background:#fffbeb;border:1px solid #fbe2a8;border-radius:11px;padding:11px 15px;display:flex;align-items:center;gap:10px">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#b45309" stroke-width="2.2"><path d="M12 9v4"></path><circle cx="12" cy="16.5" r=".6" fill="#b45309"></circle><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg>
      <span style="font-size:12.5px;color:#92400e;line-height:1.5"><b>표본 ${si.lots}개 로트</b> — 통계 권장 최소 ${si.min}개 미만입니다(${esc(si.mode)} 기준). σ·판정을 참고용으로 보시고, 더 많은 표본이 필요하면 <b>전체</b>를 선택하십시오.</span></div>` : '';

  const ootBlock = lot.items.length ? `<div style="margin-top:18px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:11px"><span style="font-size:14.5px;font-weight:700">OOT 항목</span><span style="font-family:${MONO};font-size:12px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">${lot.items.length}</span></div>
      <div style="display:flex;flex-direction:column;gap:10px">${items}</div>
      <div style="font-size:12px;color:#9aa4b4;margin-top:12px;line-height:1.5">정상 ${lot.normal}개 항목 · 정성항목(미생물·확인·성상 등) ${lot.qual}개 σ 판정 제외</div>${excludedNote(lot)}</div>`
    : `<div style="margin-top:18px;background:#fff;border:1px solid #e3e7ee;border-radius:13px;padding:16px 18px;display:flex;align-items:center;gap:10px">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.4"><path d="M5 12.5 10 17.5 19.5 7"></path></svg>
      <span style="font-size:14px;font-weight:600;color:#15803d">정상 ${lot.normal}개 항목 · OOT 없음</span>
      <span style="color:#9aa4b4;font-weight:500;margin-left:auto;font-size:12.5px">정성항목 ${lot.qual}개 제외</span></div>${excludedNote(lot)}`;

  return `<div style="display:flex;gap:18px;align-items:center;padding:22px 24px;border-radius:16px;border:1px solid ${TH.bd};background:${TH.bg};box-shadow:0 1px 3px rgba(20,30,50,.05);flex-wrap:wrap">
      ${icon}
      <div style="flex:1"><div style="color:${TH.fg};font-size:25px;font-weight:700;letter-spacing:-.015em;line-height:1.2">${headline}</div>
        <div style="font-size:13.5px;color:#5b6573;margin-top:7px">LOT ${esc(lot.lot)} · ${esc(S.productName)} · 품목코드 ${esc(S.code)}</div></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-self:stretch">
        ${kpi('관리이탈', kpiVals.crit, '#dc2626')}${!stab ? kpi('경향이탈', trendN, '#7c3aed') : ''}${kpi('주의', kpiVals.warn, '#d97706')}${kpi('정상', kpiVals.normal, '#16a34a')}${kpi(lastKpi[0], lastKpi[1], lastKpi[2])}</div></div>
    <div style="display:flex;align-items:center;gap:12px;margin:13px 2px 0;flex-wrap:wrap">
      <button data-act="jumpStab" style="display:flex;align-items:center;gap:8px;padding:9px 15px;border:1.5px solid #E5310F;border-radius:10px;background:#fff;color:#E5310F;font-size:12.5px;font-weight:600;cursor:pointer">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 7-6 7-4-3-4 5"></path></svg>이 품목 안정성 분석</button></div>
    ${sampleBanner}
    ${isStabType(S.ootTestType) ? ootStabTpTable() : ootBlock + normalItemsTable(lot)}`;
}

function ootRail() {
  const policyChip = S.alarm.policy === '관리이탈만' ? '관리이탈(±3σ) 발생 시 메일 발송' : '관리이탈·주의 발송';
  return `<aside style="flex:1 1 320px;min-width:300px;display:flex;flex-direction:column;gap:14px">
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;padding:16px 18px;box-shadow:0 1px 3px rgba(20,30,50,.05)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:13px"><span style="width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulseDot 1.8s infinite"></span><span style="font-weight:700;font-size:14.5px">실시간 OOT 알람</span><span style="margin-left:auto;font-size:11px;font-weight:600;color:#15803d;background:#ecfdf3;padding:3px 9px;border-radius:999px">감시 중</span></div>
      <div style="display:flex;flex-direction:column;gap:9px">
        <div style="display:flex;justify-content:space-between;font-size:12.5px"><span style="color:#8a94a6">감시 대상</span><span style="font-weight:600">전체(모든 시험종류)</span></div>
        <div style="display:flex;justify-content:space-between;font-size:12.5px"><span style="color:#8a94a6">실행 주기</span><span style="font-weight:600;font-family:${MONO}">${esc(S.alarm.interval)}</span></div></div>
      <div style="margin-top:12px;padding-top:13px;border-top:1px solid #eef1f5">
        <div style="font-size:11px;color:#8a94a6;margin-bottom:7px">발송 정책</div>
        <span style="font-size:12.5px;font-weight:600;color:#E5310F;background:#fdece8;padding:5px 11px;border-radius:8px">${esc(policyChip)}</span>
        <div style="font-size:11px;color:#9aa4b4;margin-top:11px;line-height:1.55">신규 OOT만 발송(중복 자동 차단). 실시간성은 Databricks LIMS 적재 주기(매일 새벽)에 종속됩니다.</div></div></div>
  </aside>`;
}

function ootCompList() {
  if (!S.lotSummary) return [];
  const names = new Set();
  S.lotSummary.lots.forEach(l => (l.normalItems || []).concat(l.items || []).forEach(it => {
    if (it.sd != null && it.sd > 0) names.add(it.name);
  }));
  return [...names].sort((a, b) => a.localeCompare(b, 'ko'));
}

function ootCompData(comp) {
  const rows = [];
  let mean = null, sd = null, specLo = null, specHi = null, spec = null, sdRaw = null, sdFloored = false;
  S.lotSummary.lots.forEach(l => {
    const it = (l.normalItems || []).concat(l.items || []).find(x => x.name === comp);
    if (it && it.val != null) {
      rows.push([l.lot, it.val, l.seq || l.lot]);
      if (mean == null) { mean = it.mean; sd = it.sd; specLo = it.specLo; specHi = it.specHi; spec = it.spec; sdRaw = it.sdRaw; sdFloored = it.sdFloored; }
    }
  });
  rows.sort((a, b) => String(a[2]).localeCompare(String(b[2])));   // 시계열(의뢰일자|제조번호) 오름차순
  return { rows, mean, sd, specLo, specHi, spec, sdRaw, sdFloored };
}

function isStabType(t) { return /안정성|stability|long ?term|ongoing|accel/i.test(t || ''); }
function stabTicks(t) {
  if (/가속|accel/i.test(t)) return [0, 3, 6];
  if (/시판후|ongoing/i.test(t)) return [0, 12, 24, 36];
  return [0, 3, 6, 9, 12, 18, 24, 36];  // 장기·4b장기 등
}

async function loadOotStab() {
  if (!(S.nav === 'oot' && S.code && isStabType(S.ootTestType) && S.ootComp)) return;
  const key = [S.code, S.ootTestType, S.ootComp].join('|');
  if (S.ootStabKey === key && S.ootStabData) { renderOotCompChart(); return; }
  S.ootStabKey = key; S.ootStabLoading = true; renderOotCompChart();
  try {
    const p = new URLSearchParams({ code: S.code, test_type: S.ootTestType, test_item: S.ootComp, method: 'pooled' });
    if (S.specLow) p.set('spec_low', S.specLow);
    if (S.specHigh) p.set('spec_high', S.specHigh);
    S.ootStabData = await getJSON('/api/stability?' + p);
  } catch (e) { S.ootStabData = { ok: false, reason: String(e) }; }
  S.ootStabLoading = false; render();
}

function ootStabBatches() {
  const A = S.ootStabData;
  if (!A || !A.ok) return [];
  const b = S.lot ? A.batches.filter(x => String(x.batch) === String(S.lot)) : A.batches;
  return b.filter(x => x.pts && x.pts.length);
}

function buildOotStabPlotly() {
  const use = ootStabBatches();
  if (!use.length) return null;
  const A = S.ootStabData;
  const allM = use.flatMap(b => b.pts.map(p => p[0]));
  const maxData = allM.length ? Math.max(...allM) : 0;
  // 기본 스케줄(시판후·장기·4b=36개월, 가속=6개월). 데이터가 더 길면 그때만 눈금 연장.
  const ticks = stabTicks(S.ootTestType).slice();
  const step = /가속|accel/i.test(S.ootTestType) ? 3 : 12;
  while (ticks[ticks.length - 1] < maxData) ticks.push(ticks[ticks.length - 1] + step);
  const xMax = ticks[ticks.length - 1] + (step === 3 ? 0.6 : 1.5);
  const sigma = A.sigma;
  const data = [];
  use.forEach(b => {
    data.push({ x: b.pts.map(p => p[0]), y: b.pts.map(p => p[1]), mode: 'markers+text', text: b.pts.map(p => fmt(p[1], 1)), textposition: 'top center', textfont: { size: 10, color: '#46536a' }, marker: { color: b.color || '#2a78d6', size: 9, line: { color: '#fff', width: 1.3 } }, type: 'scatter', name: '배치 ' + b.batch, hovertemplate: `배치 ${b.batch}<br>%{x}개월 · %{y}<extra></extra>` });
    if (b.slope != null) {
      const xb = b.lastT || Math.max(...b.pts.map(p => p[0]));
      data.push({ x: [0, xb], y: [b.intercept, b.intercept + b.slope * xb], mode: 'lines', line: { color: b.color || '#2a78d6', width: 2 }, hoverinfo: 'skip', showlegend: false, type: 'scatter' });
      const sg = usableSigma(A, b);   // σ≈0이면 밴드가 추세선에 붙어 무의미 → 생략
      if (sg) {
        const seg = (k, c, d) => data.push({ x: [0, xb], y: [b.intercept + k * sg, b.intercept + b.slope * xb + k * sg], mode: 'lines', line: { color: c, width: 1, dash: d }, hoverinfo: 'skip', showlegend: false, type: 'scatter' });
        seg(2, '#eda100', 'dash'); seg(-2, '#eda100', 'dash'); seg(3, '#7c6fdd', 'dot'); seg(-3, '#7c6fdd', 'dot');
      }
    }
  });
  const shapes = [];
  if (A.specLow != null) shapes.push({ type: 'line', x0: 0, x1: xMax, y0: A.specLow, y1: A.specLow, line: { color: '#dc2626', width: 1.4, dash: 'dash' } });
  if (A.specHigh != null) shapes.push({ type: 'line', x0: 0, x1: xMax, y0: A.specHigh, y1: A.specHigh, line: { color: '#dc2626', width: 1.4, dash: 'dash' } });
  const layout = { height: 380, margin: { l: 48, r: 16, t: 14, b: 48 }, xaxis: { title: '시점 (개월)', tickvals: ticks.filter(t => t <= xMax), range: [-1.5, xMax + 1], gridcolor: '#f5f6f9', zeroline: false }, yaxis: { title: '결과값', gridcolor: '#eef1f5', zeroline: false }, shapes, plot_bgcolor: '#fff', paper_bgcolor: '#fff', font: { family: 'Pretendard Variable, sans-serif', size: 11 }, hovermode: 'closest' };
  return { data, layout, config: { displayModeBar: false, responsive: true } };
}

function ootCompStabSection() {
  const comps = ootCompList();
  const opts = `<option value="">성분(시험항목) 선택…</option>` +
    comps.map(c => `<option value="${esc(c)}" ${c === S.ootComp ? 'selected' : ''}>${esc(c)}</option>`).join('');
  const lotNote = S.lot ? `배치 ${esc(S.lot)}` : '전체 배치';
  const sel = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-size:13px;font-weight:700">시점별 OOT 관리도</span>
      <div style="position:relative">
        <select data-act="ootComp" style="appearance:none;padding:9px 32px 9px 12px;border:1px solid #d7dce4;border-radius:9px;font-size:13px;font-weight:600;color:#27303f;background:#fff;cursor:pointer;min-width:220px">${opts}</select>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:11px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div>
      <span style="font-size:11.5px;color:#9aa4b4">${esc(lotNote)} · 시점(개월)별 추세 ±2σ/±3σ · ${esc(S.ootTestType)}</span></div>`;
  if (!S.ootComp) {
    return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">${sel}</div>`;
  }
  const A = S.ootStabData;
  let strip = '', legend = '';
  if (A && A.ok && !S.ootStabLoading) {
    const pts = ootStabBatches().flatMap(b => b.pts.map(p => p[1]));
    const tile = (lab, val, col) => `<div style="background:#fafbfd;border:1px solid #eef1f5;border-radius:10px;padding:8px 13px;min-width:62px"><div style="font-size:10px;color:#8a94a6;margin-bottom:2px">${lab}</div><div style="font-family:${MONO};font-size:14.5px;font-weight:600;color:${col || '#27303f'}">${val}</div></div>`;
    strip = `<div style="display:flex;gap:9px;flex-wrap:wrap;margin:14px 0 4px">
      ${tile('규격하한', A.specLow != null ? A.specLow : '—', '#b91c1c')}
      ${tile('규격상한', A.specHigh != null ? A.specHigh : '—', '#b91c1c')}
      ${tile('최소값', fmt(pts.length ? Math.min(...pts) : null, 2))}
      ${tile('최대값', fmt(pts.length ? Math.max(...pts) : null, 2))}
      ${tile('평균값', fmt(pts.length ? pts.reduce((a, c) => a + c, 0) / pts.length : null, 2))}
      ${tile('표준편차 σ', (A.sigma != null && A.sigma > 1e-6) ? fmt(A.sigma, 3) : '≈0', '#6d28d9')}
      ${tile('시점 수', pts.length)}</div>`;
    legend = `<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px;font-size:11.5px;color:#5b6573">
      <span style="display:flex;align-items:center;gap:5px"><span style="width:9px;height:9px;border-radius:50%;background:#2a78d6"></span>측정값</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px solid #2a78d6"></span>추세선</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dashed #eda100"></span>±2σ 주의</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dotted #7c6fdd"></span>±3σ 관리한계</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dashed #dc2626"></span>규격</span></div>`;
  }
  const body = S.ootStabLoading ? `<div style="padding:48px;text-align:center;color:#9aa4b4">시점 데이터 불러오는 중…</div>`
    : (A && !A.ok ? `<div style="padding:40px;text-align:center;color:#9aa4b4">${esc(A.reason || '시점 데이터를 산출할 수 없습니다.')}</div>`
      : `<div id="oot-comp-chart" style="min-height:360px"></div>`);
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    ${sel}${strip}${legend}${body}</div>`;
}

function ootCompSection() {
  if (!S.code || !S.lotSummary) return '';
  if (isStabType(S.ootTestType)) return ootCompStabSection();
  const comps = ootCompList();
  if (!comps.length) return '';
  const opts = `<option value="">성분(시험항목) 선택…</option>` +
    comps.map(c => `<option value="${esc(c)}" ${c === S.ootComp ? 'selected' : ''}>${esc(c)}</option>`).join('');
  const sel = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span style="font-size:13px;font-weight:700">성분별 LOT 관리도</span>
      <div style="position:relative">
        <select data-act="ootComp" style="appearance:none;padding:9px 32px 9px 12px;border:1px solid #d7dce4;border-radius:9px;font-size:13px;font-weight:600;color:#27303f;background:#fff;cursor:pointer;min-width:220px">${opts}</select>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:11px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div>
      <span style="font-size:11.5px;color:#9aa4b4">선택한 성분의 전체 LOT 값을 평균±2σ/±3σ와 비교합니다.</span></div>`;
  if (!S.ootComp) {
    return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">${sel}</div>`;
  }
  const { rows, mean, sd, sdRaw, sdFloored, spec } = ootCompData(S.ootComp);
  const vals = rows.map(r => r[1]);
  let nOot = 0, nWarn = 0;
  vals.forEach(v => { const z = sd ? Math.abs((v - mean) / sd) : 0; if (z > 3) nOot++; else if (z > 2) nWarn++; });
  const tile = (lab, val, col) => `<div style="background:#fafbfd;border:1px solid #eef1f5;border-radius:10px;padding:8px 13px;min-width:62px"><div style="font-size:10px;color:#8a94a6;margin-bottom:2px">${lab}</div><div style="font-family:${MONO};font-size:14.5px;font-weight:600;color:${col || '#27303f'}">${val}</div></div>`;
  const strip = `<div style="display:flex;gap:9px;flex-wrap:wrap;margin:14px 0 4px">
    ${tile('평균 μ', fmt(mean, mean != null && mean < 10 ? 3 : 2))}
    ${tile('표준편차 σ', fmt(sd, sd != null && sd < 10 ? 3 : 2), '#6d28d9')}
    ${tile('최소값', fmt(vals.length ? Math.min(...vals) : null, 2))}
    ${tile('최대값', fmt(vals.length ? Math.max(...vals) : null, 2))}
    ${tile('LOT 수', rows.length)}
    ${tile('주의(2~3σ)', nWarn, nWarn ? '#b45309' : '#27303f')}
    ${tile('관리이탈(3σ↑)', nOot, nOot ? '#b91c1c' : '#27303f')}</div>`;
  const legend = `<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px;font-size:11.5px;color:#5b6573">
    <span style="display:flex;align-items:center;gap:5px"><span style="width:9px;height:9px;border-radius:50%;background:#2a78d6"></span>정상 ±2σ</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:9px;height:9px;border-radius:50%;background:#eda100"></span>주의 2~3σ</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:9px;height:9px;border-radius:50%;background:#d03b3b"></span>관리이탈 3σ↑</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px solid #888"></span>중심선 μ</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dashed #eda100"></span>±2σ</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dotted #7c6fdd"></span>±3σ</span>
    <span style="display:flex;align-items:center;gap:5px"><span style="width:14px;height:0;border-top:2px dashed #c0392b"></span>규격 상·하한</span></div>`;
  const floorNote = sdFloored ? `<div style="margin:2px 0 8px;font-size:11.5px;color:#6d28d9;background:#f7f5ff;border:1px solid #e5ddfb;border-radius:8px;padding:7px 11px;display:inline-block">
    ⓘ 보고값이 반올림(분해능)돼 실측 σ=${fmt(sdRaw, 3)}가 매우 작아, <b>σ 하한(분해능 ${fmt(sd, 3)})</b>을 적용했습니다. 1단위 차이는 약 1σ로 판정됩니다.</div>` : '';
  const specNote = spec ? `<span style="font-size:11px;color:#9aa4b4;margin-left:8px">규격: ${esc(spec)}</span>` : '';
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    ${sel}${strip}${legend}${floorNote ? '<div>' + floorNote + specNote + '</div>' : ''}
    <div id="oot-comp-chart" style="min-height:360px"></div></div>`;
}

function buildOotCompPlotly() {
  const { rows, mean, sd, specLo, specHi } = ootCompData(S.ootComp);
  if (!rows.length || !sd) return null;
  const labels = rows.map(r => String(r[0])), vals = rows.map(r => r[1]);
  const colors = vals.map(v => { const z = Math.abs((v - mean) / sd); return z > 3 ? '#d03b3b' : z > 2 ? '#eda100' : '#2a78d6'; });
  const flat = y => labels.map(() => y);
  const lim = (y, c, d, w) => ({ x: labels, y: flat(y), mode: 'lines', line: { color: c, width: w || 1.4, dash: d }, hoverinfo: 'skip', showlegend: false, type: 'scatter' });
  const data = [
    lim(mean + 3 * sd, '#7c6fdd', 'dot'), lim(mean - 3 * sd, '#7c6fdd', 'dot'),
    lim(mean + 2 * sd, '#eda100', 'dash'), lim(mean - 2 * sd, '#eda100', 'dash'),
    lim(mean, '#888', 'solid'),
  ];
  // 규격 기준선(상한/하한) — 있으면 진한 빨강 굵은 파선(APQR 점검표 스타일)
  if (specHi != null) data.push(lim(specHi, '#c0392b', 'dash', 2));
  if (specLo != null) data.push(lim(specLo, '#c0392b', 'dash', 2));
  data.push(
    { x: labels, y: vals, mode: 'markers', marker: { color: colors, size: 9, line: { color: '#fff', width: 1.2 } }, showlegend: false, type: 'scatter',
      hovertemplate: rows.map(r => { const z = ((r[1] - mean) / sd).toFixed(2); const s = Math.abs(z) > 3 ? '관리이탈' : Math.abs(z) > 2 ? '주의' : '정상'; return `LOT ${r[0]}<br>결과값 ${r[1]} (z=${z}, ${s})<extra></extra>`; }) },
  );
  // y축 범위: 규격선까지 보이도록 여유 확보
  const ys = vals.concat([mean + 3 * sd, mean - 3 * sd]);
  if (specHi != null) ys.push(specHi);
  if (specLo != null) ys.push(specLo);
  const ymin = Math.min(...ys), ymax = Math.max(...ys), pad = (ymax - ymin) * 0.08 || 1;
  const anno = [];
  if (specHi != null) anno.push({ xref: 'paper', x: 1, y: specHi, xanchor: 'right', yanchor: 'bottom', text: `기준상한 ${specHi}`, showarrow: false, font: { size: 10, color: '#c0392b' } });
  if (specLo != null) anno.push({ xref: 'paper', x: 1, y: specLo, xanchor: 'right', yanchor: 'top', text: `기준하한 ${specLo}`, showarrow: false, font: { size: 10, color: '#c0392b' } });
  const layout = { height: 360, margin: { l: 48, r: 16, t: 12, b: 54 }, xaxis: { title: '제조번호 (LOT)', type: 'category', tickangle: -45, tickfont: { size: 10 }, gridcolor: '#f5f6f9' }, yaxis: { title: '결과값', gridcolor: '#eef1f5', zeroline: false, range: [ymin - pad, ymax + pad] }, annotations: anno, plot_bgcolor: '#fff', paper_bgcolor: '#fff', font: { family: 'Pretendard Variable, sans-serif', size: 11 }, hovermode: 'closest' };
  return { data, layout, config: { displayModeBar: false, responsive: true } };
}

function renderOotCompChart() {
  if (S.nav !== 'oot' || !S.ootComp || !window.Plotly) return;
  const el = document.getElementById('oot-comp-chart');
  if (!el) return;
  const fig = isStabType(S.ootTestType) ? buildOotStabPlotly() : buildOotCompPlotly();
  if (fig) window.Plotly.newPlot(el, fig.data, fig.layout, fig.config);
}

function ootPage() {
  const nameColor = S.productName ? '#27303f' : '#b8c0cc';
  return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', 'OOT 빠른 조회', 'Out Of Trend · LOT 판정',
      `데이터 출처: Databricks <span style="font-family:${MONO}">광동제약_gmp_lims</span>(LIMS 수정판) · ${esc(S.ootTestType)} 온디맨드 조회`)}
    ${stepGuide(['시험종류 선택', '품목 검색·선택', '연도 선택', 'LOT·엑셀 확인'], S.code ? (S.lot ? 3 : 2) : 1)}
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);position:relative;z-index:5">
      <div style="padding:18px 22px;display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end">
        <div style="flex:0 0 auto"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">시험종류</span>
          <div style="position:relative"><select data-act="ootTestType" style="appearance:none;padding:10px 34px 10px 14px;background:#eef1f6;border:1px solid #dde3ec;color:#3a4658;font-size:14px;font-weight:600;border-radius:10px;cursor:pointer">${OOT_TEST_TYPES.map(t => `<option ${t === S.ootTestType ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9aa4b4" stroke-width="2.2" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none"><path d="m6 9 6 6 6-6"></path></svg></div></div>
        <div style="flex:1 1 340px;min-width:260px;position:relative">
          <span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:flex;gap:7px;align-items:center">품목코드${S.ootProdLoading
            ? `<span style="display:inline-flex;align-items:center;gap:5px;background:#fff4ef;color:#E5310F;font-weight:600;padding:1px 8px;border-radius:5px;font-size:10px">${spinnerHTML(9)}품목 불러오는 중…</span>`
            : `<span style="background:#fdece8;color:#E5310F;font-weight:600;padding:1px 7px;border-radius:5px;font-size:10px">검색형 · ${S.ootProducts.length.toLocaleString()}개</span>`}</span>
          <input id="oot-search" value="${esc(S.query)}" placeholder="${S.ootProdLoading ? '품목 목록을 불러오는 중입니다…' : '코드 또는 품목명 입력 (예: 21039)'}" autocomplete="off" style="width:100%;padding:11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:14px;font-family:${MONO};color:#27303f;outline:none;background:#fff">
          <div id="oot-dropdown">${ootDropdown()}</div></div>
        <div style="flex:1 1 260px;min-width:200px"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">품목명 <span style="color:#b8c0cc;font-weight:500">(자동)</span></span>
          <div id="oot-pname" style="width:100%;padding:11px 13px;border:1px solid #e7ebf1;border-radius:10px;font-size:14px;background:#f8fafc;min-height:43px;color:${nameColor}">${esc(S.productName || '품목코드 선택 시 표시')}</div></div>
      </div>
      <div id="oot-lot-section" style="border-top:1px solid #eef1f5;background:#fafbfd;padding:16px 22px;border-radius:0 0 16px 16px">${ootLotControls()}</div>
    </div>
    <div id="oot-comp-section">${ootCompSection()}</div>
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
  const approved = A.accelerated ? 0 : (A.approvedMonths || 0);   // 가속은 허가선 미표시
  let xMax;
  if (A.accelerated) { xMax = Math.max(lastT, 6); }   // 가속=6개월 종료 → 외삽 금지
  else { xMax = Math.max(maxShelf, lastT, approved) * 1.12; xMax = Math.ceil(xMax / 3) * 3; if (xMax < 24) xMax = 24; }
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
  const approved = A.accelerated ? 0 : (A.approvedMonths || 0);   // 가속은 허가선 미표시
  let xMax;
  if (A.accelerated) { xMax = Math.max(lastT, 6); }   // 가속=6개월 종료 → 외삽 금지
  else { xMax = Math.max(maxShelf, lastT, approved) * 1.12; xMax = Math.ceil(xMax / 3) * 3; if (xMax < 24) xMax = 24; }
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
    data.push({ x: b.pts.map(p => p[0]), y: b.pts.map(p => p[1]), mode: 'markers+text', text: b.pts.map(p => fmt(p[1], 1)), textposition: 'top center', textfont: { size: 10, color: '#46536a' }, marker: { color: b.color, size: 9, line: { color: '#fff', width: 1.5 } }, name: '배치 ' + b.batch, legendgroup: b.batch, showlegend: false, type: 'scatter', hovertemplate: `배치 ${b.batch}<br>%{x}개월 · 함량 %{y}<extra></extra>` });
  });
  const shapes = [], annotations = [];
  if (specLow != null) { shapes.push({ type: 'line', x0: 0, x1: xMax, y0: specLow, y1: specLow, line: { color: '#dc2626', width: 1.5, dash: 'dash' } }); annotations.push({ x: xMax, y: specLow, xanchor: 'right', yanchor: 'bottom', text: '규격하한 ' + specLow, showarrow: false, font: { size: 10, color: '#dc2626' } }); }
  if (worst && worst.shelf != null) { shapes.push({ type: 'line', x0: worst.shelf, x1: worst.shelf, y0: yMin, y1: yMax, line: { color: '#16a34a', width: 1.5, dash: 'dot' } }); annotations.push({ x: worst.shelf, y: yMax, yanchor: 'top', text: worst.shelf.toFixed(1) + '개월', showarrow: false, font: { size: 10, color: '#16a34a' } }); }
  if (approved > 0 && approved <= xMax) { shapes.push({ type: 'line', x0: approved, x1: approved, y0: yMin, y1: yMax, line: { color: '#d97706', width: 1.5, dash: 'dash' } }); annotations.push({ x: approved, y: yMax, yanchor: 'top', text: '허가 ' + approved + '개월', showarrow: false, font: { size: 10, color: '#b45309' } }); }
  const yTitle = '함량 (' + (A.unit || '%') + ')';
  const layout = { height: 400, margin: { l: 46, r: 20, t: 26, b: 42 }, xaxis: { title: '시점 (개월)', tickvals: ticks, range: [0, xMax], gridcolor: '#f0f2f6', zeroline: false }, yaxis: { title: yTitle, range: [yMin, yMax], gridcolor: '#eef1f5', zeroline: false }, shapes, annotations, legend: { orientation: 'h', y: -0.2 }, plot_bgcolor: '#fff', paper_bgcolor: '#fff', font: { family: 'Pretendard Variable, sans-serif', size: 11 }, hovermode: 'closest' };
  return { data, layout, config: { displayModeBar: false, responsive: true } };
}

function renderStabChart() {
  if (S.nav !== 'stability' || !S.stabData || !S.stabData.ok || !window.Plotly) return;
  const el = document.getElementById('stab-chart');
  if (!el) return;
  const fig = buildPlotly(S.stabData);
  if (fig) { el.innerHTML = ''; window.Plotly.newPlot(el, fig.data, fig.layout, fig.config); }
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

// 유효기간 '산출불가' 사유 (표시 전용 — 계산값은 변경하지 않음)
function isAccelLimit(r) { return !!(r.limit && /가속/.test(r.limit)); }
function shelfNoteText(r) {
  if (isAccelLimit(r))
    return '가속 안정성시험은 6개월 종료 시험으로 유효기간(저장수명) 산출 대상이 아닙니다. 유의적 변화 평가용이며, 저장수명은 장기 안정성시험으로 산출합니다. (ICH Q1A/Q1E)';
  if (r.n != null && r.n < 3) return '데이터 부족 — 회귀에 필요한 시점이 부족합니다(3개 미만).';
  if (r.limit === '시작부터 규격 위반')
    return '초기(0개월) 95% 신뢰구간이 이미 규격선에 닿음 — 시점 수가 적고 측정 산포가 커서 CI가 넓습니다. 측정값 자체의 규격 적합 여부와는 별개입니다.';
  return r.limit ? ('산출 조건 미충족 — ' + r.limit) : '산출 조건 미충족';
}
function shelfCell(r) {
  if (r.shelf != null) return `<span style="color:#15803d">${r.shelf.toFixed(1)}</span>`;
  const why = shelfNoteText(r);
  const label = isAccelLimit(r) ? '해당없음*' : '산출불가*';
  return `<span title="${esc(why)}" style="cursor:help;color:#b45309;border-bottom:1px dotted #b45309">${label}</span>`;
}

function stabSummaryTable() {
  const t = S.stabTables;
  if (!t || !t.ok) return '';
  const list = S.method === 'pooled' ? t.summaryPooled : t.summaryIndep;
  if (!list || !list.length) return '';
  const anyNone = list.some(r => r.shelf == null);
  const rows = list.map(r => `<div style="display:grid;grid-template-columns:1.7fr .8fr .6fr .8fr .8fr .7fr .8fr .9fr;border-top:1px solid #f2f4f8;font-size:12px">
    <div style="padding:8px 12px;color:#27303f">${esc(r.component)}</div>
    <div style="padding:8px 12px;font-family:${MONO};color:#5b6573">${esc(r.batch)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.n}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.slope == null ? '—' : r.slope.toFixed(4)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.intercept == null ? '—' : r.intercept.toFixed(2)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};color:#5b6573">${r.r2 == null ? '—' : r.r2.toFixed(4)}</div>
    <div style="padding:8px 12px;color:#5b6573">${esc(r.trend)}</div>
    <div style="padding:8px 12px;text-align:right;font-family:${MONO};font-weight:600">${shelfCell(r)}</div></div>`).join('');
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <div style="font-size:14.5px;font-weight:700;margin-bottom:4px">선택 방식(${S.method === 'pooled' ? '통합' : '배치별 독립'}) 상세 요약 <span style="font-size:11.5px;font-weight:500;color:#9aa4b4">전 시험항목×배치</span></div>
    <div style="border:1px solid #e7ebf1;border-radius:12px;overflow:hidden;margin-top:8px">
      <div style="display:grid;grid-template-columns:1.7fr .8fr .6fr .8fr .8fr .7fr .8fr .9fr;background:#f5f7fa;border-bottom:1px solid #e7ebf1;font-size:11px;font-weight:600;color:#8a94a6">
        <div style="padding:8px 12px">시험항목</div><div style="padding:8px 12px">제조번호</div><div style="padding:8px 12px;text-align:right">데이터수</div><div style="padding:8px 12px;text-align:right">기울기 b</div><div style="padding:8px 12px;text-align:right">절편 a</div><div style="padding:8px 12px;text-align:right">R²</div><div style="padding:8px 12px">추세</div><div style="padding:8px 12px;text-align:right">유효기간</div></div>
      ${rows}</div>
    ${anyNone ? `<div style="margin-top:12px;padding:11px 14px;background:#fffbeb;border:1px solid #f3dd9f;border-radius:10px;font-size:11.8px;color:#8a5a09;line-height:1.6">
      <b>* 산출불가 / 해당없음</b> — 각 행에 마우스를 올리면 사유가 표시됩니다.
      <b>가속</b>은 6개월 종료 시험이라 유효기간 산출 대상이 아니며(ICH Q1A/Q1E),
      그 외에는 <b>0개월 시점에서 이미 95% 신뢰구간이 규격선에 닿는 경우</b>(시점 수가 적고 산포가 커서 CI가 넓음)입니다.
      <b>측정값 자체의 규격 적합 여부와는 별개</b>입니다.</div>` : ''}</div>`;
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
  return `<details open style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:18px 22px;margin-top:18px">
    <summary style="cursor:pointer;font-size:14.5px;font-weight:700;user-select:none;display:flex;align-items:center;gap:9px">📄 조회된 데이터 (원자료) <span style="font-size:11.5px;font-weight:500;color:#9aa4b4">분석 입력 데이터 ${t.raw.length}행 (0개월=완제품 출하 포함)</span>
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
    <div style="font-size:12.5px;color:#9aa4b4;margin-top:7px">데이터 출처: Databricks <span style="font-family:${MONO}">광동제약_gmp_lims</span>(LIMS 수정판) · <span style="font-family:${MONO}">의뢰 특이사항</span> → 시점(개월) · 함량 = <span style="font-family:${MONO}">LOT결과_0제외</span></div></div>`
    + stepGuide(['시험종류·품목 선택', '규격·방식 설정', '결과·엑셀 확인'], (A && A.ok) ? 2 : (S.stabCode ? 1 : 0));

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
      <div style="flex:0 0 auto"><span style="font-size:11px;font-weight:600;color:#8a94a6;margin-bottom:7px;display:block">함량 규격 (자동)</span>
        ${A && A.ok
          ? `<div style="display:flex;align-items:center;height:42px;padding:0 16px;border:1px solid #e7ebf1;border-radius:10px;background:#f5f7fa;font-family:${MONO};font-size:13.5px;font-weight:600;color:#27303f;white-space:nowrap">${esc(A.specText || '—')}</div>`
          : `<div style="display:flex;align-items:center;gap:8px">
          <input data-act="specLow" value="${esc(S.specLow)}" style="width:72px;padding:10px 11px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-family:${MONO};text-align:center;outline:none">
          <span style="color:#b8c0cc;font-weight:600">~</span>
          <input data-act="specHigh" value="${esc(S.specHigh)}" style="width:72px;padding:10px 11px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-family:${MONO};text-align:center;outline:none"></div>`}</div>
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
  const accel = !!A.accelerated;   // 가속: 6개월 종료 → 유효기간 산출 대상 아님
  const bGood = !!worst || accel;
  const bTH = accel
    ? { bg: '#eef2ff', bd: '#c7d2fe', fg: '#3730a3', tile: '#e0e7ff', icon: '#4f46e5' }
    : (bGood ? { bg: '#f1fbf4', bd: '#bcecca', fg: '#15803d', tile: '#cdf2da', icon: '#16a34a' } : { bg: '#fef4f4', bd: '#f6c9c9', fg: '#b91c1c', tile: '#fde0e0', icon: '#dc2626' });
  const skpi = 'background:rgba(255,255,255,.6);border:1px solid rgba(20,30,50,.06);border-radius:11px;padding:9px 14px;min-width:72px;text-align:center';
  const skpiBox = (lab, val, col, sz) => `<div style="${skpi}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">${lab}</div><div style="font-family:${MONO};font-size:${sz || 19}px;font-weight:600;color:${col}">${val}</div></div>`;
  const ootColor = A.nOot > 0 ? '#dc2626' : A.nWarn > 0 ? '#d97706' : '#16a34a';
  const shortWarn = A.approvedShort && worst;
  const shelfKpiColor = shortWarn ? '#b45309' : '#15803d';
  const apprStr = A.approvedMonths != null ? A.approvedMonths + '개월' : '—';
  const banner = `<div style="display:flex;gap:18px;align-items:center;padding:22px 24px;border-radius:16px;margin-top:18px;border:1px solid ${bTH.bd};background:${bTH.bg};box-shadow:0 1px 3px rgba(20,30,50,.05);flex-wrap:wrap">
    <div style="width:48px;height:48px;border-radius:13px;display:flex;align-items:center;justify-content:center;flex:0 0 auto;background:${bTH.tile}"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="${bTH.icon}" stroke-width="2.2"><path d="M5 12.5 10 17.5 19.5 7"></path></svg></div>
    <div style="flex:1;min-width:200px"><div style="font-size:11.5px;font-weight:600;color:#8a94a6;margin-bottom:5px">${accel ? '가속 안정성시험 · 6개월 종료' : '종합 판정 · worst-case'}</div>
      <div style="color:${bTH.fg};font-size:24px;font-weight:700;letter-spacing:-.015em;line-height:1.2">${accel ? '유효기간 산출 대상 아님' : (worst ? worst.shelf.toFixed(1) + '개월까지 안정성 유효' : '측정기간 내 규격 이탈 없음(적합)')}</div>
      <div style="font-size:13px;color:#5b6573;margin-top:7px">${accel
        ? esc(A.accelNote || '가속시험은 유의적 변화(significant change) 평가용이며, 저장수명은 장기 안정성시험으로 산출합니다. (ICH Q1A/Q1E)')
        : `제한 배치 <span style="font-family:${MONO};font-weight:600">${worst ? esc(worst.batch) : '—'}</span> · ${esc(A.testItem)} · ${worst ? '규격하한 ' + (A.specLow != null ? A.specLow : '—') + ' (CI 하한 교차)' : '추세·σ만 표시'}`}</div>
      ${shortWarn ? `<div style="margin-top:9px;display:inline-flex;align-items:center;gap:7px;background:#fffbeb;border:1px solid #f3dd9f;color:#b45309;font-size:12px;font-weight:600;padding:5px 11px;border-radius:9px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.2"><path d="M10.3 3.9 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path><path d="M12 9v4"></path><circle cx="12" cy="16.5" r=".5" fill="#d97706"></circle></svg>추정 저장수명(${worst.shelf.toFixed(1)}개월)이 허가 유효기간(${A.approvedMonths}개월)보다 짧습니다 — CI 기준 라벨 미충족 가능</div>` : ''}</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-self:stretch">
      ${skpiBox('추정 저장수명', accel ? '해당없음' : (worst ? worst.shelf.toFixed(1) : '—'), accel ? '#4f46e5' : shelfKpiColor, accel ? 13 : 19)}
      <div style="${skpi}"><div style="font-size:10.5px;color:#8a94a6;margin-bottom:3px">허가 유효기간</div><div style="font-family:${MONO};font-size:${accel ? 13 : 19}px;font-weight:600;color:#5b6573">${accel ? '해당없음' : apprStr}</div></div>
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
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:6px;flex-wrap:wrap"><span style="font-size:14.5px;font-weight:700">배치별 저장수명도</span><span style="font-size:11.5px;color:#9aa4b4">함량(${esc(A.unit || '%')}) vs 시점(개월) · 적합선 + 95% CI + 규격 + 유효기간 · 각 점 = 시점별 결과값${S.stabBatch ? ' · 배치 ' + esc(S.stabBatch) : ''}</span></div>
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
  return `<div style="padding:26px 30px 60px;max-width:1320px;width:100%">${head}${control}${banner}${ancovaPanel}${chartBlock}${stabSummaryTable()}${stabRawTable()}${footer}</div>`;
}

/* ============================ ALARM PAGE ============================ */
function recipientDbCard() {
  const q = (S.dbSearch || '').trim().toLowerCase();
  const filtered = S.recipDb.filter(r => !q || (r.name || '').toLowerCase().includes(q) || (r.email || '').toLowerCase().includes(q));
  const rows = filtered.length ? filtered.map(r => `<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;border-top:1px solid #f2f4f8">
    <span style="font-size:13px;font-weight:600;color:#27303f;min-width:64px">${esc(r.name || '—')}</span>
    <span style="font-family:${MONO};font-size:12px;color:#5b6573;flex:1;word-break:break-all">${esc(r.email)}</span>
    <button data-act="rmDbRecip" data-email="${esc(r.email)}" title="DB에서 삭제" style="border:none;background:transparent;color:#b91c1c;cursor:pointer;font-size:15px;line-height:1;padding:0 4px">×</button></div>`).join('') : `<div style="padding:14px;text-align:center;color:#9aa4b4;font-size:12.5px">결과 없음</div>`;
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px;margin-bottom:16px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="font-size:13.5px;font-weight:700">수신자 마스터 DB</span><span style="font-family:${MONO};font-size:12px;font-weight:600;color:#5b6573;background:#eef1f5;padding:2px 8px;border-radius:6px">${S.recipDb.length}</span></div>
    <div style="font-size:12px;color:#9aa4b4;margin-bottom:12px">사내 명부 기반. 아래에서 이름·이메일을 직접 추가하면 DB에 동기화됩니다.</div>
    <input id="db-search" value="${esc(S.dbSearch)}" placeholder="이름·이메일 검색" style="width:100%;max-width:300px;padding:8px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;outline:none;margin-bottom:10px">
    <div id="db-list" style="border:1px solid #e7ebf1;border-radius:10px;max-height:230px;overflow-y:auto;background:#fff">${rows}</div>
    <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
      <input id="db-name" placeholder="이름" style="width:120px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;outline:none">
      <input id="db-email" placeholder="email@ekdp.com" style="flex:1;min-width:180px;max-width:260px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;font-family:${MONO};outline:none">
      <button data-act="addDbRecip" style="display:flex;align-items:center;gap:7px;padding:9px 14px;border:1.5px dashed #c3cdda;border-radius:10px;background:#fff;color:#5b6573;font-size:12.5px;font-weight:600;cursor:pointer"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>추가</button>
      <span id="db-msg" style="font-size:12px;font-weight:600;align-self:center"></span></div></div>`;
}

function groupEditorCard() {
  const tts = S.recipTestTypes.length ? S.recipTestTypes : ['완제품'];
  const active = S.activeTT && tts.includes(S.activeTT) ? S.activeTT : tts[0];
  const cnt = tt => (S.groups[tt] || []).length;
  const badges = tts.map(tt => {
    const sel = tt === active, n = cnt(tt);
    return `<button data-act="selectTT" data-tt="${esc(tt)}" style="display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;cursor:pointer;font-size:11.5px;font-weight:600;border:1px solid ${sel ? '#E5310F' : '#e0e5ec'};background:${sel ? '#fdece8' : '#fff'};color:${sel ? '#E5310F' : '#5b6573'}">${esc(tt)}<span style="font-family:${MONO};background:${sel ? '#E5310F' : '#eef1f5'};color:${n ? (sel ? '#fff' : '#5b6573') : '#9aa4b4'};border-radius:999px;padding:0 6px;font-size:10.5px">${n}</span></button>`;
  }).join('');
  const members = (S.groups[active] || []).map(e => String(e).toLowerCase());
  const chips = S.recipDb.length ? S.recipDb.map(r => {
    const on = members.includes((r.email || '').toLowerCase());
    return `<button data-act="toggleMember" data-email="${esc(r.email)}" style="display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;cursor:pointer;font-size:12px;font-weight:600;border:1px solid ${on ? '#E5310F' : '#e0e5ec'};background:${on ? '#E5310F' : '#fff'};color:${on ? '#fff' : '#46536a'}">${on ? '✓ ' : ''}${esc(r.name || r.email)}</button>`;
  }).join('') : `<span style="font-size:12.5px;color:#9aa4b4">DB에 수신자가 없습니다. 위에서 추가하세요.</span>`;
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px;margin-bottom:16px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap"><span style="font-size:13.5px;font-weight:700">시험종류별 수신 그룹</span>
      <span style="font-size:11.5px;color:#9aa4b4">각 시험종류 알림은 해당 그룹에게만 발송</span>
      <button data-act="saveGroups" style="margin-left:auto;display:flex;align-items:center;gap:7px;padding:8px 14px;border:none;border-radius:10px;background:#E5310F;color:#fff;font-size:12px;font-weight:600;cursor:pointer">그룹 저장</button>
      <span id="grp-status" style="font-size:12px;font-weight:600;color:${S.recipDirty ? '#b45309' : '#9aa4b4'}">${S.recipDirty ? '● 미저장' : ''}</span></div>
    <div style="display:flex;gap:7px;flex-wrap:wrap;margin:12px 0 14px">${badges}</div>
    <div style="border-top:1px solid #eef1f5;padding-top:14px">
      <div style="font-size:12px;color:#5b6573;margin-bottom:10px"><b style="color:#E5310F">${esc(active)}</b> 그룹 수신자 선택 (클릭하여 추가/제외)</div>
      <div style="display:flex;gap:7px;flex-wrap:wrap;max-height:220px;overflow-y:auto">${chips}</div></div></div>`;
}

function updateDbList() {
  const l = document.getElementById('db-list'); if (!l) return;
  const q = (S.dbSearch || '').trim().toLowerCase();
  const filtered = S.recipDb.filter(r => !q || (r.name || '').toLowerCase().includes(q) || (r.email || '').toLowerCase().includes(q));
  l.innerHTML = filtered.length ? filtered.map(r => `<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;border-top:1px solid #f2f4f8">
    <span style="font-size:13px;font-weight:600;color:#27303f;min-width:64px">${esc(r.name || '—')}</span>
    <span style="font-family:${MONO};font-size:12px;color:#5b6573;flex:1;word-break:break-all">${esc(r.email)}</span>
    <button data-act="rmDbRecip" data-email="${esc(r.email)}" title="DB에서 삭제" style="border:none;background:transparent;color:#b91c1c;cursor:pointer;font-size:15px;line-height:1;padding:0 4px">×</button></div>`).join('') : `<div style="padding:14px;text-align:center;color:#9aa4b4;font-size:12.5px">결과 없음</div>`;
}

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

/* ===================== 알람·발송 이력 패널 (알림설정 우측) ===================== */
const HIST_KIND = {
  sent:   { t: '발송',     c: '#15803d', bg: '#ecfdf3' },
  fail:   { t: '발송실패', c: '#dc2626', bg: '#fef2f2' },
  skip:   { t: '생략',     c: '#b45309', bg: '#fffbeb' },
  error:  { t: '오류',     c: '#dc2626', bg: '#fef2f2' },
  detect: { t: '신규감지', c: '#E5310F', bg: '#fdece8' },
  check:  { t: '점검',     c: '#64748b', bg: '#f1f5f9' },
  system: { t: '시스템',   c: '#64748b', bg: '#f1f5f9' },
};
const HIST_KIND_FILTERS = [['key', '주요'], ['sent', '발송'], ['skip', '생략'], ['err', '실패·오류'], ['all', '전체']];
const HIST_DAYS = [[7, '최근 7일'], [30, '최근 30일'], [90, '최근 90일'], [0, '전체 기간']];

async function loadAlarmHistory() {
  S.histLoading = true; S.histErr = ''; updateHistPanel();
  try { S.hist = await getJSON('/api/alarm/history?days=' + S.histDays); }
  catch (e) { S.histErr = e.message || String(e); }
  S.histLoading = false; updateHistPanel();
}
const histWd = d => '일월화수목금토'[new Date(d + 'T00:00:00').getDay()];
const histNum = v => { const n = Number(v); return (v === '' || v == null || isNaN(n)) ? esc(v) : esc(String(Number(n.toPrecision(5)))); };
const histHas = (parts, q) => !q || parts.join(' ').toLowerCase().includes(q);
function histName(email) {
  const r = (S.recipDb || []).find(x => (x.email || '').toLowerCase() === email.toLowerCase());
  return r ? r.name : email;
}
function histTTChip(tt) {
  return tt ? `<span style="font-size:11px;font-weight:600;color:#46536a;background:#eef1f6;padding:2px 8px;border-radius:999px;white-space:nowrap">${esc(tt)}</span>` : '';
}
function histSentRows() {
  if (!S.hist) return [];
  const q = S.histQ.trim().toLowerCase();
  return S.hist.sent.filter(r => (!S.histTT || r.testType === S.histTT) &&
    histHas([r.product, r.code, r.lot, r.item, r.id, r.cls, r.recipients.join(' '), r.recipients.map(histName).join(' ')], q));
}
function histSentGroups() {
  const map = new Map();   // 메일 1통 = 같은 발송시각 + 같은 시험종류
  histSentRows().forEach(r => {
    const k = r.time + '|' + r.testType;
    if (!map.has(k)) map.set(k, { key: k, time: r.time, testType: r.testType, items: [], recipients: r.recipients });
    map.get(k).items.push(r);
  });
  return [...map.values()];
}
function histEvents() {
  if (!S.hist) return [];
  const q = S.histQ.trim().toLowerCase(), k = S.histKind;
  return S.hist.events.filter(e => {
    if (S.histTT && e.testType !== S.histTT) return false;
    if (k === 'key' && (e.kind === 'check' || e.kind === 'system')) return false;
    if (k === 'sent' && e.kind !== 'sent') return false;
    if (k === 'skip' && e.kind !== 'skip') return false;
    if (k === 'err' && e.kind !== 'fail' && e.kind !== 'error') return false;
    return histHas([e.text], q);
  });
}
function histStats() {
  if (!S.hist) return null;
  const tt = S.histTT, c = S.hist.counts || {};
  // 로그 집계는 서버가 기간 전체로 계산(counts[종류][시험종류] = 발생 횟수) — 화면 표시 줄 수 제한과 무관
  const n = kind => Object.entries(c[kind] || {}).reduce((a, [t, v]) => a + ((!tt || t === tt) ? v : 0), 0);
  const sent = S.hist.sent.filter(r => !tt || r.testType === tt);
  return {
    mails: new Set(sent.map(r => r.time + '|' + r.testType)).size,
    items: sent.length,
    skipped: n('skip'),
    errs: n('fail') + n('error'),
  };
}
function histSubHTML() {
  const h = S.hist; if (!h) return '이력을 불러오는 중…';
  const f = t => t ? esc(t.slice(5, 16)) : '—';
  return `마지막 점검 <b style="font-family:${MONO};color:#46536a">${f(h.lastCheck)}</b> · 마지막 발송 <b style="font-family:${MONO};color:#46536a">${f(h.lastSent)}</b>`;
}
function histTTOptions() {
  const tts = [...((S.hist && S.hist.testTypes) || [])];
  if (S.histTT && !tts.includes(S.histTT)) tts.push(S.histTT);
  return `<option value="">전체 시험종류</option>` + tts.map(t => `<option value="${esc(t)}" ${t === S.histTT ? 'selected' : ''}>${esc(t)}</option>`).join('');
}
function histDynHTML() {
  const st = histStats();
  const per = (HIST_DAYS.find(d => d[0] === S.histDays) || [0, ''])[1];
  const kpi = (label, val, unit, tab, kind, color, hint) => `<button data-act="histJump" data-tab="${tab}" data-kind="${kind}" title="${hint} — 클릭하면 해당 이력으로 이동"
      style="flex:1 1 180px;min-width:0;text-align:left;padding:14px 16px;border:1px solid #dfe4ec;border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(20,30,50,.05);cursor:pointer">
      <div style="font-size:12px;color:#8a94a6;white-space:nowrap">${label}</div>
      <div style="font-size:24px;font-weight:700;color:${color};font-family:${MONO};margin-top:4px">${st ? Number(val).toLocaleString() : '–'}<span style="font-size:12.5px;font-weight:600;color:#8a94a6;margin-left:3px">${unit}</span></div>
      <div style="font-size:11px;color:#aab3c0;margin-top:2px">${hint}</div></button>`;
  const tabBtn = (id, t, n) => {
    const on = S.histTab === id;
    return `<button data-act="histTab" data-tab="${id}" style="padding:9px 18px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;${on ? 'background:#fff;color:#1a2230;box-shadow:0 1px 2px rgba(20,30,50,.12)' : 'background:transparent;color:#7a8699'}">${t}${S.hist ? ` <span style="font-family:${MONO};color:${on ? '#E5310F' : '#9aa4b4'}">${Number(n).toLocaleString()}</span>` : ''}</button>`;
  };
  const kindChips = S.histTab !== 'log' ? '' : `<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${HIST_KIND_FILTERS.map(([k, t]) => {
    const on = S.histKind === k;
    return `<button data-act="histKind" data-kind="${k}" style="font-size:12px;font-weight:600;padding:6px 13px;border-radius:999px;cursor:pointer;${on ? 'border:1px solid #E5310F;background:#fdece8;color:#E5310F' : 'border:1px solid #e0e5ec;background:#fff;color:#7a8699'}">${t}</button>`;
  }).join('')}<span style="font-size:11px;color:#9aa4b4;margin-left:4px">주요 = 점검·시스템 로그 제외</span></div>`;
  return `<div style="font-size:11.5px;color:#9aa4b4;margin:0 0 8px">${esc(per)}${S.histTT ? ' · ' + esc(S.histTT) : ''} 요약</div>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      ${kpi('메일 발송', st && st.mails, '회', 'sent', '', '#1a2230', '알람 메일 발송 횟수')}
      ${kpi('알림 OOT', st && st.items, '건', 'sent', '', '#1a2230', '메일로 알린 OOT 건수')}
      ${kpi('발송 생략', st && st.skipped, '회', 'log', 'skip', '#b45309', '수신 그룹 미지정으로 생략')}
      ${kpi('실패·오류', st && st.errs, '회', 'log', 'err', st && st.errs ? '#dc2626' : '#1a2230', '발송 실패·조회/인터넷 오류')}</div>
    <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:16px">
      <div style="display:flex;gap:3px;background:#e6eaf0;border:1px solid #dde2ea;border-radius:10px;padding:3px">
        ${tabBtn('sent', '메일 발송 이력', histSentGroups().length)}${tabBtn('log', '알람 실행 로그', histEvents().length)}</div>${kindChips}</div>`;
}
function histEmpty(msg) {
  return `<div style="text-align:center;padding:60px 10px;color:#9aa4b4;font-size:13px">${msg}</div>`;
}
function histMore(total) {
  return total > S.histLimit ? `<button data-act="histMore" style="display:block;width:calc(100% - 32px);margin:14px 16px;padding:10px;border:1px dashed #d7dce4;border-radius:10px;background:#fff;color:#5b6573;font-size:12.5px;font-weight:600;cursor:pointer">더 보기 (${S.histLimit.toLocaleString()} / ${total.toLocaleString()})</button>` : '';
}
const HIST_TH = `position:sticky;top:0;z-index:2;background:#f5f7fa;text-align:left;font-size:11.5px;font-weight:700;color:#6b7686;padding:10px 12px;border-bottom:1px solid #dfe4ec;white-space:nowrap`;
const HIST_TD = `padding:9px 12px;border-bottom:1px solid #f1f4f8;font-size:12.5px;color:#27303f;vertical-align:top`;
function histSentHTML() {
  const groups = histSentGroups();
  if (!groups.length) return histEmpty(S.histQ || S.histTT ? '조건에 맞는 발송 이력이 없습니다.' : '이 기간에 발송된 메일이 없습니다.');
  const cols = ['품목', '품목코드', '제조번호(LOT)', '시험항목', '결과값', '평균 ± 표준편차', '분류', '알림ID'];
  const body = groups.slice(0, S.histLimit).map(g => {
    const day = g.time.slice(0, 10);
    const head = `<tr><td colspan="${cols.length}" style="padding:10px 12px;background:#fbf6f4;border-bottom:1px solid #f3e3dc;border-top:1px solid #f3e3dc">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="font-family:${MONO};font-size:13px;font-weight:700;color:#1a2230">${esc(day)} (${histWd(day)}) ${esc(g.time.slice(11, 16))}</span>${histTTChip(g.testType)}
        <span style="font-size:12.5px;color:#46536a">OOT <b>${g.items.length}</b>건 → 수신 <b>${g.recipients.length}</b>명</span>
        <span style="display:flex;flex-wrap:wrap;gap:4px">${g.recipients.map(m => `<span title="${esc(m)}" style="padding:2px 9px;border-radius:999px;background:#fdece8;color:#E5310F;font-size:11.5px;font-weight:600">${esc(histName(m))}</span>`).join('')}</span></div></td></tr>`;
    const rows = g.items.map(r => {
      const crit = (r.cls || '').includes('관리이탈');
      return `<tr>
        <td style="${HIST_TD};font-weight:600">${esc(r.product)}</td>
        <td style="${HIST_TD};font-family:${MONO};color:#8a94a6">${esc(r.code)}</td>
        <td style="${HIST_TD};font-family:${MONO}">${esc(r.lot)}</td>
        <td style="${HIST_TD}">${esc(r.item)}</td>
        <td style="${HIST_TD};font-family:${MONO};font-weight:700;text-align:right">${histNum(r.value)}</td>
        <td style="${HIST_TD};font-family:${MONO};color:#8a94a6;white-space:nowrap">${histNum(r.mean)} ± ${histNum(r.sd)}</td>
        <td style="${HIST_TD}"><span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;white-space:nowrap;${crit ? 'background:#fef2f2;color:#dc2626' : 'background:#fffbeb;color:#b45309'}">${esc(r.cls || '-')}</span></td>
        <td style="${HIST_TD};font-family:${MONO};font-size:11.5px;color:#aab3c0">${esc(r.id)}</td></tr>`;
    }).join('');
    return head + rows;
  }).join('');
  return `<table style="width:100%;border-collapse:separate;border-spacing:0">
    <thead><tr>${cols.map(c => `<th style="${HIST_TH}">${c}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>` + histMore(groups.length);
}
function histLogHTML() {
  const ev = histEvents();
  const trunc = S.hist.eventsTruncated ? `<div style="font-size:11.5px;color:#8a94a6;background:#f8fafc;border-bottom:1px solid #eef1f5;padding:8px 14px">최근 ${S.hist.events.length.toLocaleString()}줄까지 표시합니다 (기간 내 전체 ${S.hist.eventsTotal.toLocaleString()}줄 · 위 요약 수치는 전체 기준).</div>` : '';
  if (!ev.length) return trunc + histEmpty('조건에 맞는 로그가 없습니다.');
  let lastDay = '';
  const rows = ev.slice(0, S.histLimit).map(e => {
    const day = e.time.slice(0, 10);
    const dayRow = day !== lastDay ? `<tr><td colspan="4" style="padding:9px 12px 6px;background:#fafbfc;font-size:11.5px;font-weight:700;color:#8a94a6;border-bottom:1px solid #eef1f5">${esc(day)} (${histWd(day)})</td></tr>` : '';
    lastDay = day;
    const k = HIST_KIND[e.kind] || HIST_KIND.system;
    return `${dayRow}<tr>
      <td style="${HIST_TD};font-family:${MONO};color:#8a94a6;white-space:nowrap;width:90px">${esc(e.time.slice(11, 19))}</td>
      <td style="${HIST_TD};width:80px"><span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;white-space:nowrap;background:${k.bg};color:${k.c}">${k.t}</span></td>
      <td style="${HIST_TD};width:190px">${histTTChip(e.testType) || '<span style="color:#cbd2dc">—</span>'}</td>
      <td style="${HIST_TD};color:#46536a;word-break:break-all">${esc(e.text.replace(/^[✅⚠️\s]+/u, ''))}</td></tr>`;
  }).join('');
  return trunc + `<table style="width:100%;border-collapse:separate;border-spacing:0">
    <thead><tr><th style="${HIST_TH}">시각</th><th style="${HIST_TH}">종류</th><th style="${HIST_TH}">시험종류</th><th style="${HIST_TH}">내용</th></tr></thead><tbody>${rows}</tbody></table>` + histMore(ev.length);
}
function histBodyHTML() {
  if (S.histErr && !S.hist) return histEmpty(`이력을 불러오지 못했습니다: ${esc(S.histErr)}<br><button data-act="histRefresh" style="margin-top:10px;padding:7px 14px;border:1px solid #d7dce4;border-radius:8px;background:#fff;cursor:pointer">다시 시도</button>`);
  if (!S.hist) return `<div style="display:flex;justify-content:center;padding:60px">${spinnerHTML(24)}</div>`;
  return S.histTab === 'sent' ? histSentHTML() : histLogHTML();
}
// 알람 발송 이력 — 별도 메뉴(접근 제한 없음, 화면 최대 폭)
function historyPage() {
  const ctl = `padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:13px;color:#27303f;background:#fff`;
  const btn = `display:flex;align-items:center;gap:7px;padding:9px 14px;border:1px solid #d7dce4;border-radius:10px;background:#fff;color:#46536a;font-size:12.5px;font-weight:600;cursor:pointer;white-space:nowrap`;
  return `<div style="padding:26px 30px 40px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', '알람 발송 이력', '', 'OOT 알람 메일 발송 이력 · 알람 실행 로그 (조회 전용)')}
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:-6px 0 16px">
      <select data-act="histDays" style="${ctl}">${HIST_DAYS.map(([d, t]) => `<option value="${d}" ${d === S.histDays ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <select id="hist-tt" data-act="histTT" style="${ctl};min-width:200px">${histTTOptions()}</select>
      <input id="hist-q" value="${esc(S.histQ)}" placeholder="품목·품목코드·LOT·시험항목·알림ID·수신자 검색" style="${ctl};flex:1 1 320px;min-width:220px;outline:none">
      <span id="hist-sub" style="font-size:12px;color:#9aa4b4;white-space:nowrap">${histSubHTML()}</span>
      <button data-act="histCsv" title="현재 탭·필터 결과를 CSV로 저장" style="${btn}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#46536a" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="m7 10 5 5 5-5"></path><path d="M12 15V3"></path></svg>CSV 내보내기</button>
      <button data-act="histRefresh" title="새로고침" style="${btn}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#46536a" stroke-width="2"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>새로고침</button></div>
    <div id="hist-dyn">${histDynHTML()}</div>
    <div id="alarm-hist-body" style="margin-top:14px;background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);overflow:auto;max-height:calc(100vh - 150px);min-height:420px">${histBodyHTML()}</div>
  </div>`;
}
function ensureHistory() {
  if (!S.hist && !S.histLoading) loadAlarmHistory();
  if (!(S.recipDb || []).length) getJSON('/api/recipients/groups').then(g => { S.recipDb = g.recipients || []; updateHistPanel(); }).catch(() => {});
}

// 검색 입력 포커스를 유지하도록 패널의 가변 영역만 갱신
function updateHistPanel() {
  const sub = $('#hist-sub'), tt = $('#hist-tt'), dyn = $('#hist-dyn'), body = $('#alarm-hist-body');
  if (sub) sub.innerHTML = histSubHTML();
  if (tt) tt.innerHTML = histTTOptions();
  if (dyn) dyn.innerHTML = histDynHTML();
  if (body) body.innerHTML = histBodyHTML();
}
function histCsv() {
  const q = v => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
  let head, rows, name;
  if (S.histTab === 'sent') {
    head = ['발송일시', '알림ID', '시험종류', '품목', '품목코드', '제조번호', '시험항목', '결과값', '평균', '표준편차', '분류', '수신자'];
    rows = histSentRows().map(r => [r.time, r.id, r.testType, r.product, r.code, r.lot, r.item, r.value, r.mean, r.sd, r.cls, r.recipients.join('; ')]);
    name = 'OOT_메일발송이력';
  } else {
    head = ['일시', '종류', '시험종류', '내용'];
    rows = histEvents().map(e => [e.time, (HIST_KIND[e.kind] || HIST_KIND.system).t, e.testType, e.text]);
    name = 'OOT_알람실행로그';
  }
  if (!rows.length) { alert('내보낼 이력이 없습니다.'); return; }
  const csv = '﻿' + [head, ...rows].map(r => r.map(q).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = `${name}_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
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
  // ── 알람 실행 주기: 두 방식 중 1개만 적용(라디오 카드) ──
  const sch = al.schedule || { mode: 'daily', daily_time: '07:30', interval_min: 10 };
  const inp = `font-family:${MONO};font-size:14px;font-weight:600;padding:6px 9px;border:1px solid #d7dce4;border-radius:8px;color:#27303f;background:#fff`;
  const txt = `font-size:12.5px;color:#5b6573`;
  const schedOpt = (m, title, desc, body) => {
    const on = sch.mode === m;
    return `<div style="flex:1 1 210px;border-radius:12px;padding:13px 14px;${on ? 'border:1.5px solid #E5310F;background:#fdece8' : 'border:1px solid #e0e5ec;background:#f8fafc'}">
      <button data-act="schedMode" data-mode="${m}" style="display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;padding:0;cursor:pointer;text-align:left">
        <span style="width:16px;height:16px;border-radius:50%;border:2px solid ${on ? '#E5310F' : '#b8c1ce'};display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto">${on ? '<span style="width:8px;height:8px;border-radius:50%;background:#E5310F"></span>' : ''}</span>
        <span style="font-size:13px;font-weight:700;color:${on ? '#1a2230' : '#7a8699'}">${title}</span>
        <span style="margin-left:auto;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:999px;${on ? 'background:#E5310F;color:#fff' : 'background:#e6eaf0;color:#8a94a6'}">${on ? '적용 중' : '미적용'}</span></button>
      <div style="font-size:11.5px;color:#8a94a6;margin:6px 0 10px 24px">${desc}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-left:24px;${on ? '' : 'opacity:.45'}">${body(on)}</div></div>`;
  };
  const optDaily = schedOpt('daily', '매일 특정 시각', '하루 1번, 지정한 시각에 점검·발송',
    on => `<span style="${txt}">매일</span><input type="time" data-act="schedTime" value="${esc(sch.daily_time)}" style="${inp}" ${on ? '' : 'disabled'}><span style="${txt}">1회</span>`);
  const optInterval = schedOpt('interval', '주기 반복', '지정한 분 간격으로 계속 점검·발송',
    on => `<input type="number" min="1" max="1440" data-act="schedInterval" value="${esc(String(sch.interval_min))}" style="${inp};width:84px" ${on ? '' : 'disabled'}><span style="${txt}">분마다</span>`);
  const schedLabel = sch.mode === 'daily' ? `매일 ${sch.daily_time}` : `${sch.interval_min}분 주기`;
  const nextRunTxt = (() => {
    if (sch.mode !== 'daily') return `저장 후 1분 이내 첫 실행, 이후 ${sch.interval_min}분마다`;
    const [h, m] = String(sch.daily_time || '07:30').split(':').map(Number);
    const n = new Date(), t = new Date(n); t.setHours(h, m, 0, 0); if (t <= n) t.setDate(t.getDate() + 1);
    return `다음 실행 ${t.getMonth() + 1}/${t.getDate()}(${'일월화수목금토'[t.getDay()]}) ${sch.daily_time}`;
  })();
  const intChips = `<div style="display:flex;gap:10px;flex-wrap:wrap">${optDaily}${optInterval}</div>
    <div style="margin-top:12px;padding:11px 13px;background:#f8fafc;border:1px solid #eef1f5;border-radius:10px;font-size:12px;color:#46536a;line-height:1.65">
      <b style="color:#E5310F">${S.alarmDirty ? '선택됨(미저장)' : '현재 적용'}: ${esc(schedLabel)}</b> · ${esc(nextRunTxt)}${S.alarmDirty ? ' <span style="color:#b45309;font-weight:600">— [저장]을 눌러야 적용됩니다</span>' : ''}<br>
      <span style="color:#8a94a6">두 방식은 동시에 적용되지 않습니다. 선택한 1가지만 동작하며, 미적용 쪽 값은 보관만 됩니다.</span></div>`;
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
    ${recipientDbCard()}${groupEditorCard()}
    <div style="display:flex;gap:16px;flex-wrap:wrap">
      <div style="flex:1 1 100%;background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px">
        <div style="font-size:13.5px;font-weight:700;margin-bottom:4px">알람 실행 주기 <span style="font-size:11.5px;font-weight:600;color:#8a94a6">(둘 중 1가지 선택)</span></div>
        <div style="font-size:11.5px;color:#9aa4b4;margin-bottom:12px">저장하면 실행 중인 알람에 1분 이내 자동 반영됩니다.</div>
        ${intChips}</div>
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

/* ===================== 동일품목군 (APQR 풀링 OOT) ===================== */
const GROUP_TYPES = ['완제품', '원료시험', '반제품', '직접자재', '시험기기 및 기구', '기타시험'];

function ensureGroup() {
  if (!S.groupList.length) loadGroupList();
  loadGroupCatalog(false);
}
async function loadGroupList() {
  try { const r = await getJSON('/api/group/list'); S.groupList = r.groups || []; render(); } catch (e) {}
}
async function loadGroupCatalog(force) {
  if (!force && S.groupCatalogKey === S.groupTestType && S.groupCatalog.length) { render(); return; }
  try {
    const r = await getJSON('/api/group/items?test_type=' + encodeURIComponent(S.groupTestType));
    S.groupCatalog = r.catalog || []; S.groupCatalogKey = S.groupTestType; render();
  } catch (e) { S.groupMsg = '품목 목록 로드 실패: ' + e.message; render(); }
}
async function loadGroupItems() {
  const codes = S.groupMembers.map(m => m.code);
  if (!codes.length) { S.groupItems = []; S.groupYears = []; render(); return; }
  try {
    const r = await getJSON('/api/group/items?test_type=' + encodeURIComponent(S.groupTestType) + '&codes=' + encodeURIComponent(codes.join(',')));
    S.groupItems = r.testItems || [];       // 분석 가능 시험항목(전 연도 기준·개수 표시용)
    S.groupYears = r.years || [];
    if (S.groupYear !== '전체' && S.groupYears.length && !S.groupYears.includes(S.groupYear)) S.groupYear = '전체';
    render();
  } catch (e) { render(); }
}
function grpAddMember(code, name) {
  if (!S.groupMembers.some(m => m.code === code)) S.groupMembers.push({ code, name });
  S.groupQuery = ''; S.groupOpen = false; S.groupResults = [];
  render();            // 칩 즉시 표시(항목·연도는 백그라운드 로드)
  loadGroupItems();
}
function grpRemoveMember(code) {
  S.groupMembers = S.groupMembers.filter(m => m.code !== code);
  S.groupResults = [];
  render();
  loadGroupItems();
}
async function grpSave() {
  const name = (S.groupName || '').trim();
  if (!name || !S.groupMembers.length) { S.groupMsg = '그룹 이름과 품목을 지정하세요.'; render(); return; }
  try {
    const r = await postJSON('/api/group', { group_id: name, group_name: name, member_codes: S.groupMembers.map(m => m.code) });
    if (r.ok) { S.groupList = r.groups || S.groupList; S.groupMsg = '저장됨: ' + name; }
    else { S.groupMsg = r.detail || '저장 실패'; }
    render();
  } catch (e) { S.groupMsg = '저장 실패: ' + e.message; render(); }
}
function grpProgText(pr, pct) {   // 진행바 라벨(순수 텍스트)
  if (!pr) return '';
  const head = pr.done === 0 ? '데이터 불러오는 중' : '전 시험항목 OOT 분석 중';
  return `${head}… ${pr.done}/${pr.total} (${pct}%)` + (pr.cur ? ' · ' + pr.cur : '');
}
function updateGroupProgress() {   // 전체 재렌더 없이 진행바만 갱신(부드럽게)
  const pr = S.groupProg; if (!pr) return;
  const pct = pr.total ? Math.round(pr.done / pr.total * 100) : 0;
  const bar = document.getElementById('grp-prog-bar'); if (bar) bar.style.width = pct + '%';
  const txt = document.getElementById('grp-prog-text'); if (txt) txt.textContent = grpProgText(pr, pct);
}
async function grpAnalyzeAll() {
  if (S.groupMembers.length < 1) { S.groupMsg = '동일품목을 먼저 선택하세요.'; render(); return; }
  const codes = S.groupMembers.map(m => m.code);
  const year = (S.groupYear && S.groupYear !== '전체') ? S.groupYear : '';
  const items = (S.groupItems || []).slice();
  S.groupResults = []; S.groupMsg = '';
  S.groupPooledLoading = true; S.groupProg = { done: 0, total: items.length || 1, cur: items[0] || '' };
  render();
  // 시험항목 목록이 아직 준비 안됐으면 서버 일괄 경로로 폴백(진행률 없음)
  if (!items.length) {
    try {
      const r = await postJSON('/api/group/pooled_all', { codes, test_type: S.groupTestType, year });
      if (r.detail) { S.groupResults = []; S.groupMsg = r.detail; }
      else { S.groupResults = r.results || []; S.groupMsg = S.groupResults.length ? '' : '풀링 가능한(유효 2건 이상) 시험항목이 없습니다.'; }
    } catch (e) { S.groupResults = []; S.groupMsg = '분석 실패: ' + e.message; }
    S.groupPooledLoading = false; S.groupProg = null; render(); return;
  }
  // 항목별 순차 풀링 → 실제 진행률(첫 항목이 데이터 조회로 느리고, 이후는 캐시로 빠름)
  const out = [];
  for (let i = 0; i < items.length; i++) {
    S.groupProg = { done: i, total: items.length, cur: items[i] }; updateGroupProgress();
    try {
      const r = await postJSON('/api/group/pooled', { codes, test_type: S.groupTestType, test_item: items[i], year });
      if (!r.detail && r.n >= 2) out.push(r);
    } catch (e) { /* 해당 항목 건너뜀 */ }
  }
  S.groupProg = { done: items.length, total: items.length, cur: '' }; updateGroupProgress();
  S.groupResults = out;
  S.groupMsg = out.length ? '' : '풀링 가능한(유효 2건 이상) 시험항목이 없습니다.';
  S.groupPooledLoading = false; S.groupProg = null;
  render();
}
function grpPickSaved(gid) {
  const g = S.groupList.find(x => x.group_id === gid);
  if (!g) return;
  const byCode = Object.fromEntries(S.groupCatalog.map(c => [c.품목코드, c.품목명]));
  S.groupMembers = (g.member_codes || []).map(c => ({ code: c, name: byCode[c] || '' }));
  S.groupName = g.group_name || g.group_id; S.groupResults = []; S.groupMsg = '';
  loadGroupItems();
}
async function grpDelSaved(gid) {
  try { const r = await postJSON('/api/group/delete', { group_id: gid }); S.groupList = r.groups || S.groupList; render(); } catch (e) {}
}

function groupDropdown() {
  const q = (S.groupQuery || '').trim().toLowerCase();
  if (!S.groupOpen || !q) return '';
  const picked = new Set(S.groupMembers.map(m => m.code));
  const opts = S.groupCatalog.filter(c => !picked.has(c.품목코드) && (String(c.품목코드).includes(q) || (c.품목명 || '').toLowerCase().includes(q))).slice(0, 10);
  if (!opts.length) return '';
  return `<div style="position:absolute;top:100%;left:0;right:0;background:#fff;border:1px solid #dde3ec;border-radius:10px;margin-top:4px;box-shadow:0 8px 24px rgba(20,30,50,.13);z-index:30;overflow:hidden;max-height:300px;overflow-y:auto">
    ${opts.map(o => `<div data-act="grpAdd" data-code="${esc(o.품목코드)}" data-name="${esc(o.품목명)}" style="display:flex;align-items:center;gap:12px;padding:9px 13px;cursor:pointer;border-bottom:1px solid #f2f4f8" data-hover>
      <span style="font-family:${MONO};font-size:12.5px;color:#E5310F;font-weight:600">${esc(o.품목코드)}</span>
      <span style="font-size:13px;color:#27303f;flex:1">${esc(o.품목명)}</span>
      <span style="font-size:11px;color:#9aa4b4">추가 +</span></div>`).join('')}
  </div>`;
}
function groupMemberChips() {
  if (!S.groupMembers.length) return `<span style="font-size:12.5px;color:#9aa4b4">선택된 품목이 없습니다. 위에서 검색해 추가하세요.</span>`;
  return S.groupMembers.map(m => `<span style="display:inline-flex;align-items:center;gap:7px;background:#eef4ff;border:1px solid #d3e0f5;color:#27303f;font-size:12.5px;padding:6px 11px;border-radius:999px">
    <span style="font-family:${MONO};color:#2563eb;font-weight:600">${esc(m.code)}</span>${esc(m.name)}
    <button data-act="grpRemove" data-code="${esc(m.code)}" style="border:none;background:transparent;color:#8a94a6;cursor:pointer;font-size:14px;line-height:1;padding:0">×</button></span>`).join('');
}
function groupSavedList() {
  if (!S.groupList.length) return '';
  const rows = S.groupList.map(g => `<div style="display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid #f2f4f8">
    <button data-act="grpPick" data-gid="${esc(g.group_id)}" style="flex:1;text-align:left;border:none;background:transparent;cursor:pointer;font-size:12.5px;color:#27303f">
      <b>${esc(g.group_name || g.group_id)}</b> <span style="color:#9aa4b4">· ${(g.member_codes || []).length}개 코드 · ${esc((g.updated_at || '').slice(0, 10))}</span></button>
    <button data-act="grpDel" data-gid="${esc(g.group_id)}" title="삭제" style="border:none;background:transparent;color:#b91c1c;cursor:pointer;font-size:15px">×</button></div>`).join('');
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:16px 20px;margin-top:16px">
    <div style="font-size:13.5px;font-weight:700;margin-bottom:10px">저장된 동일품목군</div>
    <div style="border:1px solid #eef1f5;border-radius:10px;overflow:hidden">${rows}</div></div>`;
}
function groupResultsAll() {
  if (S.groupPooledLoading) {
    const pr = S.groupProg || { done: 0, total: 0, cur: '' };
    const pct = pr.total ? Math.round(pr.done / pr.total * 100) : 0;
    return `<div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:26px 26px 22px;margin-top:16px">
      <div style="display:flex;align-items:center;gap:11px;margin-bottom:14px">${spinnerHTML(22)}
        <span id="grp-prog-text" style="font-size:14px;font-weight:600;color:#46536a">${esc(grpProgText(pr, pct))}</span></div>
      <div style="height:9px;background:#eef1f6;border-radius:999px;overflow:hidden">
        <div id="grp-prog-bar" style="height:100%;width:${pct}%;background:linear-gradient(90deg,#E5310F,#ff7a45);border-radius:999px;transition:width .35s ease"></div></div>
      <div style="font-size:11.5px;color:#9aa4b4;margin-top:9px">${S.groupMembers.length}개 품목 · 첫 항목은 데이터 조회로 다소 걸릴 수 있고, 이후 항목은 캐시로 빠르게 처리됩니다.</div>
    </div>`;
  }
  const rs = S.groupResults || [];
  if (!rs.length) return '';
  const gyq = (S.groupYear && S.groupYear !== '전체') ? '&year=' + encodeURIComponent(S.groupYear) : '';
  const gxls = `/api/group/excel?codes=${encodeURIComponent(S.groupMembers.map(m => m.code).join(','))}&test_type=${encodeURIComponent(S.groupTestType)}${gyq}`;
  const totOot = rs.reduce((a, p) => a + (p.points || []).filter(x => x.oot_3s).length, 0);
  const totWarn = rs.reduce((a, p) => a + (p.points || []).filter(x => x.warn_2s).length, 0);
  const ylabel = (S.groupYear && S.groupYear !== '전체') ? `${S.groupYear}년 ` : '';
  return `<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:18px">
      <div style="font-size:15px;font-weight:700">${ylabel}전 시험항목 OOT · ${rs.length}개 항목</div>
      <div style="font-size:12.5px;font-weight:600"><span style="color:#d03b3b">OOT ${totOot}건</span> · <span style="color:#c47d00">주의 ${totWarn}건</span></div>
      <a href="${gxls}" title="전 시험항목 리포트(연도 반영) 엑셀" style="margin-left:auto;display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border:1.5px solid #E5310F;border-radius:9px;background:#fff;color:#E5310F;font-size:12px;font-weight:600;text-decoration:none"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E5310F" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="M7 10l5 5 5-5"></path><path d="M12 15V3"></path></svg>엑셀 다운로드(${S.groupYear === '전체' ? '전체기간' : S.groupYear + '년'}·전항목)</a>
    </div>
    ${rs.map((p, i) => groupItemCard(p, i)).join('')}`;
}
function groupItemCard(p, i) {
  const ootN = (p.points || []).filter(x => x.oot_3s).length;
  const warnN = (p.points || []).filter(x => x.warn_2s).length;
  const flag = ootN ? '#d03b3b' : warnN ? '#c47d00' : '#15803d';
  return `<div style="background:#fff;border:1px solid #dfe4ec;border-left:3px solid ${flag};border-radius:14px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:16px 20px;margin-top:12px">
    <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;margin-bottom:10px">
      <div style="font-size:13.5px;font-weight:700">${esc(p.시험항목)}</div>
      <div style="font-size:11.5px;color:#5b6573;font-family:${MONO}">n=${p.n} · 평균 ${fmt(p.mean, 3)} · σ ${fmt(p.std, 3)} · 3σ [${fmt(p.lcl_3s, 3)}, ${fmt(p.ucl_3s, 3)}]</div>
      <div style="margin-left:auto;font-size:11.5px;font-weight:600"><span style="color:#d03b3b">OOT ${ootN}</span> · <span style="color:#c47d00">주의 ${warnN}</span></div>
    </div>
    <div id="group-chart-${i}" style="min-height:300px"></div></div>`;
}
function groupPage() {
  const cat = S.groupCatalog.length;
  const gtypes = ((typeof OOT_TEST_TYPES !== 'undefined' && OOT_TEST_TYPES.length > 1) ? OOT_TEST_TYPES : GROUP_TYPES).filter(t => !t.includes('안정성'));
  return `<div style="padding:26px 30px 60px;max-width:1100px;width:100%">
    ${pageHeader('광동제약 · 품질·시험', 'APQR용 조회(참고용)', 'APQR · 풀링 OOT', 'APQR용 코드가 다른 동일 제품을 합쳐(pooling) 관리도·OOT를 봅니다 <span style="color:#dc2626;font-weight:800;font-size:15.5px">(GMP활용 금지)</span>')}
    ${stepGuide(['시험종류 선택', '유사품목 다중선택', '연도 선택', '전체 OOT·엑셀'], S.groupMembers.length ? ((S.groupResults.length || S.groupPooledLoading) ? 3 : 2) : 1)}
    <div style="display:flex;align-items:center;gap:8px;margin:-6px 0 16px;padding:11px 15px;background:#fff7ed;border:1px solid #fed7aa;border-radius:11px">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#c2660c" stroke-width="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path></svg>
      <span style="font-size:12px;color:#9a5700">풀링은 <b>규격·시험방법이 동일한 코드</b>에만 적용하세요(APQR 전제).</span></div>
    <div style="background:#fff;border:1px solid #dfe4ec;border-radius:16px;box-shadow:0 1px 3px rgba(20,30,50,.05);padding:20px 22px">
      <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-end">
        <div><div style="font-size:11.5px;font-weight:600;color:#5b6573;margin-bottom:6px">시험종류</div>
          <select data-act="groupTestType" style="padding:10px 32px 10px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:13.5px;font-weight:600;color:#27303f;background:#fff;appearance:none;cursor:pointer">${gtypes.map(t => `<option ${t === S.groupTestType ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
        <div style="flex:1 1 320px;min-width:240px;position:relative">
          <div style="font-size:11.5px;font-weight:600;color:#5b6573;margin-bottom:6px">동일품목 검색 ${cat ? `<span style="color:#9aa4b4;font-weight:500">(${cat}개)</span>` : '<span style="color:#9aa4b4;font-weight:500">로딩…</span>'}</div>
          <input id="group-search" value="${esc(S.groupQuery)}" placeholder="품목명 입력 (예: 베니톨정)" autocomplete="off" style="width:100%;padding:11px 13px;border:1px solid #d7dce4;border-radius:10px;font-size:14px;color:#27303f;outline:none;background:#fff">
          <div id="group-dropdown">${groupDropdown()}</div></div>
        <div><div style="font-size:11.5px;font-weight:600;color:#5b6573;margin-bottom:6px">분석 가능 시험항목</div>
          <div style="padding:10px 14px;border:1px solid #eef1f5;border-radius:10px;background:#f8fafc;font-size:13px;font-weight:600;color:${S.groupItems.length ? '#27303f' : '#9aa4b4'};min-width:130px;text-align:center">${S.groupMembers.length ? (S.groupItems.length ? S.groupItems.length + '개 (전체 분석)' : '로딩…') : '품목 선택 후'}</div></div>
      </div>
      <div style="margin-top:14px;padding-top:14px;border-top:1px solid #eef1f5">
        <div style="font-size:11.5px;font-weight:600;color:#5b6573;margin-bottom:9px">선택 품목 (${S.groupMembers.length})</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${groupMemberChips()}</div>
      </div>
      ${S.groupMembers.length ? `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px">
        <span style="font-size:11.5px;font-weight:600;color:#5b6573">연도</span>
        <div style="display:flex;gap:3px;background:#eef1f6;border:1px solid #e2e7ef;border-radius:9px;padding:3px">${['전체', ...(S.groupYears || [])].map(y => { const sel = S.groupYear === y; const b = `font-family:${MONO};font-size:12px;font-weight:600;padding:5px 11px;border-radius:7px;cursor:pointer;border:none`; return `<button data-act="grpYear" data-year="${esc(y)}" style="${b};${sel ? 'background:#fff;color:#27303f;box-shadow:0 1px 2px rgba(20,30,50,.12)' : 'background:transparent;color:#7a8699'}">${esc(y)}</button>`; }).join('')}</div>
        <span style="font-size:11px;color:#9aa4b4">연도 선택 시 그 해 데이터만 풀링(재계산)</span>
      </div>` : ''}
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px">
        <input id="group-name" value="${esc(S.groupName)}" placeholder="그룹 이름(APQR 저장용)" style="width:220px;padding:9px 12px;border:1px solid #d7dce4;border-radius:10px;font-size:12.5px;outline:none">
        <button data-act="grpSave" style="padding:9px 15px;border:1px solid #c3cdda;border-radius:10px;background:#fff;color:#46536a;font-size:12.5px;font-weight:600;cursor:pointer">확정 그룹 저장</button>
        <button data-act="grpPool" style="display:flex;align-items:center;gap:7px;padding:9px 16px;border:none;border-radius:10px;background:#E5310F;color:#fff;font-size:12.5px;font-weight:600;cursor:pointer">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>OOT 분석</button>
        <span style="font-size:12px;font-weight:600;color:${(S.groupMsg.includes('실패') || S.groupMsg.includes('부족') || S.groupMsg.includes('선택')) ? '#dc2626' : '#15803d'}">${esc(S.groupMsg)}</span>
      </div>
    </div>
    ${(!S.groupMembers.length && !S.groupResults.length) ? startGuide('APQR 풀링을 시작하세요', [
      '<b>시험종류</b> 선택',
      '동일 제품을 <b>품목명으로 검색</b>해 <b>2개 이상</b> 선택 (규격·시험방법 동일 코드만)',
      '<b>연도</b> 선택 (기본 당해년도)',
      '<b>[OOT 분석]</b> → <b>전 시험항목</b> 관리도를 한눈에 · <b>엑셀 다운로드</b>',
    ]) : ''}
    ${groupResultsAll()}
    ${groupSavedList()}
  </div>`;
}
function plotGroupChart(el, p) {
  const pts = p.points || [];
  if (!pts.length || !p.std) { el.innerHTML = '<div style="padding:26px;text-align:center;color:#9aa4b4">표시할 데이터가 없습니다.</div>'; return; }
  const labels = pts.map(x => `${x.품목코드}·${x.LOT || ''}`), vals = pts.map(x => x.시험결과);
  const colors = vals.map(v => { const z = Math.abs((v - p.mean) / p.std); return z > 3 ? '#d03b3b' : z > 2 ? '#eda100' : '#2a78d6'; });
  const flat = y => labels.map(() => y);
  const lim = (y, c, d) => ({ x: labels, y: flat(y), mode: 'lines', line: { color: c, width: 1.4, dash: d }, hoverinfo: 'skip', showlegend: false, type: 'scatter' });
  const data = [
    lim(p.ucl_3s, '#7c6fdd', 'dot'), lim(p.lcl_3s, '#7c6fdd', 'dot'),
    lim(p.ucl_2s, '#eda100', 'dash'), lim(p.lcl_2s, '#eda100', 'dash'),
    lim(p.mean, '#888', 'solid'),
    {
      x: labels, y: vals, mode: 'markers', marker: { color: colors, size: 8, line: { color: '#fff', width: 1.2 } }, showlegend: false, type: 'scatter',
      hovertemplate: pts.map(x => { const z = ((x.시험결과 - p.mean) / p.std).toFixed(2); const s = x.oot_3s ? '관리이탈' : x.warn_2s ? '주의' : '정상'; return `${x.품목코드} · LOT ${x.LOT || ''}<br>결과 ${x.시험결과} (z=${z}, ${s})<extra></extra>`; }),
    },
  ];
  const layout = {
    height: 300, margin: { l: 50, r: 16, t: 8, b: 90 },
    xaxis: { title: '', type: 'category', tickangle: -50, tickfont: { size: 8 }, gridcolor: '#f5f6f9' },
    yaxis: { title: '', gridcolor: '#eef1f5', zeroline: false },
    plot_bgcolor: '#fff', paper_bgcolor: '#fff', font: { family: 'Pretendard Variable, sans-serif', size: 11 }, hovermode: 'closest',
  };
  window.Plotly.newPlot(el, data, layout, { displayModeBar: false, responsive: true });
}
function renderGroupCharts() {
  if (!window.Plotly) return;
  (S.groupResults || []).forEach((p, i) => {
    const el = document.getElementById('group-chart-' + i);
    if (el) plotGroupChart(el, p);
  });
}

/* ============================ RENDER + EVENTS ============================ */
function render() {
  const page = S.nav === 'oot' ? ootPage() : S.nav === 'stability' ? stabPage()
             : S.nav === 'group' ? groupPage() : S.nav === 'history' ? historyPage() : alarmPage();
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
        S.code = null; S.productName = ''; S.lot = null; S.lotSummary = null; S.years = ['전체']; S.yearFilter = '전체'; S.lotQuery = ''; S.ootComp = null;
        const pn = $('#oot-pname'); if (pn) { pn.textContent = '품목코드 선택 시 표시'; pn.style.color = '#b8c0cc'; }
        const cs = $('#oot-comp-section'); if (cs) cs.innerHTML = '';
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
    const lots = S.lotSummary.lots.filter(l => (!S.lotQuery || l.lot.toLowerCase().includes(S.lotQuery.toLowerCase())));
    const cnt = $('#lot-count'); if (cnt) cnt.textContent = `표시 ${lots.length} / 전체 ${S.lotSummary.lots.length}`;
  });
  ['specLow', 'specHigh'].forEach(k => { const el = document.querySelector(`[data-act="${k}"]`); if (el) el.addEventListener('change', e => { S[k] = e.target.value; loadStability(); }); });
  const apw = $('#alarm-pw');
  if (apw) { apw.focus(); apw.addEventListener('keydown', e => { if (e.key === 'Enter') unlockAlarm(); }); }
  const pwNew = $('#pw-new');
  if (pwNew) pwNew.addEventListener('keydown', e => { if (e.key === 'Enter') changePw(); });
  const dbSearch = $('#db-search');
  if (dbSearch) dbSearch.addEventListener('input', e => { S.dbSearch = e.target.value; updateDbList(); });
  const histQ = $('#hist-q');
  if (histQ) histQ.addEventListener('input', e => { S.histQ = e.target.value; S.histLimit = 200; updateHistPanel(); });
  const dbEmail = $('#db-email');
  if (dbEmail) dbEmail.addEventListener('keydown', e => { if (e.key === 'Enter') addDbRecip(); });
  const grpSearch = $('#group-search');
  if (grpSearch) {
    grpSearch.addEventListener('input', e => { S.groupQuery = e.target.value; S.groupOpen = true; const d = $('#group-dropdown'); if (d) d.innerHTML = groupDropdown(); });
    grpSearch.addEventListener('focus', () => { S.groupOpen = true; const d = $('#group-dropdown'); if (d) d.innerHTML = groupDropdown(); });
    grpSearch.addEventListener('blur', () => setTimeout(() => { S.groupOpen = false; const d = $('#group-dropdown'); if (d) d.innerHTML = ''; }, 160));
  }
  const grpName = $('#group-name');
  if (grpName) grpName.addEventListener('input', e => { S.groupName = e.target.value; });
  renderStabChart();   // Plotly 인터랙티브 차트(가능 시 SVG 대체)
  renderOotCompChart();   // OOT 성분별 LOT 관리도
  renderGroupCharts();   // 동일품목군 전 시험항목 풀링 관리도
  loadOotStab();   // 안정성 시험종류일 때 시점별 데이터 로드
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
  else if (act === 'nav') { S.nav = el.dataset.nav; if (S.nav === 'alarm') S.alarmAuthed = false; render(); if (S.nav === 'stability') ensureStability(); if (S.nav === 'group') ensureGroup(); if (S.nav === 'alarm') loadAlarm(); if (S.nav === 'history') ensureHistory(); }
  else if (act === 'alarmUnlock') { unlockAlarm(); }
  else if (act === 'alarmLock') { S.alarmAuthed = false; render(); }
  else if (act === 'alarmTest') { testSend(); }
  else if (act === 'histTab') { S.histTab = el.dataset.tab; S.histLimit = 200; updateHistPanel(); }
  else if (act === 'histKind') { S.histKind = el.dataset.kind; S.histLimit = 200; updateHistPanel(); }
  else if (act === 'histJump') { S.histTab = el.dataset.tab; if (el.dataset.kind) S.histKind = el.dataset.kind; S.histLimit = 200; updateHistPanel(); }
  else if (act === 'histToggle') { const k = el.dataset.key; if (S.histOpen[k]) delete S.histOpen[k]; else S.histOpen[k] = true; updateHistPanel(); }
  else if (act === 'histMore') { S.histLimit += 200; updateHistPanel(); }
  else if (act === 'histRefresh') { loadAlarmHistory(); }
  else if (act === 'histCsv') { histCsv(); }
  else if (act === 'changePw') { changePw(); }
  else if (act === 'refresh') { refreshData(); }
  else if (act === 'pickYear') { S.yearFilter = el.dataset.year; loadLots(); }
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
  else if (act === 'schedMode') { if ((S.alarm.schedule || {}).mode === el.dataset.mode) return; S.alarm.schedule = { ...(S.alarm.schedule || {}), mode: el.dataset.mode }; S.alarmDirty = true; render(); }
  else if (act === 'toggleNight') { S.alarm.night = !S.alarm.night; S.alarmDirty = true; render(); }
  else if (act === 'addRecip') { const i = $('#recip-input'); const v = i ? i.value.trim() : ''; if (v) { if (!S.alarm.recipients.includes(v)) S.alarm.recipients.push(v); S.alarmDirty = true; render(); } }
  else if (act === 'rmRecip') { S.alarm.recipients = S.alarm.recipients.filter(m => m !== el.dataset.mail); S.alarmDirty = true; render(); }
  else if (act === 'saveAlarm') { saveAlarm(); }
  else if (act === 'addDbRecip') { addDbRecip(); }
  else if (act === 'rmDbRecip') { rmDbRecip(el.dataset.email); }
  else if (act === 'selectTT') { S.activeTT = el.dataset.tt; render(); }
  else if (act === 'toggleMember') { toggleMember(el.dataset.email); }
  else if (act === 'saveGroups') { saveGroups(); }
  else if (act === 'grpAdd') { grpAddMember(el.dataset.code, el.dataset.name); }
  else if (act === 'grpRemove') { grpRemoveMember(el.dataset.code); }
  else if (act === 'grpSave') { grpSave(); }
  else if (act === 'grpPool') { grpAnalyzeAll(); }
  else if (act === 'grpPick') { grpPickSaved(el.dataset.gid); }
  else if (act === 'grpDel') { grpDelSaved(el.dataset.gid); }
  else if (act === 'grpYear') { S.groupYear = el.dataset.year; if (S.groupResults.length) grpAnalyzeAll(); else render(); }
});

document.addEventListener('change', e => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  if (el.dataset.act === 'ootComp') { S.ootComp = el.value || null; render(); }
  else if (el.dataset.act === 'histDays') { S.histDays = parseInt(el.value, 10) || 0; S.histLimit = 200; S.histOpen = {}; loadAlarmHistory(); }
  else if (el.dataset.act === 'histTT') { S.histTT = el.value; S.histLimit = 200; S.histOpen = {}; updateHistPanel(); }
  else if (el.dataset.act === 'schedTime') { S.alarm.schedule = { ...(S.alarm.schedule || {}), daily_time: el.value || '07:30' }; S.alarmDirty = true; render(); }
  else if (el.dataset.act === 'schedInterval') { const v = parseInt(el.value, 10); S.alarm.schedule = { ...(S.alarm.schedule || {}), interval_min: (v >= 1 && v <= 1440) ? v : 10 }; S.alarmDirty = true; render(); }
  else if (el.dataset.act === 'ootTestType') { S.ootTestType = el.value; S.code = null; S.productName = ''; S.lot = null; S.lotSummary = null; S.query = ''; S.ootComp = null; loadOotProducts(); }
  else if (el.dataset.act === 'stabTestType') { S.stabTestType = el.value; S.stabCode = null; S.stabData = null; S.stabBatch = null; S.stabFromOot = false; loadStabProducts(); }
  else if (el.dataset.act === 'stabProduct') { S.stabCode = el.value; S.stabTestItem = null; S.stabFromOot = false; S.stabBatch = null; loadStability(); }
  else if (el.dataset.act === 'testItem') { S.stabTestItem = el.value; loadStability(); }
  else if (el.dataset.act === 'groupTestType') { S.groupTestType = el.value; S.groupMembers = []; S.groupItems = []; S.groupYear = String(new Date().getFullYear()); S.groupYears = []; S.groupResults = []; loadGroupCatalog(true); }
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
async function refreshData() {
  try { await postJSON('/api/refresh', {}); } catch (e) {}   // 서버 캐시 무효화 후 새로고침
  location.reload();
}
async function loadOotProducts() {
  S.ootProdLoading = true; render();
  try { const d = await getJSON(`/api/oot/products?test_type=${encodeURIComponent(S.ootTestType)}`); S.ootProducts = d.products; OOT_TEST_TYPES = d.testTypes; }
  catch (e) { S.ootProducts = []; }
  S.ootProdLoading = false; render();
}
async function loadLots() {
  if (!S.code) { render(); return; }
  S.lotsLoading = true; render();
  const yq = (S.yearFilter && S.yearFilter !== '전체') ? `&year=${encodeURIComponent(S.yearFilter)}` : '';
  try { S.lotSummary = await getJSON(`/api/oot/lots?code=${encodeURIComponent(S.code)}&test_type=${encodeURIComponent(S.ootTestType)}${yq}`); S.years = S.lotSummary.years; }
  catch (e) { S.lotSummary = { lots: [], years: ['전체'] }; S.years = ['전체']; }
  S.lotsLoading = false; render();
}
async function pickProduct(code, name) {
  S.code = code; S.productName = name; S.query = `${code}  ${name}`; S.open = false; S.lot = null; S.lotQuery = ''; S.ootComp = null;
  S.yearFilter = '전체';                    // 기본 = 전체(전 이력 기준)
  render();
  await loadLots();                        // year=전체
  // 기본 선택 = 가장 최근 업데이트된 제조번호(로트는 내림차순 정렬 → 첫 항목)
  const ls = (S.lotSummary && S.lotSummary.lots) || [];
  if (ls.length) { S.lot = ls[0].lot; render(); }
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
  try {
    const g = await getJSON('/api/recipients/groups');
    S.groups = g.groups || {}; S.recipTestTypes = g.testTypes || []; S.recipDb = g.recipients || [];
    if ((!S.activeTT || !S.recipTestTypes.includes(S.activeTT)) && S.recipTestTypes.length) S.activeTT = S.recipTestTypes[0];
  } catch (e) {}
  S.alarmDirty = false; S.recipDirty = false;
  render();
}
async function addDbRecip() {
  const n = $('#db-name'), e = $('#db-email'); if (!e) return;
  const name = n ? n.value.trim() : '', email = e.value.trim();
  const m = $('#db-msg');
  try {
    const r = await postJSON('/api/recipients', { name, email });
    if (r.ok) { S.recipDb = r.recipients || S.recipDb; render(); }
    else if (m) { m.textContent = r.msg || '추가 실패'; m.style.color = '#dc2626'; }
  } catch (err) { if (m) { m.textContent = '추가 실패: ' + err.message; m.style.color = '#dc2626'; } }
}
async function rmDbRecip(email) {
  try {
    const r = await postJSON('/api/recipients/delete', { email });
    S.recipDb = r.recipients || S.recipDb;
    const em = String(email).toLowerCase();
    for (const tt of Object.keys(S.groups)) S.groups[tt] = (S.groups[tt] || []).filter(x => String(x).toLowerCase() !== em);
    render();
  } catch (e) {}
}
function toggleMember(email) {
  const tt = S.activeTT; if (!tt) return;
  const list = (S.groups[tt] || []).slice();
  const em = String(email).toLowerCase();
  const i = list.findIndex(x => String(x).toLowerCase() === em);
  if (i >= 0) list.splice(i, 1); else list.push(email);
  S.groups[tt] = list; S.recipDirty = true; render();
}
async function saveGroups() {
  try {
    const r = await postJSON('/api/recipients/groups', { groups: S.groups });
    S.groups = r.groups || S.groups; S.recipDirty = false; render();
    const s = $('#grp-status'); if (s) { s.textContent = '✓ 저장됨'; s.style.color = '#15803d'; }
  } catch (e) {
    const s = $('#grp-status'); if (s) { s.textContent = '저장 실패: ' + e.message; s.style.color = '#dc2626'; }
  }
}
async function saveAlarm() {
  try {
    const r = await postJSON('/api/alarm/config', S.alarm);
    if (r && r.detail) throw new Error(typeof r.detail === 'string' ? r.detail : '입력값을 확인하세요');
    if (r && r.schedule) { S.alarm.schedule = r.schedule; S.alarm.interval = r.interval; }
    S.alarmDirty = false; render();
    const s = $('#alarm-status'); if (s) { s.textContent = '✓ 저장되었습니다 (알람에 1분 이내 반영)'; s.style.color = '#15803d'; }
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
