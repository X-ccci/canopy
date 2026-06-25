/**
 * Canopy Dashboard — 环境检测与 API 桥接层
 *
 * 自动检测运行环境：
 *   - pywebview（桌面端）：通过 window.pywebview.api 调用 Python 后端
 *   - 浏览器（网页端）：通过 fetch('/api/*') 调用 FastAPI 服务器
 *
 * WebSocket：连接 /ws 获取实时 ticker/kline 推送
 */

// ═══ 环境检测 ═══
const IS_PYWEBVIEW = !!(window.pywebview && window.pywebview.api);
const IS_BROWSER = !IS_PYWEBVIEW;
console.log('[Canopy] 环境:', IS_PYWEBVIEW ? 'pywebview (桌面)' : '浏览器');

// ═══ API 桥接 ═══
const CanopyAPI = {
  /**
   * 统一 API 调用：pywebview 走 bridgeCall，浏览器走 fetch。
   * @param {string} method - API 方法名
   * @param {object} params - 参数对象
   * @returns {Promise<any>}
   */
  async call(method, params = {}) {
    if (IS_PYWEBVIEW) {
      // 桌面端：通过 pywebview JS API bridge
      try {
        const api = window.pywebview.api;
        // bridgeCall 支持三种模式：无参、对象参数、原始参数
        if (Object.keys(params).length === 0) {
          return await api[method]();
        }
        return await api[method](params);
      } catch (err) {
        console.error(`[API] bridgeCall ${method} failed:`, err);
        return null;
      }
    }

    // 网页端：通过 fetch 调用 FastAPI
    try {
      let url;
      let fetchOptions = { method: 'GET', headers: { 'Accept': 'application/json' } };

      switch (method) {
        case 'get_kpi':          url = '/api/kpi'; break;
        case 'get_strategies':   url = '/api/strategies'; break;
        case 'get_portfolio':    url = '/api/portfolio'; break;
        case 'get_orders':       url = `/api/orders?limit=${params.limit || 50}`; break;
        case 'get_risk_status':  url = '/api/risk'; break;
        case 'get_ws_status':    url = '/api/ws-status'; break;
        case 'get_ticker':       url = `/api/ticker?symbol=${encodeURIComponent(params.symbol || 'BTC/USDT')}`; break;
        case 'get_status':       url = '/api/status'; break;
        case 'get_sentiment':    url = '/api/sentiment'; break;
        case 'connect_exchange': url = '/api/status'; break;  // status 含连接信息
        case 'start_strategies': url = '/api/strategies'; break;
        case 'stop_strategies':  url = '/api/strategies'; break;
        default:
          console.warn(`[API] 未知方法 ${method}，尝试 /api/status`);
          url = '/api/status';
      }

      const resp = await fetch(url, fetchOptions);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      console.error(`[API] fetch ${method} failed:`, err);
      return null;
    }
  },

  // 便捷方法
  async getKpi()           { return this.call('get_kpi'); },
  async getStrategies()    { return this.call('get_strategies'); },
  async getPortfolio()     { return this.call('get_portfolio'); },
  async getOrders(limit)   { return this.call('get_orders', { limit: limit || 50 }); },
  async getRisk()          { return this.call('get_risk_status'); },
  async getWsStatus()      { return this.call('get_ws_status'); },
  async getTicker(symbol)  { return this.call('get_ticker', { symbol: symbol || 'BTC/USDT' }); },
  async getStatus()        { return this.call('get_status'); },
  async getSentiment()     { return this.call('get_sentiment'); },
};

// ═══ WebSocket 连接（仅浏览器环境） ═══
let wsConnection = null;

