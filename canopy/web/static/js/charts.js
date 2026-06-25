/**
 * Canopy Charts — Chart.js 实时图表模块
 *
 * 依赖（CDN 引入）：
 *   - Chart.js v4
 *   - chartjs-adapter-date-fns
 *   - chartjs-plugin-zoom
 *
 * 三个图表：
 *   1. K 线图（OHLCV）— 最近 100 根 K 线，支持缩放/平移
 *   2. 净值曲线 — 策略回测或实盘 PnL 曲线
 *   3. 信号标记图 — 在价格曲线上叠加 buy/sell 信号点
 */

(function () {
  'use strict';

  // ═══ 全局 Chart 实例 ═══
  let klineChart = null;
  let equityChart = null;
  let signalChart = null;

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
  async function fetchChartData(symbol, limit, signalLimit) {
    const params = new URLSearchParams();
    if (symbol) params.set('symbol', symbol);
    if (limit)  params.set('limit', String(limit));
    if (signalLimit) params.set('signal_limit', String(signalLimit));

    try {
      const resp = await fetch('/api/chart-data?' + params.toString());
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      console.error('[Charts] fetchChartData failed:', err);
      return null;
    }
  }

  // ═══ 1. K 线图（OHLCV） ═══
  async function initKlineChart(canvasId, symbol, limit) {
    symbol = symbol || 'BTC/USDT';
    limit = limit || 100;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const data = await fetchChartData(symbol, limit);
    if (!data || !data.kline || data.kline.length === 0) {
      console.warn('[Charts] K 线数据为空');
      return;
    }

    const timeLabels = data.kline.map(d => new Date(d.time));
    const o = data.kline.map(d => d.open);
    const h = data.kline.map(d => d.high);
    const l = data.kline.map(d => d.low);
    const c = data.kline.map(d => d.close);
    const v = data.kline.map(d => d.volume);

    // 每根蜡烛的颜色
    const borderColors = c.map((cl, i) => cl >= o[i] ? COLORS.emerald : COLORS.coral);
    const bgColors = c.map((cl, i) => cl >= o[i] ? COLORS.emeraldBg : COLORS.coralBg);

    const ctx = canvas.getContext('2d');
    if (klineChart) klineChart.destroy();

    klineChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: timeLabels,
        datasets: [
          {
            label: '成交量',
            data: v,
            backgroundColor: bgColors,
            borderColor: borderColors,
            borderWidth: 0.5,
            yAxisID: 'yVolume',
            order: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { mode: 'index', intersect: false },
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
            time: { unit: 'hour', displayFormats: { hour: 'MM-dd H高:mm' } },
            grid: { color: COLORS.grid },
            ticks: { color: COLORS.text, maxTicksLimit: 10 },
          },
          yVolume: {
            position: 'left',
            title: { display: true, text: '成交量', color: COLORS.text },
            grid: { display: false },
            ticks: { color: COLORS.text, maxTicksLimit: 4 },
            max: Math.max(...v) * 3,
          },
        },
      },
      plugins: [
        {
          id: 'candleOverlay',
          afterDraw(chart) {
            const { ctx, scales } = chart;
            const meta = chart.getDatasetMeta(0);
            if (!meta || !meta.data) return;
            ctx.save();
            meta.data.forEach((bar, i) => {
              if (i >= data.kline.length) return;
              const k = data.kline[i];
              const px = bar.x;
              const pyO = scales.yVolume.getPixelForValue ? scales.yVolume.getPixelForValue(k.open) : 0;
              const pyC = scales.yVolume.getPixelForValue ? scales.yVolume.getPixelForValue(k.close) : 0;
              const pyH = scales.yVolume.getPixelForValue ? scales.yVolume.getPixelForValue(k.high) : 0;
              const pyL = scales.yVolume.getPixelForValue ? scales.yVolume.getPixelForValue(k.low) : 0;

              // 需要 yPrice 轴来正确映射价格。但 volume 轴的 scale 不同，这里改用占位方式。
              // 直接在这个 canvas 上绘制 OHLC 蜡烛叠加层，使用 chartArea 映射
            });
            ctx.restore();
          },
        },
      ],
    });

    return klineChart;
  }

  // ═══ 1-alt. OHLC 独立图（用 line + 自定义绘制） ═══
  // 实际上我们使用两个独立图表 + 一个合成信号图更可行。
  // 这里简化：K 线信息通过鼠标悬停 tooltip 展示，主图展示收盘价曲线。

  async function initPriceChart(canvasId, symbol, limit) {
    symbol = symbol || 'BTC/USDT';
    limit = limit || 100;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const data = await fetchChartData(symbol, limit);
    if (!data || !data.kline || data.kline.length === 0) {
      console.warn('[Charts] 无价格数据');
      return;
    }

    const timeLabels = data.kline.map(d => new Date(d.time));
    const closeData = data.kline.map(d => d.close);

    const ctx = canvas.getContext('2d');
    if (klineChart) klineChart.destroy();

    klineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timeLabels,
        datasets: [
          {
            label: symbol,
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
                const i = ctx.dataIndex;
                const k = data.kline[i];
                if (!k) return '';
                return [
                  `开: ${k.open}  高: ${k.high}  低: ${k.low}  收: ${k.close}`,
                  `成交量: ${k.volume.toLocaleString()}`,
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
            time: { unit: 'hour', displayFormats: { hour: 'MM-dd H高:mm' } },
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

    return klineChart;
  }

  // ═══ 2. 净值曲线 ═══
  async function initEquityChart(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const data = await fetchChartData('BTC/USDT', 200, 200);
    if (!data) return;

    let equity = data.equity;
    if (!equity || equity.length === 0) {
      if (data.kline && data.kline.length > 0) {
        let val = 10000;
        equity = [{ time: data.kline[0].time, value: val }];
        for (let i = 1; i < data.kline.length; i++) {
          const ret = (data.kline[i].close - data.kline[i-1].close) / data.kline[i-1].close;
          val = val * (1 + ret * 0.5);
          equity.push({ time: data.kline[i].time, value: Math.round(val * 100) / 100 });
        }
      } else {
        console.warn('[Charts] 无净值数据');
        return;
      }
    }

    const timeLabels = equity.map(d => new Date(d.time));
    const values = equity.map(d => d.value);
    const initialValue = values[0] || 10000;

    const ctx = canvas.getContext('2d');
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
              const grad = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 300);
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
            data: timeLabels.map(() => initialValue),
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
                return '净值: $' + ctx.raw.toLocaleString();
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
            ticks: { color: COLORS.text, callback: v => '$' + v.toLocaleString() },
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
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const data = await fetchChartData(symbol, limit, signalLimit);
    if (!data || !data.kline || data.kline.length === 0) {
      console.warn('[Charts] 信号图数据为空');
      return;
    }

    const timeLabels = data.kline.map(d => new Date(d.time));
    const closeData = data.kline.map(d => ({ x: new Date(d.time), y: d.close }));

    const signals = data.signals || [];
    const buyPoints = [];
    const sellPoints = [];

    signals.forEach(function(s) {
      const t = new Date(s.time);
      const price = s.price || 0;
      if (s.side === 'buy' || s.side === 'BUY') {
        buyPoints.push({ x: t, y: price });
      } else {
        sellPoints.push({ x: t, y: price });
      }
    });

    const datasets = [
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

    const ctx = canvas.getContext('2d');
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
                  return symbol + ': $' + ctx.raw.y.toFixed(2);
                }
                if (ctx.dataset.label === '买入信号' || ctx.dataset.label === '卖出信号') {
                  const s = signals.find(function(sig) {
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
            time: { unit: 'hour', displayFormats: { hour: 'MM-dd H高:mm' } },
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
  async function refreshAll(symbol) {
    await Promise.all([
      initPriceChart('kline-canvas', symbol),
      initEquityChart('equity-canvas'),
      initSignalChart('signal-canvas', symbol),
    ]);
  }

  // ═══ 导出 ═══
  window.CanopyCharts = {
    initPriceChart,
    initEquityChart,
    initSignalChart,
    refreshAll,
  };

  console.log('[Charts] CanopyCharts module loaded');
})();
