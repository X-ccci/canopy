/**
 * Canopy i18n — 多语言切换（中/英/日）
 * LocalStorage 记忆语言偏好，所有 UI 文字通过 t('key') 函数化调用。
 */
(function () {
  'use strict';

  const LANG_KEY = 'canopy_lang';
  const SUPPORTED = ['zh', 'en', 'ja'];

  const translations = {
    zh: {
      'nav.dashboard': '仪表盘',
      'nav.trading': '交易',
      'nav.positions': '持仓',
      'nav.analysis': '分析',
      'nav.backtest': '回测',
      'nav.optimize': '优化',
      'nav.orders': '订单',
      'nav.marketplace': '市场',
      'nav.paper': '模拟盘',
      'nav.replay': '回放',
      'nav.community': '社区',
      'kpi.total_assets': '总资产',
      'kpi.pnl_24h': '24小时盈亏',
      'kpi.active_strategies': '活跃策略',
      'kpi.win_rate_30d': '胜率(30天)',
      'kpi.change_mtd': '本月',
      'kpi.profitable': '个盈利',
      'table.strategy': '策略',
      'table.pair': '交易对',
      'table.signal': '信号',
      'table.entry': '入场价',
      'table.current': '当前价',
      'table.pnl': '盈亏',
      'table.status': '状态',
      'table.running': '运行中',
      'table.holding': '持仓中',
      'table.stopped': '已止损',
      'chart.price': '价格图表 (OHLCV)',
      'chart.equity': '净值曲线',
      'chart.signals': '信号标记',
      'portfolio.title': '持仓分布',
      'portfolio.rebalanced': '已再平衡',
      'portfolio.total': '总计',
      'sentiment.title': 'Market Sentiment',
      'sentiment.fear_greed': 'Fear & Greed',
      'sentiment.fear': '恐惧',
      'sentiment.greed': '贪婪',
      'trade.quick': '快速交易',
      'trade.pair': '交易对',
      'trade.type': '类型',
      'trade.market': '市价',
      'trade.limit': '限价',
      'trade.amount': '金额 (USDT)',
      'trade.buy': '买入',
      'trade.sell': '卖出',
      'settings.title': '主题设置',
      'settings.mode': '模式',
      'settings.color': '配色方案',
      'settings.animation': '动画',
      'settings.skeleton': '骨架屏加载',
      'settings.dark': '暗色',
      'settings.light': '亮色',
      'order.id': '编号',
      'order.symbol': '交易对',
      'order.side': '方向',
      'order.type': '类型',
      'order.price': '价格',
      'order.qty': '数量',
      'order.filled': '已成交',
      'order.status': '状态',
      'btn.refresh': '刷新',
      'btn.run': '运行回测',
      'btn.compare': '对比全部',
      'btn.optimize': '启动优化',
      'btn.load_best': '加载最佳',
      'status.online': '在线',
      'status.offline': '离线',
    },
    en: {
      'nav.dashboard': 'Dashboard',
      'nav.trading': 'Trading',
      'nav.positions': 'Positions',
      'nav.analysis': 'Analysis',
      'nav.backtest': 'Backtest',
      'nav.optimize': 'Optimize',
      'nav.orders': 'Orders',
      'nav.marketplace': 'Marketplace',
      'nav.paper': 'Paper Trading',
      'nav.replay': 'Replay',
      'nav.community': 'Community',
      'kpi.total_assets': 'Total Assets',
      'kpi.pnl_24h': '24h PnL',
      'kpi.active_strategies': 'Active Strategies',
      'kpi.win_rate_30d': 'Win Rate (30d)',
      'kpi.change_mtd': 'MTD',
      'kpi.profitable': 'profitable',
      'table.strategy': 'Strategy',
      'table.pair': 'Pair',
      'table.signal': 'Signal',
      'table.entry': 'Entry',
      'table.current': 'Current',
      'table.pnl': 'PnL',
      'table.status': 'Status',
      'table.running': 'Running',
      'table.holding': 'Holding',
      'table.stopped': 'Stopped',
      'chart.price': 'Price Chart (OHLCV)',
      'chart.equity': 'Equity Curve',
      'chart.signals': 'Signal Marks',
      'portfolio.title': 'Portfolio',
      'portfolio.rebalanced': 'Rebalanced',
      'portfolio.total': 'Total',
      'sentiment.title': 'Market Sentiment',
      'sentiment.fear_greed': 'Fear & Greed',
      'sentiment.fear': 'Fear',
      'sentiment.greed': 'Greed',
      'trade.quick': 'Quick Trade',
      'trade.pair': 'Pair',
      'trade.type': 'Type',
      'trade.market': 'Market',
      'trade.limit': 'Limit',
      'trade.amount': 'Amount (USDT)',
      'trade.buy': 'Buy',
      'trade.sell': 'Sell',
      'settings.title': 'Theme Settings',
      'settings.mode': 'Mode',
      'settings.color': 'Color Theme',
      'settings.animation': 'Animation',
      'settings.skeleton': 'Skeleton Loading',
      'settings.dark': 'Dark',
      'settings.light': 'Light',
      'order.id': 'ID',
      'order.symbol': 'Symbol',
      'order.side': 'Side',
      'order.type': 'Type',
      'order.price': 'Price',
      'order.qty': 'Qty',
      'order.filled': 'Filled',
      'order.status': 'Status',
      'btn.refresh': 'Refresh',
      'btn.run': 'Run Backtest',
      'btn.compare': 'Compare All',
      'btn.optimize': 'Start Optimize',
      'btn.load_best': 'Load Best',
      'status.online': 'Online',
      'status.offline': 'Offline',
    },
    ja: {
      'nav.dashboard': 'ダッシュボード',
      'nav.trading': '取引',
      'nav.positions': 'ポジション',
      'nav.analysis': '分析',
      'nav.backtest': 'バックテスト',
      'nav.optimize': '最適化',
      'nav.orders': '注文',
      'nav.marketplace': 'マーケット',
      'nav.paper': 'ペーパー取引',
      'nav.replay': 'リプレイ',
      'nav.community': 'コミュニティ',
      'kpi.total_assets': '総資産',
      'kpi.pnl_24h': '24h損益',
      'kpi.active_strategies': '稼働戦略',
      'kpi.win_rate_30d': '勝率(30日)',
      'kpi.change_mtd': '月間',
      'kpi.profitable': '利益',
      'table.strategy': '戦略',
      'table.pair': 'ペア',
      'table.signal': 'シグナル',
      'table.entry': 'エントリー',
      'table.current': '現在値',
      'table.pnl': '損益',
      'table.status': '状態',
      'table.running': '稼働中',
      'table.holding': '保有中',
      'table.stopped': '停止',
      'chart.price': '価格チャート (OHLCV)',
      'chart.equity': '資産曲線',
      'chart.signals': 'シグナルマーク',
      'portfolio.title': 'ポートフォリオ',
      'portfolio.rebalanced': 'リバランス済',
      'portfolio.total': '合計',
      'sentiment.title': 'Market Sentiment',
      'sentiment.fear_greed': 'Fear & Greed',
      'sentiment.fear': '恐怖',
      'sentiment.greed': '強欲',
      'trade.quick': 'クイック取引',
      'trade.pair': 'ペア',
      'trade.type': 'タイプ',
      'trade.market': '成行',
      'trade.limit': '指値',
      'trade.amount': '金額 (USDT)',
      'trade.buy': '買い',
      'trade.sell': '売り',
      'settings.title': 'テーマ設定',
      'settings.mode': 'モード',
      'settings.color': 'カラーテーマ',
      'settings.animation': 'アニメーション',
      'settings.skeleton': 'スケルトン',
      'settings.dark': 'ダーク',
      'settings.light': 'ライト',
      'order.id': 'ID',
      'order.symbol': 'シンボル',
      'order.side': '方向',
      'order.type': 'タイプ',
      'order.price': '価格',
      'order.qty': '数量',
      'order.filled': '約定',
      'order.status': '状態',
      'btn.refresh': '更新',
      'btn.run': '実行',
      'btn.compare': '全比較',
      'btn.optimize': '最適化開始',
      'btn.load_best': '最適値読込',
      'status.online': 'オンライン',
      'status.offline': 'オフライン',
    },
  };

  let currentLang = localStorage.getItem(LANG_KEY) || 'zh';
  if (!SUPPORTED.includes(currentLang)) currentLang = 'zh';

  function getLang() {
    return currentLang;
  }

  function setLang(lang) {
    if (!SUPPORTED.includes(lang)) return;
    currentLang = lang;
    localStorage.setItem(LANG_KEY, lang);
    refreshAllUI();
    return lang;
  }

  function t(key, fallback) {
    const dict = translations[currentLang];
    if (dict && dict[key] !== undefined) return dict[key];
    // fallback to en
    if (translations.en && translations.en[key] !== undefined) return translations.en[key];
    return fallback || key;
  }

  /**
   * 刷新页面上所有 [data-i18n] 元素。
   */
  function refreshAllUI() {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      const key = el.getAttribute('data-i18n');
      if (key) {
        el.textContent = t(key);
      }
    });
    // 更新语言切换按钮
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-lang') === currentLang);
    });
  }

  // 暴露全局 API
  window.CanopyI18n = {
    t: t,
    getLang: getLang,
    setLang: setLang,
    refreshAllUI: refreshAllUI,
    SUPPORTED: SUPPORTED,
  };

  // 初始刷新
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshAllUI);
  } else {
    refreshAllUI();
  }
})();