function connectWebSocket() {
  if (!IS_BROWSER) return;  // pywebview 不需要浏览器 WS

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/ws`;

  try {
    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
      console.log('[WS] 已连接', wsUrl);
      updateWsIndicator('connected');
    };

    wsConnection.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWsMessage(data);
      } catch (e) {
        console.error('[WS] 消息解析失败:', e);
      }
    };

    wsConnection.onerror = (err) => {
      console.error('[WS] 连接错误:', err);
      updateWsIndicator('error');
    };

    wsConnection.onclose = () => {
      console.log('[WS] 已断开，5s 后重连...');
      updateWsIndicator('disconnected');
      setTimeout(connectWebSocket, 5000);
    };
  } catch (e) {
    console.error('[WS] 创建连接失败:', e);
  }
}

function handleWsMessage(data) {
  // 更新 ticker 显示
  if (data.ticker) {
    Object.entries(data.ticker).forEach(([symbol, ticker]) => {
      updateTickerDisplay(symbol, ticker);
    });
  }
  // 更新 WS 状态
  if (data.ws_status) {
    updateWsStatusDisplay(data.ws_status);
  }
}

function updateWsIndicator(status) {
  const el = document.getElementById('ws-indicator');
  if (!el) return;
  el.className = 'ws-indicator ' + status;
  el.title = 'WebSocket: ' + status;
}

function updateTickerDisplay(symbol, ticker) {
  // 可由各页面按需覆写
}

function updateWsStatusDisplay(status) {
  // 可由各页面按需覆写
}

// 页面加载后自动连接
document.addEventListener('DOMContentLoaded', () => {
  if (IS_BROWSER) {
    connectWebSocket();
  }
});

// ═══ 定期轮询（浏览器环境 fallback） ═══
let pollInterval = null;

function startPolling(intervalMs = 3000) {
  if (!IS_BROWSER) return;
  stopPolling();
  pollInterval = setInterval(async () => {
    const kpi = await CanopyAPI.getKpi();
    if (kpi) updateKpiDisplay(kpi);
  }, intervalMs);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

function updateKpiDisplay(kpi) {
  // 更新 KPI 数值
  const pods = document.querySelectorAll('.kpi-pod .kpi-value');
  if (pods.length >= 4 && kpi) {
    if (kpi.total_value !== undefined) pods[0].textContent = '$' + Number(kpi.total_value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (kpi.pnl_24h !== undefined) pods[1].textContent = '$' + Number(kpi.pnl_24h).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (kpi.active_strategies !== undefined) pods[2].textContent = kpi.active_strategies;
    if (kpi.win_rate !== undefined) pods[3].textContent = kpi.win_rate.toFixed(1) + '%';
  }
}

// 页面加载后开始轮询
document.addEventListener('DOMContentLoaded', () => {
  if (IS_BROWSER) {
    startPolling(3000);
  }
});

// ═══ 页面可见性切换时暂停/恢复轮询 ═══
document.addEventListener('visibilitychange', () => {
  if (!IS_BROWSER) return;
  if (document.hidden) {
    stopPolling();
    if (wsConnection) wsConnection.close();
  } else {
    startPolling(3000);
    connectWebSocket();
  }
});

// ===== FIREFLY =====
(function(){
  const c=document.getElementById('fireflyCanvas'),ctx=c.getContext('2d');
  let W,H,P=[];
  function rsz(){W=c.width=innerWidth;H=c.height=innerHeight}
  rsz();addEventListener('resize',rsz);
  class F{
    constructor(){this.reset();this.y=Math.random()*H}
    reset(){
      this.x=Math.random()*W;this.y=-20;
      this.s=Math.random()*2+0.8;
      this.sY=Math.random()*0.25+.1;
      this.sX=(Math.random()-.5)*.35;
      this.o=0;this.tO=Math.random()*.4+.18;
      this.pS=Math.random()*.012+.006;this.pO=Math.random()*6.28;
      this.gs=this.s*7;
    }
    get hueList(){return (document.body.dataset.theme==='emerald'?'168,190,40,170':document.body.dataset.theme==='amber'?'40,35,168,190':document.body.dataset.theme==='amethyst'?'270,190,40,310':'350,190,330,168').split(',').map(Number)}
    get hue(){return this._h||(this._h=this.hueList[Math.floor(Math.random()*4)])}
    upd(){
      this.y+=this.sY;this.x+=this.sX+Math.sin(Date.now()*.001+this.pO)*.15;
      const p=Math.sin(Date.now()*this.pS+this.pO);
      this.o+=(this.tO*(.6+.4*p)-this.o)*.03;
      if(this.y>H+30||this.x<-30||this.x>W+30){this._h=null;this.reset()}
    }
    draw(ctx){
      const g=ctx.createRadialGradient(this.x,this.y,0,this.x,this.y,this.gs);
      g.addColorStop(0,`hsla(${this.hue},65%,55%,${this.o})`);
      g.addColorStop(.35,`hsla(${this.hue},55%,40%,${this.o*.35})`);
      g.addColorStop(1,`hsla(${this.hue},45%,30%,0)`);
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(this.x,this.y,this.gs,0,6.28);ctx.fill();
      ctx.fillStyle=`hsla(${this.hue},75%,70%,${this.o*1.1})`;
      ctx.beginPath();ctx.arc(this.x,this.y,this.s*.7,0,6.28);ctx.fill();
    }
  }
  for(let i=0;i<45;i++)P.push(new F());
  (function anim(){ctx.clearRect(0,0,W,H);P.forEach(p=>{p.upd();p.draw(ctx)});requestAnimationFrame(anim)})();
})();

// ===== SETTINGS PANEL =====
const body=document.body;
const overlay=document.getElementById('settingsOverlay');
const panel=document.getElementById('settingsPanel');

// Open/close
document.getElementById('settingsBtn').addEventListener('click',()=>{overlay.classList.add('open');panel.classList.add('open')});
document.getElementById('settingsClose').addEventListener('click',closeSettings);
overlay.addEventListener('click',closeSettings);
function closeSettings(){overlay.classList.remove('open');panel.classList.remove('open')}

// Mode toggle
document.querySelectorAll('.mode-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.mode-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    body.dataset.mode=btn.dataset.mode;
    savePrefs();
  });
});

// Theme cards
document.querySelectorAll('.theme-card').forEach(card=>{
  card.addEventListener('click',()=>{
    document.querySelectorAll('.theme-card').forEach(c=>c.classList.remove('active'));
    card.classList.add('active');
    body.dataset.theme=card.dataset.theme;
    savePrefs();
  });
});

// Animation options
document.querySelectorAll('.anim-option').forEach(opt=>{
  opt.addEventListener('click',()=>{
    document.querySelectorAll('.anim-option').forEach(o=>o.classList.remove('active'));
    opt.classList.add('active');
    body.dataset.animation=opt.dataset.animation;
    savePrefs();
  });
});

// Skeleton toggle
const skToggle=document.getElementById('skeletonToggle');
skToggle.addEventListener('click',()=>{
  skToggle.classList.toggle('active');
  body.dataset.skeleton=skToggle.classList.contains('active')?'true':'false';
  if(body.dataset.skeleton==='false'){
    // Re-trigger bar heights
    setTimeout(()=>{
      document.querySelectorAll('.chart-bars .bar-item').forEach((b,i)=>{
        const h=b.style.height;b.style.height='0%';
        setTimeout(()=>{b.style.height=h},100+i*60);
      });
    },100);
  }
  savePrefs();
});

// Persistence
function savePrefs(){
  localStorage.setItem('nt-theme',body.dataset.theme);
  localStorage.setItem('nt-mode',body.dataset.mode);
  localStorage.setItem('nt-animation',body.dataset.animation);
  localStorage.setItem('nt-skeleton',body.dataset.skeleton);
}
function loadPrefs(){
  const t=localStorage.getItem('nt-theme')||'emerald';
  const m=localStorage.getItem('nt-mode')||'dark';
  const a=localStorage.getItem('nt-animation')||'spring';
  const s=localStorage.getItem('nt-skeleton')||'false';
  body.dataset.theme=t;body.dataset.mode=m;body.dataset.animation=a;body.dataset.skeleton=s;
  // Update UI
  document.querySelectorAll('.theme-card').forEach(c=>c.classList.toggle('active',c.dataset.theme===t));
  document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode===m));
  document.querySelectorAll('.anim-option').forEach(o=>o.classList.toggle('active',o.dataset.animation===a));
  skToggle.classList.toggle('active',s==='true');
}
loadPrefs();

// ===== THEME QUICK TOGGLE =====
document.getElementById('themeToggleBtn').addEventListener('click',()=>{
  body.dataset.mode = body.dataset.mode === 'dark' ? 'light' : 'dark';
  document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode===body.dataset.mode));
  savePrefs();
});

// Nav links
document.querySelectorAll('.nav-link').forEach(l=>{
  l.addEventListener('click',function(){
    // 回测/订单标签有自己的切换逻辑，这里只处理其他标签切回主视图
    if (this.id !== 'nav-backtest' && this.id !== 'nav-orders') {
      document.querySelectorAll('.nav-link').forEach(x=>x.classList.remove('active'));
      this.classList.add('active');
      // 隐藏回测面板和订单面板，恢复主视图
      const bp = document.getElementById('backtest-panel');
      if (bp) bp.style.display = 'none';
      const op = document.getElementById('orders-panel');
      if (op) op.style.display = 'none';
      const mg = document.querySelector('.main-grid');
      if (mg) mg.querySelectorAll(':scope > :not(#backtest-panel):not(#orders-panel)').forEach(el => el.style.display = '');
    }
  });
});

// Bar entrance
setTimeout(()=>{
  if(body.dataset.skeleton==='false'){
    document.querySelectorAll('.chart-bars .bar-item').forEach((b,i)=>{
      const h=b.style.height;b.style.height='0%';
      setTimeout(()=>{b.style.height=h},100+i*60);
    });
  }
},300);

// ===== COUNT-UP KPI ANIMATION =====
function countUp(el, targetNum, prefix, suffix, decimals, duration) {
  const start = performance.now();
  const initialText = el.textContent;
  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = targetNum * eased;
    el.textContent = prefix + current.toFixed(decimals) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = prefix + targetNum.toFixed(decimals) + suffix;
  }
  requestAnimationFrame(tick);
}

setTimeout(()=>{
  if(body.dataset.skeleton==='false'){
    const pods = document.querySelectorAll('.kpi-pod .kpi-value');
    if(pods.length>=4){
      countUp(pods[0], 184632.50, '$', '', 2, 1400);
      countUp(pods[1], 4218.00, '$', '', 2, 1200);
      countUp(pods[2], 7, '', '', 0, 800);
      countUp(pods[3], 68.4, '', '%', 1, 1000);
    }
  }
},400);

// Keyboard shortcut: Esc to close settings
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeSettings()});