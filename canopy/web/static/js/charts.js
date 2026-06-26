/**
 * Canopy Charts — Chart.js 实时图表模块（含多周期 K 线）
 *
 * 依赖（CDN 引入）：
 *   - Chart.js v4
 *   - chartjs-adapter-date-fns
 *   - chartjs-plugin-zoom
 *
 * 三个主图表 + K 线周期切换按钮：
 *   1. K 线图（OHLCV）— 支持 1m/5m/15m/1h/4h/1d 周期切换
 *   2. 净值曲线 — 策略回测或实盘 PnL 曲线
 *   3. 信号标记图 — 在价格曲线上叠加 buy/sell 信号点
 */

(function () {
  'use strict';

  // ═══ 全局 Chart 实例 ═══
  let klineChart = null;
  let equityChart = null;
  let signalChart = null;
  let currentKlineSymbol = 'BTC/USDT';
  let currentKlineInterval = '1h';

  // ═══ Nature-Tech Glass 配色 ═══
  const COLORS = {
    emerald:   'rgba(80, 200, 120, 1)',
    emeraldBg: 'rgba(80, 200, 120, 0.08)',
    coral:     'rgba(244, 114, 114, 1)',
    coralBg:   'rgba(244, 114, 114, 0.08)',
    amber:     'rgba(251, 191, 36, 1)',
    amethyst:  'rgba(167, 139, 250, 1)',
    cyan:      'rgba(34, 211, 238, 1)',
    grid:      'rgba(255, 255, 255, 0.05)',
    text:      'rgba(255, 255, 255, 0.6)',
  };

  // ═══ 数据获取 ═══
  async function fetchChartData(symbol, limit, signalLimit, interval) {
    var params = new URLSearchParams();
    if (symbol) params.set('symbol', symbol);
    if (limit)  params.set('limit', String(limit));
    if (signalLimit) params.set('signal_limit', String(signalLimit));
    if (interval) params.set('interval', interval);

    try {
      var resp = await fetch('/api/chart-data?' + params.toString());
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return await resp.json();
    } catch (err) {
      console.error('[Charts] fetchChartData failed:', err);
      return null;
    }
  }

  // ═══ 时间单位映射 ═══
  function getTimeUnit(interval) {
    return { '1m': 'minute', '5m': 'minute', '15m': 'minute', '1h': 'hour', '4h': 'hour', '1d': 'day' }[interval] || 'hour';
  }

  function getDisplayFormat(interval) {
    return {
      '1m': 'HH:mm', '5m': 'HH:mm', '15m': 'HH:mm',
      '1h': 'MM-dd HH:mm', '4h': 'MM-dd HH:mm', '1d': 'MM-dd'
    }[interval] || 'MM-dd HH:mm';
  }

  // ═══ 周期切换按钮渲染 ═══
  function renderIntervalButtons(containerId, onSelect) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var intervals = ['1m', '5m', '15m', '1h', '4h', '1d'];
    var html = '';
    intervals.forEach(function(ival) {
      var cls = (ival === currentKlineInterval) ? 'interval-btn active' : 'interval-btn';
      html += '<button class="' + cls + '" data-interval="' + ival + '">' + ival + '</button>';
    });
    container.innerHTML = html;
    container.style.display = 'flex';
    container.style.gap = '6px';
    container.style.marginBottom = '10px';
    container.style.flexWrap = 'wrap';

    container.querySelectorAll('.interval-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        currentKlineInterval = this.dataset.interval;
        container.querySelectorAll('.interval-btn').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        if (onSelect) onSelect(currentKlineInterval);
      });
    });
  }

  // ═══ 1. K 线图（OHLCV）— 支持 interval 参数 ═══
  async function initPriceChart(canvasId, symbol, limit, interval) {
    symbol = symbol || currentKlineSymbol;
    limit = limit || 100;
    interval = interval || currentKlineInterval;
    currentKlineSymbol = symbol;
    currentKlineInterval = interval;

    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    var data = await fetchChartData(symbol, limit, 0, interval);
    if (!data || !data.kline || data.kline.length === 0) {
      console.warn('[Charts] 无价格数据');
      return;
    }

    var timeLabels = data.kline.map(function(d) { return new Date(d.time); });
    var closeData = data.kline.map(function(d) { return d.close; });
    var timeUnit = getTimeUnit(interval);
    var displayFmt = getDisplayFormat(interval);

    var ctx = canvas.getContext('2d');
    if (klineChart) klineChart.destroy();

    klineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timeLabels,
        datasets: [
          {
            label: symbol + ' · ' + interval,
            data: closeData,
            borderColor: COLORS.emerald,
            backgroundColor: 'rgba(80, 200, 120, 0.08)',
            fill: true,
            tension: 0.1,
            pointRadius: 0,
            pointHoverRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var i = ctx.dataIndex;
                var k = data.kline[i];
                if (!k) return '';
                return [
                  '开: ' + k.open + '  高: ' + k.high + '  低: ' + k.low + '  收: ' + k.close,
                  '成交量: ' + (k.volume || 0).toLocaleString(),
                ];
              },
            },
          },
          zoom: {
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              drag: { enabled: true, backgroundColor: 'rgba(80,200,120,0.08)' },
              mode: 'x',
            },
            pan: { enabled: true, mode: 'x' },
          },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: timeUnit, displayFormats: {} },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text, maxTicksLimit: 10 },
          },
          y: {
            title: { display: true, text: '价格 (USDT)', color: COLORS.text },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text },
          },
        },
      },
    });

    // 动态设置 x 轴显示格式
    if (klineChart && klineChart.options && klineChart.options.scales && klineChart.options.scales.x) {
      klineChart.options.scales.x.time.displayFormats = {};
      klineChart.options.scales.x.time.displayFormats[timeUnit] = displayFmt;
      klineChart.update();
    }

    return klineChart;
  }

  // ═══ 2. 净值曲线 ═══
  async function initEquityChart(canvasId) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    var data = await fetchChartData('BTC/USDT', 200, 200);
    if (!data) return;

    var equity = data.equity;
    if (!equity || equity.length === 0) {
      if (data.kline && data.kline.length > 0) {
        var val = 10000;
        equity = [{ time: data.kline[0].time, value: val }];
        for (var i = 1; i < data.kline.length; i++) {
          var ret = (data.kline[i].close - data.kline[i-1].close) / data.kline[i-1].close;
          val = val * (1 + ret * 0.5);
          equity.push({ time: data.kline[i].time, value: Math.round(val * 100) / 100 });
        }
      } else {
        console.warn('[Charts] 无净值数据');
        return;
      }
    }

    var timeLabels = equity.map(function(d) { return new Date(d.time); });
    var values = equity.map(function(d) { return d.value; });
    var initialValue = values[0] || 10000;

    var ctx = canvas.getContext('2d');
    if (equityChart) equityChart.destroy();

    equityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timeLabels,
        datasets: [
          {
            label: '净值',
            data: values,
            borderColor: COLORS.emerald,
            backgroundColor: function(ctx) {
              var grad = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 300);
              grad.addColorStop(0, 'rgba(80, 200, 120, 0.25)');
              grad.addColorStop(1, 'rgba(80, 200, 120, 0.01)');
              return grad;
            },
            fill: true,
            tension: 0.25,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: COLORS.emerald,
          },
          {
            label: '初始资金',
            data: timeLabels.map(function() { return initialValue; }),
            borderColor: 'rgba(255,255,255,0.15)',
            borderWidth: 1,
            borderDash: [5, 5],
            fill: false,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, labels: { color: COLORS.text, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                if (ctx.dataset.label === '初始资金')
                  return '初始资金: $' + initialValue.toLocaleString();
                return '净值: $' + (ctx.raw || 0).toLocaleString();
              },
            },
          },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: 'day', displayFormats: { day: 'MM-dd' } },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text, maxTicksLimit: 10 },
          },
          y: {
            title: { display: true, text: '净值 (USDT)', color: COLORS.text },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text, callback: function(v) { return '$' + v.toLocaleString(); } },
          },
        },
      },
    });

    return equityChart;
  }

  // ═══ 3. 信号标记图 ═══
  async function initSignalChart(canvasId, symbol, limit, signalLimit) {
    symbol = symbol || 'BTC/USDT';
    limit = limit || 100;
    signalLimit = signalLimit || 50;
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    var data = await fetchChartData(symbol, limit, signalLimit);
    if (!data || !data.kline || data.kline.length === 0) {
      console.warn('[Charts] 信号图数据为空');
      return;
    }

    var timeLabels = data.kline.map(function(d) { return new Date(d.time); });
    var closeData = data.kline.map(function(d) { return { x: new Date(d.time), y: d.close }; });

    var signals = data.signals || [];
    var buyPoints = [];
    var sellPoints = [];

    signals.forEach(function(s) {
      var t = new Date(s.time);
      var price = s.price || 0;
      if (s.side === 'buy' || s.side === 'BUY') {
        buyPoints.push({ x: t, y: price });
      } else {
        sellPoints.push({ x: t, y: price });
      }
    });

    var datasets = [
      {
        label: symbol,
        data: closeData,
        borderColor: COLORS.cyan,
        borderWidth: 1,
        fill: false,
        tension: 0.1,
        pointRadius: 0,
        order: 3,
      },
    ];

    if (buyPoints.length > 0) {
      datasets.push({
        label: '买入信号',
        data: buyPoints,
        backgroundColor: COLORS.emerald,
        borderColor: COLORS.emerald,
        borderWidth: 1,
        pointStyle: 'triangle',
        pointRadius: 8,
        pointHoverRadius: 12,
        showLine: false,
        order: 1,
      });
    }

    if (sellPoints.length > 0) {
      datasets.push({
        label: '卖出信号',
        data: sellPoints,
        backgroundColor: COLORS.coral,
        borderColor: COLORS.coral,
        borderWidth: 1,
        pointStyle: 'triangle',
        rotation: 180,
        pointRadius: 8,
        pointHoverRadius: 12,
        showLine: false,
        order: 2,
      });
    }

    var ctx = canvas.getContext('2d');
    if (signalChart) signalChart.destroy();

    signalChart = new Chart(ctx, {
      type: 'line',
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: true, labels: { color: COLORS.text, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                if (ctx.dataset.label === symbol) {
                  return symbol + ': $' + (ctx.raw.y || 0).toFixed(2);
                }
                if (ctx.dataset.label === '买入信号' || ctx.dataset.label === '卖出信号') {
                  var s = signals.find(function(sig) {
                    return new Date(sig.time).getTime() === ctx.raw.x.getTime();
                  });
                  if (s) {
                    var lines = [s.side + ' @ $' + s.price, '策略: ' + (s.strategy || '无')];
                    if (s.reason) lines.push('原因: ' + s.reason);
                    return lines;
                  }
                  return ctx.dataset.label + ' @ $' + ctx.raw.y.toFixed(2);
                }
                return '';
              },
            },
          },
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: 'hour', displayFormats: { hour: 'MM-dd HH:mm' } },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text, maxTicksLimit: 10 },
          },
          y: {
            title: { display: true, text: '价格 (USDT)', color: COLORS.text },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text },
          },
        },
      },
    });

    return signalChart;
  }

  // ═══ 刷新所有图表 ═══
  async function refreshAll(symbol, interval) {
    interval = interval || currentKlineInterval;
    currentKlineSymbol = symbol || currentKlineSymbol;
    currentKlineInterval = interval;
    await Promise.all([
      initPriceChart('kline-canvas', currentKlineSymbol, 100, interval),
      initEquityChart('equity-canvas'),
      initSignalChart('signal-canvas', currentKlineSymbol),
    ]);
  }

  // ═══ 导出 ═══
  window.CanopyCharts = {
    initPriceChart: initPriceChart,
    initEquityChart: initEquityChart,
    initSignalChart: initSignalChart,
    refreshAll: refreshAll,
    renderIntervalButtons: renderIntervalButtons,
    currentKlineInterval: currentKlineInterval,
  };

  console.log('[Charts] CanopyCharts module loaded (multi-interval)');
})();
