<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import ChartWorkspace from '$lib/components/chart/ChartWorkspace.svelte';
	import type { ChartDrawing, ChartDrawingPoint, ChartDrawingTool } from '$lib/components/chart/types';
	import {
		forceCloseForvenTrade,
		getForvenDashboard,
		getForvenOpenTrades,
		getForvenRecentTrades,
		getLiveIndicators,
		getLiveMarkers,
		getLiveSignals,
		getOHLCV,
		listLifecycleStrategies,
		type ForvenTrade,
		type ForvenDashboardResponse,
		type LifecycleStrategy,
		type OHLCVBar,
	} from '$lib/api';
	import { getPaperSession } from '$lib/api/paper';
	import type {
		IndicatorHistoryPoint,
		PaperTradingSession,
		PendingSignal,
		SessionIndicatorConfig,
	} from '$lib/api/paper';
	import type { IndicatorConfig, SignalMarker } from '$lib/stores/chartStore';
	import {
		buildChartIndicators,
		formatIndicatorValue,
		getIndicatorSidebarGroup,
		isChartRenderableIndicator,
	} from '$lib/components/chart/indicatorHelpers';
	import { createPoller, type Poller } from '$lib/utils/polling';
	import StrategyContainerDrawer from '$lib/components/lifecycle/StrategyContainerDrawer.svelte';
	import { simulationActive, simulationPrices } from '$lib/stores/simulation';
	import { getSimTrades } from '$lib/api/simulation';
	import TradeHistoryTable from './TradeHistoryTable.svelte';
	import DeployedContainersList from './DeployedContainersList.svelte';
	import TradingGatesStrip from './TradingGatesStrip.svelte';

	/** Loader data from +page.ts — provides initial trades payload. */
	export let data: {
		openTrades: ForvenTrade[];
		recentTrades: ForvenTrade[];
		dashboard: ForvenDashboardResponse | null;
		deployedStrategies: LifecycleStrategy[];
	};

	// Drawer state
	let showStrategyDrawer = false;
	let drawerStrategyId = '';
	let drawerDisplayId = '';
	let drawerStrategyName = '';
	let drawerStage = 'deployed';
	let drawerMetrics = {};
	let drawerMarketPot: string | null = null;

	function openStrategyDetail() {
		if (activeDeployedStrategy) {
			drawerStrategyId = activeDeployedStrategy.id;
			drawerDisplayId = deployedDisplayLabel(activeDeployedStrategy);
			drawerStrategyName = activeDeployedStrategy.name;
			drawerStage = activeDeployedStrategy.state || 'deployed';
			drawerMetrics = activeDeployedStrategy.metrics || {};
			showStrategyDrawer = true;
		} else if (activeTrade && activeTrade.strategy_id) {
			drawerStrategyId = activeTrade.strategy_id;
			drawerDisplayId = activeTrade.strategy || activeTrade.strategy_id;
			drawerStrategyName = activeTrade.strategy || '';
			drawerStage = 'deployed'; // Open trades are by definition deployed
			// No co-located container row for this open trade; the drawer self-loads audit/metrics.
			drawerMetrics = {};
			showStrategyDrawer = true;
		}
	}

	// Seed from loader data so the page renders without a spinner flash.
	let loading = data.openTrades.length === 0 && data.recentTrades.length === 0;
	let refreshing = false;
	let errorMessage = '';
	let partialWarning = '';
	let lastUpdated = '';
	let closingTradeId = '';
	let selectedTradeId = '';
	let forceCloseError = '';
	let forceCloseNotice = '';
	let poller: Poller | null = null;

	let openTrades: ForvenTrade[] = data.openTrades.filter((trade) => !isPaperTrade(trade));
	let simTrades: ForvenTrade[] = [];
	let closedTrades: ForvenTrade[] = data.recentTrades
		.filter((trade) => String(trade.status || '').toUpperCase() === 'CLOSED' && !isPaperTrade(trade))
		.sort((left, right) => {
			const leftTs = Date.parse(String(left.closed_at || left.opened_at || '')) || 0;
			const rightTs = Date.parse(String(right.closed_at || right.opened_at || '')) || 0;
				return rightTs - leftTs;
			});
	let deployedStrategies: LifecycleStrategy[] = data.deployedStrategies.filter((s) => isDeployedState(s.state));
	let dashboard: ForvenDashboardResponse | null = data.dashboard;
	let livePrices: Record<string, number> = (() => {
		if (!data.dashboard?.prices) return {};
		const next: Record<string, number> = {};
		for (const [asset, value] of Object.entries(data.dashboard.prices as Record<string, unknown>)) {
			const parsed = typeof value === 'number' ? value : Number(value);
			if (Number.isFinite(parsed)) next[asset] = parsed;
		}
		return next;
	})();
	let selectedDeployedStrategyId = '';

	// Chart state
	let chartBars: OHLCVBar[] = [];
	let loadingChart = false;
	let chartAsset = '';
	let chartTimeframe = '1h';
	let entryMarkers: SignalMarker[] = [];
	let exitMarkers: SignalMarker[] = [];
	let preferredChartTimeframe = '';
	let activeDrawingTool: ChartDrawingTool = 'cursor';
	let chartDrawings: ChartDrawing[] = [];
	let pendingTrendLineStart: ChartDrawingPoint | null = null;
	let fitContentToken = 0;
	let lastActiveChartSymbol = '';

	// Indicator overlays + approaching-signals (mirrors PaperTrades), fed by the
	// live-position indicator/signal endpoints.
	let mainIndicators: IndicatorConfig[] = [];
	let subIndicators: IndicatorConfig[] = [];
	let indicatorConfig: Record<string, SessionIndicatorConfig> = {};
	let indicatorHistory: Record<string, IndicatorHistoryPoint[]> = {};
	let indicatorVisibility: Record<string, boolean> = {};
	let pendingSignals: PendingSignal[] = [];
	let liveSignalIndicators: Record<string, { name: string; value: number; timestamp: string }> = {};
	// Compat session for the active strategy — drives the ribbon so it matches the
	// paper-trading ribbon exactly (capital, win/PF/avg/expectancy, trade mode).
	let liveSession: PaperTradingSession | null = null;
	let liveBlockedCount = 0;
	let showIndicatorPanel = false;
	let showDetailsPanel = false;
	let lastIndicatorKey = '';
	let loadingIndicators = false;

	const chartTimeframeOptions = ['5m', '15m', '30m', '1h', '2h', '4h', '1d'];
	const indicatorGroups = ['overlays', 'lower', 'sidebar'] as const;

	function toNumber(value: unknown): number | null {
		if (value === null || value === undefined || value === '') return null;
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}

	function normalizePercent(value: number | null): number | null {
		if (value === null) return null;
		return Math.abs(value) <= 1 ? value * 100 : value;
	}

	function formatPrice(value: number | null): string {
		if (value === null) return '--';
		if (value >= 1000) return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
		if (value >= 1) return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
		return value.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 8 });
	}

	function formatSize(value: number | null): string {
		if (value === null) return '--';
		return value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 6 });
	}

	function formatUsd(value: number | null): string {
		if (value === null) return '--';
		const prefix = value >= 0 ? '+' : '-';
		return `${prefix}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	}

	function formatPct(value: number | null): string {
		if (value === null) return '--';
		const prefix = value >= 0 ? '+' : '';
		return `${prefix}${value.toFixed(2)}%`;
	}

	function formatRatio(value: number | null | undefined): string {
		if (value === null || value === undefined || !Number.isFinite(value)) return '--';
		return value.toFixed(2);
	}

	function humanizeLabel(value: string | null | undefined): string {
		const raw = String(value || '').trim();
		if (!raw) return '--';
		return raw
			.split(/[_\s]+/)
			.map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
			.join(' ');
	}

	function formatTs(value: string | null | undefined): string {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '--';
		return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
	}

	function directionLabel(direction: string | null | undefined): 'LONG' | 'SHORT' {
		return String(direction || '').toLowerCase() === 'short' ? 'SHORT' : 'LONG';
	}

	function directionClass(direction: string | null | undefined): string {
		return directionLabel(direction) === 'LONG'
			? 'text-green-300 border-green-800'
			: 'text-red-300 border-red-800';
	}

	function pnlClass(value: number | null): string {
		if (value === null) return 'text-gray-500';
		return value >= 0 ? 'text-green-400' : 'text-red-400';
	}

	function tradeRowKey(trade: ForvenTrade, index: number): string {
		return String(trade.id ?? `${trade.strategy ?? 'trade'}-${index}`);
	}

	type TradeBadge = {
		label: string;
		className: string;
	};

	function asRecord(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
		return value as Record<string, unknown>;
	}

	function tradeSignalDataRecord(trade: ForvenTrade): Record<string, unknown> {
		return asRecord(trade.signal_data) ?? {};
	}

	function isExchangeBackedTrade(trade: ForvenTrade | null | undefined): boolean {
		if (!trade) return false;
		const signalData = tradeSignalDataRecord(trade);
		const source = String(trade.source ?? '').trim().toLowerCase();
		const exchangeSource = String(signalData.source ?? '').trim().toLowerCase();
		return source === 'exchange' || exchangeSource === 'exchange_sync';
	}

	function tradeMarkPrice(trade: ForvenTrade | null | undefined): number | null {
		if (!trade) return null;
		const signalData = tradeSignalDataRecord(trade);
		const exchangeMark = toNumber(signalData.mark_price);
		if (exchangeMark !== null) return exchangeMark;
		return resolveMarketPrice(trade.asset);
	}

	// A recovered/adopted position still NEEDS the "Recovered" callout only until
	// it is healthy: attributed to a real strategy (not the 'exchange_recovered'
	// placeholder) AND its protective stop is in place. After that it's a normal
	// managed live position. Backend `source` intentionally stays 'exchange_recovered'.
	function isUnfinishedRecovery(trade: ForvenTrade): boolean {
		const signalData = tradeSignalDataRecord(trade);
		const source = String(trade.source ?? '').trim().toLowerCase();
		const recovered = source === 'exchange_recovered' || Boolean(signalData.recovery_reason);
		if (!recovered) return false;
		const protectionStatus = String(signalData.recovery_protection_status ?? '').trim().toLowerCase();
		const strategyAttr = String(trade.strategy ?? '').trim().toLowerCase();
		const healthy = Boolean(strategyAttr) && strategyAttr !== 'exchange_recovered' && protectionStatus === 'protected';
		return !healthy;
	}

	function tradeBadges(trade: ForvenTrade): TradeBadge[] {
		const signalData = tradeSignalDataRecord(trade);
		const badges: TradeBadge[] = [];
		const source = String(trade.source ?? '').trim().toLowerCase();
		const exchangeSource = String(signalData.source ?? '').trim().toLowerCase();
		const protectionStatus = String(signalData.recovery_protection_status ?? '').trim().toLowerCase();

		// Only flag "Recovered" while the recovery is UNFINISHED. Once an adopted
		// position is attributed to a real strategy AND its protective stop is in
		// place it's just a normal managed live position — keeping the badge forever
		// (recovery_reason is never cleared) made rare recoveries look constant.
		// `source` stays 'exchange_recovered' for rollback/authoritative-PnL logic.
		if (isUnfinishedRecovery(trade)) {
			badges.push({
				label: 'Recovered',
				className: 'border-amber-700/60 bg-amber-950/40 text-amber-300',
			});
		}
		if (source === 'exchange' || exchangeSource === 'exchange_sync') {
			badges.push({
				label: 'Exchange-backed',
				className: 'border-cyan-700/60 bg-cyan-950/40 text-cyan-300',
			});
		}
		if (protectionStatus === 'missing') {
			badges.push({
				label: 'Needs protection',
				className: 'border-red-700/60 bg-red-950/40 text-red-300',
			});
		} else if (protectionStatus === 'partial') {
			badges.push({
				label: 'Partial protection',
				className: 'border-orange-700/60 bg-orange-950/40 text-orange-300',
			});
		}
		return badges;
	}

	function tradeSourceLabel(trade: ForvenTrade | null): string {
		if (!trade) return '--';
		const signalData = tradeSignalDataRecord(trade);
		const source = String(trade.source ?? '').trim().toLowerCase();
		const exchangeSource = String(signalData.source ?? '').trim().toLowerCase();
		if (isUnfinishedRecovery(trade)) {
			return 'Recovered Exchange Position';
		}
		if (source === 'exchange_recovered' || source === 'exchange' || exchangeSource === 'exchange_sync') {
			return 'Exchange-backed Position';
		}
		const network = hlNetworkLabel === 'mainnet' ? 'Mainnet' : 'Testnet';
		return tradeIdValue(trade) ? `Live Scanner (${network})` : 'Deployed Container';
	}

	function tradeIdValue(trade: ForvenTrade): string {
		return String(trade.id ?? '');
	}

	function normalizeStrategyKey(value: string | null | undefined): string {
		return String(value || '').trim().toLowerCase();
	}

	function deployedStrategyKey(strategy: LifecycleStrategy): string {
		return normalizeStrategyKey(strategy.id || strategy.name || '');
	}

	function isDeployedState(state: string | null | undefined): boolean {
		// Live strategies surface as 'live_graduated' (see normalizeLifecycleState),
		// not 'deployed*'. Match both so a live strategy with no open position still
		// renders in the Open Positions panel (and is counted).
		const key = normalizeStrategyKey(state);
		return key.startsWith('deploy') || key.startsWith('live');
	}

	function deployedDisplayLabel(strategy: LifecycleStrategy): string {
		const displayId = String(strategy.display_id || '').trim();
		const ref = String(strategy.source_ref || '').trim();
		const name = String(strategy.name || '').trim();
		const id = String(strategy.id || '').trim();
		return displayId || ref || name || id || '--';
	}

	function tradeStrategyLabel(trade: ForvenTrade): string {
		// The open-trades API can omit the `strategy` label (older backends only
		// selected strategy_id), which rendered every live position as '--'. Fall
		// back to the strategy name/id so the card shows the strat number instead.
		const t = trade as Record<string, unknown>;
		const pick = (v: unknown) => String(v ?? '').trim();
		return pick(t.strategy) || pick(t.strategy_name) || pick(t.strategy_id) || '--';
	}

	function normalizeTimeframe(value: string | null | undefined): string {
		const raw = String(value || '').trim().toLowerCase();
		return raw || '1h';
	}

	function buildDrawingId(prefix: string): string {
		return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
	}

	function timeframeButtonClass(timeframe: string): string {
		const base = 'rounded-sm border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors';
		return timeframe === activeChartTimeframe
			? `${base} border-emerald-700 bg-emerald-950/40 text-emerald-200`
			: `${base} border-[#232323] bg-[#080808] text-gray-400 hover:border-[#353535] hover:text-gray-200`;
	}

	function chartToolButtonClass(active = false): string {
		const base = 'rounded-sm border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-50';
		return active
			? `${base} border-amber-600 bg-amber-950/40 text-amber-200`
			: `${base} border-[#232323] bg-[#080808] text-gray-400 hover:border-[#353535] hover:text-gray-200`;
	}

	function asSyntheticTrade(strategy: LifecycleStrategy): ForvenTrade {
		const strategyLabel = deployedDisplayLabel(strategy);
		return {
			id: '',
			strategy: strategyLabel,
			asset: strategy.symbol || '--',
			direction: 'long',
			entry_price: undefined,
			exit_price: undefined,
			size: undefined,
			leverage: undefined,
			pnl_pct: undefined,
			pnl_usd: undefined,
			status: String(strategy.state || 'DEPLOYED').toUpperCase(),
			opened_at: strategy.updated_at || strategy.created_at || null,
			closed_at: null,
		};
	}

	function tradeMatchesDeployedStrategy(trade: ForvenTrade, strategy: LifecycleStrategy): boolean {
		const strategyIdKey = deployedStrategyKey(strategy);
		const strategyDisplayIdKey = normalizeStrategyKey(strategy.display_id);
		const strategyNameKey = normalizeStrategyKey(strategy.name);
		const tradeStrategyKey = normalizeStrategyKey(trade.strategy);
		const tradeStrategyIdKey = normalizeStrategyKey(String((trade as Record<string, unknown>).strategy_id ?? ''));
		return (
			tradeStrategyKey === strategyIdKey ||
			tradeStrategyKey === strategyDisplayIdKey ||
			tradeStrategyKey === strategyNameKey ||
			tradeStrategyIdKey === strategyIdKey ||
			tradeStrategyIdKey === strategyDisplayIdKey ||
			tradeStrategyIdKey === strategyNameKey
		);
	}

	function selectDeployedStrategy(strategy: LifecycleStrategy): void {
		selectedDeployedStrategyId = deployedStrategyKey(strategy);
		selectedTradeId = '';
		forceCloseError = '';
		forceCloseNotice = '';
	}

	function normalizeAssetKey(asset: string | null | undefined): string {
		return String(asset || '')
			.toUpperCase()
			.replace('/USDT', '')
			.replace('/USD', '')
			.trim();
	}

	function resolveMarketPrice(asset: string | null | undefined): number | null {
		const key = normalizeAssetKey(asset);
		if (!key) return null;
		// Use simulation prices when sim is active
		const priceSource = $simulationActive ? $simulationPrices : livePrices;
		const direct = toNumber(priceSource[key]);
		if (direct !== null) return direct;

		for (const [raw, value] of Object.entries(priceSource)) {
			const normalized = normalizeAssetKey(raw);
			if (normalized === key) {
				return toNumber(value);
			}
		}
		return null;
	}

	function currentPnlUsd(trade: ForvenTrade): number | null {
		if (isExchangeBackedTrade(trade)) {
			return toNumber(trade.pnl_usd);
		}
		const mark = tradeMarkPrice(trade);
		const entry = toNumber(trade.entry_price);
		const size = toNumber(trade.size);
		if (mark === null || entry === null || size === null) {
			return toNumber(trade.pnl_usd);
		}
		const signed = directionLabel(trade.direction) === 'LONG' ? 1 : -1;
		return (mark - entry) * size * signed;
	}

	function currentPnlPct(trade: ForvenTrade): number | null {
		if (isExchangeBackedTrade(trade)) {
			return normalizePercent(toNumber(trade.pnl_pct));
		}
		const mark = tradeMarkPrice(trade);
		const entry = toNumber(trade.entry_price);
		const leverage = toNumber(trade.leverage) ?? 1;
		if (mark === null || entry === null || entry <= 0) {
			return normalizePercent(toNumber(trade.pnl_pct));
		}
		const signed = directionLabel(trade.direction) === 'LONG' ? 1 : -1;
		return ((mark - entry) / entry) * signed * leverage * 100;
	}

	function selectedTrade(items: ForvenTrade[], selectedId: string): ForvenTrade | null {
		if (!selectedId) return items[0] ?? null;
		return items.find((trade) => tradeIdValue(trade) === selectedId) ?? items[0] ?? null;
	}

	function getStatusColor(status: string | null | undefined): string {
		switch (String(status || '').toLowerCase()) {
			case 'open':
			case 'deployed':
			case 'running':
				return 'text-green-400';
			case 'closed':
				return 'text-gray-400';
			default:
				return 'text-gray-500';
		}
	}

	// Resolve a symbol suitable for getOHLCV from a ForvenTrade asset field
	function resolveChartSymbol(asset: string | null | undefined): string {
		const raw = String(asset || '').toUpperCase().trim();
		if (!raw || raw === '--') return '';
		if (raw.includes('/')) return raw;
		return `${raw}/USDT`;
	}

	async function loadChart(trade: ForvenTrade, timeframe: string = '1h', force = false) {
		const symbol = resolveChartSymbol(trade.asset);
		if (!symbol) return;
		const tf = normalizeTimeframe(timeframe);
		const chartKey = `${symbol}:${tf}`;

		// Skip refetch when symbol+timeframe are unchanged. The reactive trigger
		// re-runs on every 12s poll tick (activeTrade is recomputed from fresh
		// arrays); without this guard we re-pull 500 bars on every tick/selection.
		if (!force && chartAsset === chartKey && chartBars.length > 0) {
			return;
		}

		// Only show skeleton on first load for this asset
		if (chartAsset !== chartKey) {
			loadingChart = true;
			chartBars = [];
		}
		chartAsset = chartKey;
		chartTimeframe = tf;

		try {
			const bars = await getOHLCV(symbol, tf, 500);
			chartBars = bars;

			// Direction drives the marker shape/label: long -> Buy/Sell,
			// short -> Short/Cover. Without it ChartWorkspace defaults to long
			// ("Buy"), which mislabels a short entry.
			const markerDirection = directionLabel(trade.direction) === 'SHORT' ? 'short' : 'long';

			// Build entry marker
			const entryPrice = toNumber(trade.entry_price);
			const openedAt = trade.opened_at;
			if (entryPrice !== null && openedAt) {
				entryMarkers = [{
					timestamp: new Date(openedAt).toISOString(),
					price: entryPrice,
					type: 'entry' as const,
					direction: markerDirection,
				}];
			} else {
				entryMarkers = [];
			}

			// Build exit marker for closed trades
			const exitPrice = toNumber(trade.exit_price);
			const closedAt = trade.closed_at;
			if (exitPrice !== null && closedAt) {
				exitMarkers = [{
					timestamp: new Date(closedAt).toISOString(),
					price: exitPrice,
					type: 'exit' as const,
					direction: markerDirection,
				}];
			} else {
				exitMarkers = [];
			}
		} catch (e) {
			console.error('Failed to load chart:', e);
		} finally {
			loadingChart = false;
		}
	}

	// Strategy id for the active position/container, used to key indicator/signal loads.
	function activeStrategyId(): string {
		if (activeDeployedStrategy) return String(activeDeployedStrategy.id || '').trim();
		if (activeOpenTrade && activeOpenTrade.strategy_id) return String(activeOpenTrade.strategy_id).trim();
		return '';
	}

	async function loadIndicatorsAndSignals(strategyId: string, timeframe: string): Promise<void> {
		const sid = String(strategyId || '').trim();
		if (!sid) {
			mainIndicators = [];
			subIndicators = [];
			indicatorConfig = {};
			indicatorHistory = {};
			pendingSignals = [];
			liveSignalIndicators = {};
			liveSession = null;
			liveBlockedCount = 0;
			return;
		}
		loadingIndicators = true;
		const [indicatorResult, signalResult, sessionResult, markerResult] = await Promise.allSettled([
			getLiveIndicators(sid, timeframe, 1000),
			getLiveSignals(sid),
			getPaperSession(sid),
			getLiveMarkers(sid),
		]);

		// Bail if selection moved on while we were fetching.
		if (activeStrategyId() !== sid) {
			loadingIndicators = false;
			return;
		}

		liveSession = sessionResult.status === 'fulfilled' ? sessionResult.value : null;
		liveBlockedCount = markerResult.status === 'fulfilled'
			? (markerResult.value.blocked?.length ?? 0)
			: 0;

		if (indicatorResult.status === 'fulfilled') {
			const data = indicatorResult.value;
			indicatorConfig = data.config;
			indicatorHistory = data.indicators;
			for (const name of Object.keys(data.indicators)) {
				if (!(name in indicatorVisibility)) indicatorVisibility[name] = true;
			}
			const built = buildChartIndicators(data, indicatorVisibility);
			mainIndicators = built.main;
			subIndicators = built.sub;
		} else {
			indicatorConfig = {};
			indicatorHistory = {};
			mainIndicators = [];
			subIndicators = [];
		}

		if (signalResult.status === 'fulfilled') {
			pendingSignals = signalResult.value.pending_signals ?? [];
			liveSignalIndicators = signalResult.value.indicators ?? {};
		} else {
			pendingSignals = [];
			liveSignalIndicators = {};
		}
		loadingIndicators = false;
	}

	function toggleIndicatorVisibility(name: string): void {
		if (!isChartRenderableIndicator(name, indicatorConfig[name])) return;
		indicatorVisibility[name] = !(indicatorVisibility[name] ?? true);
		indicatorVisibility = indicatorVisibility;
		mainIndicators = mainIndicators.map((ind) => ({
			...ind,
			visible: ind.name === name ? indicatorVisibility[name] : ind.visible,
		}));
		subIndicators = subIndicators.map((ind) => ({
			...ind,
			visible: ind.name === name ? indicatorVisibility[name] : ind.visible,
		}));
	}

	function getCurrentIndicatorValue(name: string): number | null {
		const live = liveSignalIndicators[name]?.value;
		if (typeof live === 'number' && Number.isFinite(live)) return live;
		const history = indicatorHistory[name];
		if (history && history.length > 0) {
			for (let idx = history.length - 1; idx >= 0; idx -= 1) {
				const value = history[idx]?.value;
				if (typeof value === 'number' && Number.isFinite(value)) return value;
			}
		}
		return null;
	}

	function indicatorNamesForGroup(group: 'overlays' | 'lower' | 'sidebar'): string[] {
		return Object.keys(indicatorConfig).filter(
			(name) => getIndicatorSidebarGroup(name, indicatorConfig[name]) === group
		);
	}

	async function refreshTrades(): Promise<void> {
		if (refreshing) return;
		refreshing = true;

		const results = await Promise.allSettled([
			getForvenOpenTrades(),
			getForvenRecentTrades(300),
			getForvenDashboard(),
			// Deployed/live strategies only — the unfiltered list is capped and the live
			// strategies fall outside it, so without this filter they never show.
			listLifecycleStrategies({ state: 'deployed', limit: 500 }),
		]);

		const [openResult, recentResult, dashboardResult, lifecycleResult] = results;
		const rejected = results.filter((item) => item.status === 'rejected');
		if (rejected.length > 0) {
			const first = rejected[0] as PromiseRejectedResult;
			partialWarning = first.reason instanceof Error ? first.reason.message : String(first.reason ?? 'Partial data unavailable');
		} else {
			partialWarning = '';
		}

		if (openResult.status === 'fulfilled') {
			openTrades = [...openResult.value].filter((trade) => !isPaperTrade(trade)).sort((left, right) => {
				const leftTs = Date.parse(String(left.opened_at || '')) || 0;
				const rightTs = Date.parse(String(right.opened_at || '')) || 0;
				return rightTs - leftTs;
			});

			const selected = selectedTrade(openTrades, selectedTradeId);
			selectedTradeId = selected ? tradeIdValue(selected) : '';
		}

		if (recentResult.status === 'fulfilled') {
			closedTrades = recentResult.value
				.filter((trade) => String(trade.status || '').toUpperCase() === 'CLOSED' && !isPaperTrade(trade))
				.sort((left, right) => {
					const leftTs = Date.parse(String(left.closed_at || left.opened_at || '')) || 0;
					const rightTs = Date.parse(String(right.closed_at || right.opened_at || '')) || 0;
					return rightTs - leftTs;
				});
		}

		if (dashboardResult.status === 'fulfilled') {
			dashboard = dashboardResult.value ?? null;
			const prices = dashboardResult.value?.prices as Record<string, unknown> | undefined;
			const next: Record<string, number> = {};
			for (const [asset, value] of Object.entries(prices ?? {})) {
				const parsed = toNumber(value);
				if (parsed !== null) next[asset] = parsed;
			}
			livePrices = next;
		}

		// Fetch simulation trades when sim is active
		if ($simulationActive) {
			try {
				simTrades = await getSimTrades();
			} catch {
				simTrades = [];
			}
		} else {
			simTrades = [];
		}

		if (lifecycleResult.status === 'fulfilled') {
			deployedStrategies = [...lifecycleResult.value]
				.filter((strategy) => isDeployedState(strategy.state))
				.sort((left, right) => {
					const leftTs = Date.parse(String(left.updated_at || left.created_at || '')) || 0;
					const rightTs = Date.parse(String(right.updated_at || right.created_at || '')) || 0;
					return rightTs - leftTs;
				});
		} else {
			deployedStrategies = [];
		}

		const deployedKeys = new Set(deployedStrategies.map((strategy) => deployedStrategyKey(strategy)));
		if (selectedDeployedStrategyId && !deployedKeys.has(selectedDeployedStrategyId)) {
			selectedDeployedStrategyId = '';
		}
		if (openTrades.length === 0 && !selectedDeployedStrategyId && deployedStrategies.length > 0) {
			selectedDeployedStrategyId = deployedStrategyKey(deployedStrategies[0]);
		}

		if (openResult.status === 'rejected' && recentResult.status === 'rejected') {
			errorMessage = openResult.reason instanceof Error
				? openResult.reason.message
				: String(openResult.reason ?? 'Failed to load trades');
		} else {
			errorMessage = '';
		}

		lastUpdated = new Date().toISOString();
		loading = false;
		refreshing = false;
	}

	async function handleForceClose(trade: ForvenTrade): Promise<void> {
		const tradeId = tradeIdValue(trade).trim();
		if (!tradeId) return;

		const venue = hlNetworkLabel === 'mainnet' ? 'HyperLiquid MAINNET (real funds)' : 'HyperLiquid testnet';
		const confirmed = typeof window === 'undefined'
			? true
			: window.confirm(`Force close trade ${tradeId}? This will send a reduce-only close order on ${venue}.`);
		if (!confirmed) return;

		closingTradeId = tradeId;
		errorMessage = '';
		forceCloseError = '';
		forceCloseNotice = '';
		try {
			const result = await forceCloseForvenTrade(tradeId, 'Manual force close from Live Trades page');
			// A successful close can still report a non-fatal cancel issue on
			// resting reduce-only orders — surface it inline rather than silently.
			if (result?.cancel_error) {
				forceCloseError = `Closed, but failed to cancel resting orders: ${result.cancel_error}`;
			} else {
				const cancelled = result?.cancelled_reduce_only_orders ?? 0;
				forceCloseNotice = cancelled > 0
					? `Close submitted. Cancelled ${cancelled} resting reduce-only order${cancelled === 1 ? '' : 's'}.`
					: 'Close submitted.';
			}
			await refreshTrades();
		} catch (err) {
			// Backend returns 502 with detail when the close fails — the position
			// may still be open on the exchange, so make this hard to miss.
			forceCloseError = err instanceof Error ? err.message : 'Failed to force close trade';
		} finally {
			closingTradeId = '';
		}
	}

	function selectOpenTrade(trade: ForvenTrade): void {
		selectedDeployedStrategyId = '';
		selectedTradeId = tradeIdValue(trade);
		forceCloseError = '';
		forceCloseNotice = '';
	}

	function setChartTimeframe(timeframe: string): void {
		preferredChartTimeframe = normalizeTimeframe(timeframe);
		fitContentToken += 1;
	}

	function toggleDrawingTool(tool: Exclude<ChartDrawingTool, 'cursor'>): void {
		if (activeDrawingTool === tool) {
			activeDrawingTool = 'cursor';
			pendingTrendLineStart = null;
			return;
		}
		activeDrawingTool = tool;
		pendingTrendLineStart = null;
	}

	function clearChartDrawings(): void {
		chartDrawings = [];
		pendingTrendLineStart = null;
		activeDrawingTool = 'cursor';
	}

	function handleChartDrawingPoint(event: CustomEvent<ChartDrawingPoint>): void {
		if (activeDrawingTool === 'cursor') return;
		const point = event.detail;
		if (activeDrawingTool === 'horizontalLine') {
			chartDrawings = [
				...chartDrawings,
				{
					id: buildDrawingId('hline'),
					type: 'horizontalLine',
					price: point.price,
					color: '#f59e0b',
					label: formatPrice(point.price),
				},
			];
			return;
		}

		if (!pendingTrendLineStart) {
			pendingTrendLineStart = point;
			return;
		}

		chartDrawings = [
			...chartDrawings,
			{
				id: buildDrawingId('trend'),
				type: 'trendLine',
				start: pendingTrendLineStart,
				end: point,
				color: '#38bdf8',
			},
		];
		pendingTrendLineStart = null;
	}

	function activeChartToolHint(): string {
		if (activeDrawingTool === 'horizontalLine') {
			return 'Horizontal line mode: click the chart to place a level.';
		}
		if (activeDrawingTool === 'trendLine') {
			return pendingTrendLineStart
				? 'Trend line mode: click a second point to finish the line.'
				: 'Trend line mode: click a first point to start the line.';
		}
		return 'Cursor mode: pan, zoom, and inspect candles without overlays covering the chart.';
	}

	function openDuration(openedAt: string | null | undefined): string {
		if (!openedAt) return '--';
		const opened = Date.parse(openedAt);
		if (!Number.isFinite(opened)) return '--';
		const elapsedMs = Date.now() - opened;
		if (elapsedMs <= 0) return '0m';
		const mins = Math.floor(elapsedMs / 60000);
		if (mins < 60) return `${mins}m`;
		const hours = Math.floor(mins / 60);
		const remMins = mins % 60;
		if (hours < 24) return `${hours}h ${remMins}m`;
		const days = Math.floor(hours / 24);
		const remHours = hours % 24;
		return `${days}d ${remHours}h`;
	}

	function isSimTrade(trade: ForvenTrade): boolean {
		return (trade as Record<string, unknown>).execution_type === 'simulation';
	}

	function isPaperTrade(trade: ForvenTrade): boolean {
		const execType = String((trade as Record<string, unknown>).execution_type || '').toLowerCase();
		return execType.includes('paper');
	}

	// Merge sim trades into the open trades list when simulation is active
	$: displayOpenTrades = $simulationActive
		? [...openTrades, ...simTrades.filter((t) => t.status?.toUpperCase() === 'OPEN')]
		: openTrades;
	$: displayClosedTrades = $simulationActive
		? [...closedTrades, ...simTrades.filter((t) => t.status?.toUpperCase() === 'CLOSED')]
		: closedTrades;

	$: openStrategyKeys = new Set(
		openTrades.flatMap((trade) => [
			normalizeStrategyKey(String((trade as Record<string, unknown>).strategy_id ?? '')),
			normalizeStrategyKey(String(trade.strategy ?? '')),
		]).filter(Boolean)
	);
	$: unpositionedDeployedStrategies = deployedStrategies.filter((strategy) => {
		const idKey = normalizeStrategyKey(strategy.id);
		const displayKey = normalizeStrategyKey(strategy.display_id);
		const nameKey = normalizeStrategyKey(strategy.name);
		return !openStrategyKeys.has(idKey) && !openStrategyKeys.has(displayKey) && !openStrategyKeys.has(nameKey);
	});
	$: activeOpenTrade = selectedDeployedStrategyId ? null : selectedTrade(openTrades, selectedTradeId);
	$: activeDeployedStrategy = selectedDeployedStrategyId
		? (unpositionedDeployedStrategies.find((strategy) => deployedStrategyKey(strategy) === selectedDeployedStrategyId) ?? null)
		: null;
	$: activeTrade = activeOpenTrade ?? (activeDeployedStrategy ? asSyntheticTrade(activeDeployedStrategy) : null);
	$: defaultChartTimeframe = activeDeployedStrategy ? normalizeTimeframe(activeDeployedStrategy.timeframe) : '1h';
	$: activeChartTimeframe = normalizeTimeframe(preferredChartTimeframe || defaultChartTimeframe);
	$: activeChartSymbol = activeTrade ? resolveChartSymbol(activeTrade.asset) : '';
	$: activeTradePnlUsd = activeTrade ? currentPnlUsd(activeTrade) : null;
	$: activeTradePnlPct = activeTrade ? currentPnlPct(activeTrade) : null;
	$: activeTradeMark = activeTrade ? tradeMarkPrice(activeTrade) : null;
	$: activeTradeNotional = activeTrade
		? (toNumber(activeTrade.entry_price) ?? 0) * (toNumber(activeTrade.size) ?? 0)
		: null;
	$: filteredClosedTrades = activeDeployedStrategy
		? displayClosedTrades.filter((trade) => tradeMatchesDeployedStrategy(trade, activeDeployedStrategy))
		: (activeTrade
			? displayClosedTrades.filter((trade) => trade.strategy === activeTrade.strategy)
			: displayClosedTrades);

	// Trading gates — runtime checks that can block new trades
	$: gates = (() => {
		const d = dashboard;
		return {
			system_paused: d?.paused ?? false,
			kill_switch: d?.risk?.kill_switch_active ?? false,
			daily_loss_halt: d?.risk?.daily_loss_halt ?? false,
			recovery_active: d?.recovery?.active ?? false,
			hl_price: d?.circuit_breakers?.hl_price ?? 'closed',
			hl_trade: d?.circuit_breakers?.hl_trade ?? 'closed',
			hl_account: d?.circuit_breakers?.hl_account ?? 'closed',
		};
	})();
	$: anyGateBlocking = gates.system_paused || gates.kill_switch || gates.daily_loss_halt || gates.recovery_active
		|| gates.hl_price !== 'closed' || gates.hl_trade !== 'closed' || gates.hl_account !== 'closed';

	// Which HyperLiquid network reduce-only orders actually hit. Prefer the
	// synced account network; fall back to inferring from execution mode.
	$: hlNetworkLabel = (() => {
		const raw = (dashboard?.account?.network || '').toString().trim().toLowerCase();
		if (raw === 'mainnet' || raw === 'testnet') return raw;
		const mode = (dashboard?.execution_mode || '').toString().trim().toLowerCase();
		if (mode === 'mainnet' || mode === 'live') return 'mainnet';
		return 'testnet';
	})();

	$: if (activeChartSymbol !== lastActiveChartSymbol) {
		if (lastActiveChartSymbol) {
			clearChartDrawings();
		}
		fitContentToken += 1;
		lastActiveChartSymbol = activeChartSymbol;
	}

	// Load chart when active trade changes
	$: if (activeTrade) {
		loadChart(activeTrade, activeChartTimeframe);
	}

	// Strategy id for the active position/container (reactive so the load below
	// re-runs when the selection or its strategy changes).
	$: currentStrategyId = activeDeployedStrategy
		? String(activeDeployedStrategy.id || '').trim()
		: activeOpenTrade?.strategy_id
			? String(activeOpenTrade.strategy_id).trim()
			: '';

	// Load indicator overlays + approaching-signals when the strategy or chart
	// timeframe changes (keyed so the 12s poll tick doesn't refetch every cycle).
	$: {
		const indicatorKey = `${currentStrategyId}:${activeChartTimeframe}`;
		if (indicatorKey !== lastIndicatorKey) {
			lastIndicatorKey = indicatorKey;
			loadIndicatorsAndSignals(currentStrategyId, activeChartTimeframe);
		}
	}

	// Ribbon values (mirror the paper ribbon): prefer the compat session, fall
	// back to the live position/trade fields.
	$: ribbonPrice = liveSession && (liveSession.current_price ?? 0) > 0
		? liveSession.current_price
		: activeTradeMark;
	$: ribbonLeverage = toNumber(liveSession?.leverage) ?? toNumber(activeTrade?.leverage) ?? 1;


	onMount(async () => {
		// Loader already provided initial data — skip first fetch if we have trades.
		if (loading) {
			await refreshTrades();
		}
		poller = createPoller(refreshTrades, 12_000);
		poller.start();
	});

	onDestroy(() => {
		poller?.stop();
	});
</script>

<svelte:head>
	<title>Live Trading | Forven</title>
	<meta name="description" content="Monitor and manage live HyperLiquid testnet scanner positions and closed trade history." />
</svelte:head>

<div class="workspace-layout flex-col">
	<!-- Header bar with page title + controls -->
	<div class="h-10 flex items-center border-b border-[#222] bg-[#0a0a0a] px-4 flex-shrink-0">
		<span class="text-xs font-bold uppercase tracking-wide text-white">Live Trading</span>
		<div class="ml-auto flex items-center gap-3">
			{#if errorMessage}
				<span class="text-red-500 text-xs">{errorMessage}</span>
				<button class="text-red-500 hover:text-red-300 text-xs" on:click={() => (errorMessage = '')}>dismiss</button>
			{/if}
			{#if partialWarning && !errorMessage}
				<span class="text-yellow-400 text-xs">partial: {partialWarning}</span>
			{/if}
			<span class="text-[10px] text-gray-500">Updated {formatTs(lastUpdated)}</span>
			<button class="terminal-button text-xs py-1" on:click={() => refreshTrades()} disabled={refreshing}>
				{refreshing ? 'Refreshing...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if $simulationActive}
		<div class="bg-blue-900/60 border-b border-blue-600 px-4 py-1.5 text-[11px] text-blue-200 flex items-center gap-2">
			<span class="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></span>
			Simulation mode active &mdash; showing virtual trades with simulated timestamps
		</div>
	{/if}
	{#if dashboard?.recovery?.active || dashboard?.recovery?.requires_operator}
		<div class="bg-amber-950/40 border-b border-amber-700/60 px-4 py-1.5 text-[11px] text-amber-200 flex items-start gap-2">
			<span class="mt-0.5 h-2 w-2 rounded-full bg-amber-400"></span>
			<div>
				<div class="font-bold uppercase tracking-wider text-amber-300">Recovery Blocking Entries</div>
				<div class="mt-0.5 text-amber-100/90">{dashboard?.recovery?.summary || 'Startup exchange recovery is active.'}</div>
			</div>
		</div>
	{/if}
	<div class="flex-1 flex overflow-hidden">
		<!-- Left: Open positions list -->
			<div class="w-72 border-r border-[#222] bg-[#050505] flex flex-col flex-shrink-0">
				<div class="panel-header">
					<span>Open Positions</span>
					<span class="text-[10px] text-gray-500 normal-case">{displayOpenTrades.length + unpositionedDeployedStrategies.length}</span>
				</div>
				<div class="flex-1 overflow-y-auto">
					{#if loading}
						<div class="p-3"><Skeleton rows={6} /></div>
					{:else if displayOpenTrades.length === 0}
						<div class="px-3 py-8 text-center">
							<p class="text-gray-500 text-xs">No live scanner positions</p>
							<p class="text-gray-600 text-xs mt-1">Waiting for next scanner entries</p>
						</div>
						<DeployedContainersList
							strategies={unpositionedDeployedStrategies}
							activeKey={activeDeployedStrategy ? deployedStrategyKey(activeDeployedStrategy) : ''}
							onSelect={selectDeployedStrategy}
						/>
					{:else}
						{#each displayOpenTrades as trade, index (tradeRowKey(trade, index))}
							{@const isActive = activeTrade && tradeIdValue(activeTrade) === tradeIdValue(trade)}
							{@const rowPnlUsd = currentPnlUsd(trade)}
							{@const badges = tradeBadges(trade)}
							<div
							class="terminal-list-item w-full text-left flex-col items-start gap-0 cursor-pointer {isActive ? 'active' : ''}"
							on:click={() => selectOpenTrade(trade)}
							on:keydown={(e) => e.key === 'Enter' && selectOpenTrade(trade)}
							role="button"
							tabindex="0"
						>
							<div class="flex justify-between items-center w-full gap-2">
								<span class="text-white text-xs font-bold truncate">
									{#if isSimTrade(trade)}<span class="text-[9px] bg-blue-600 text-white px-1 py-0.5 rounded mr-1 font-bold">SIM</span>{/if}
									{tradeStrategyLabel(trade)}
								</span>
								<div class="flex items-center gap-2">
									{#if trade.strategy_id}
										<button
											class="text-[9px] px-1 border border-gray-700 text-gray-500 hover:text-white hover:border-white rounded-sm transition-colors"
											on:click|stopPropagation={() => {
												selectedTradeId = tradeIdValue(trade);
												openStrategyDetail();
											}}
										>
											INFO
										</button>
									{/if}
									<span class="text-[10px] uppercase {getStatusColor(trade.status)} flex-shrink-0">{trade.status || 'OPEN'}</span>
								</div>
							</div>
							<div class="text-[10px] text-gray-500 w-full truncate">
								{trade.asset || '--'} | {directionLabel(trade.direction)} | {formatTs(trade.opened_at)}
							</div>
							{#if badges.length > 0}
								<div class="mt-1 flex w-full flex-wrap gap-1">
									{#each badges as badge}
										<span class={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${badge.className}`}>
											{badge.label}
										</span>
									{/each}
								</div>
							{/if}
							<div class="text-[10px] w-full flex justify-between">
								<span class="text-gray-600">@ ${formatPrice(toNumber(trade.entry_price))}</span>
								<span class={pnlClass(rowPnlUsd)}>{formatUsd(rowPnlUsd)}</span>
							</div>
							</div>
						{/each}
						<DeployedContainersList
							strategies={unpositionedDeployedStrategies}
							activeKey={activeDeployedStrategy ? deployedStrategyKey(activeDeployedStrategy) : ''}
							onSelect={selectDeployedStrategy}
						/>
					{/if}
				</div>
			</div>

		<!-- Right: Detail + Chart + History (mirrors Paper Trades layout) -->
		<div class="flex-1 bg-black overflow-hidden flex flex-col min-w-0">
			{#if activeTrade}
				<!-- Header bar -->
				<div class="border-b border-[#222] bg-[#0a0a0a] px-4 py-2 flex-shrink-0">
					<div class="flex justify-between items-center">
						<div class="flex items-center gap-3 min-w-0">
							<span class="text-sm font-bold text-white truncate">{tradeStrategyLabel(activeTrade)}</span>
							<span class="text-xs text-gray-500 flex-shrink-0">{activeTrade.asset || '--'}</span>
							<span class="inline-flex items-center px-1.5 py-0.5 border rounded text-[10px] font-bold tracking-wider {directionClass(activeTrade.direction)}">
								{directionLabel(activeTrade.direction)}
							</span>
							<span class="text-[10px] uppercase font-bold flex-shrink-0 {getStatusColor(activeTrade.status)}">
								{(activeTrade.status || 'OPEN').replaceAll('_', ' ')}
							</span>
						</div>
						<div class="flex gap-2 flex-shrink-0">
							<button
								type="button"
								class={chartToolButtonClass(showDetailsPanel)}
								on:click={() => (showDetailsPanel = !showDetailsPanel)}
							>
								Details
							</button>
							<button
								type="button"
								class="terminal-button text-xs py-0.5"
								on:click={openStrategyDetail}
								disabled={!activeTrade?.strategy_id && !activeDeployedStrategy?.id}
							>
								Open Detail
							</button>
							<button
								class="terminal-button-danger text-xs py-0.5"
								on:click={() => handleForceClose(activeTrade)}
								disabled={!tradeIdValue(activeTrade) || closingTradeId === tradeIdValue(activeTrade)}
							>
								{closingTradeId === tradeIdValue(activeTrade) ? 'Closing...' : 'Force Close'}
							</button>
						</div>
					</div>

					<!-- Inline force-close result (money-critical: a failed close may leave the position open on the exchange) -->
					{#if forceCloseError}
						<div class="mt-1.5 flex items-start gap-2 rounded-sm border border-red-700 bg-red-950/50 px-2 py-1.5 text-[11px] text-red-200">
							<span class="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-red-400"></span>
							<div class="min-w-0 flex-1">
								<span class="font-bold uppercase tracking-wider text-red-300">Force close failed</span>
								<span class="ml-1 break-words">{forceCloseError}</span>
								<span class="ml-1 text-red-300/80">Position may still be open on the exchange \u2014 verify before retrying.</span>
							</div>
							<button class="flex-shrink-0 text-red-400 hover:text-red-200" on:click={() => (forceCloseError = '')}>dismiss</button>
						</div>
					{:else if forceCloseNotice}
						<div class="mt-1.5 flex items-start gap-2 rounded-sm border border-emerald-800 bg-emerald-950/40 px-2 py-1.5 text-[11px] text-emerald-200">
							<span class="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-emerald-400"></span>
							<span class="min-w-0 flex-1">{forceCloseNotice}</span>
							<button class="flex-shrink-0 text-emerald-400 hover:text-emerald-200" on:click={() => (forceCloseNotice = '')}>dismiss</button>
						</div>
					{/if}

					<!-- Trading gates -->
					<div class="mt-1.5">
						<TradingGatesStrip {gates} {anyGateBlocking} />
					</div>

					<!-- KPI strip (mirrors the paper-trading ribbon) -->
					<div class="flex flex-wrap items-center gap-4 mt-2 text-xs">
						<span>
							<span class="text-gray-500">Price</span>
							<span class="text-white font-bold ml-1">{ribbonPrice !== null && ribbonPrice !== undefined ? `$${formatPrice(ribbonPrice)}` : '--'}</span>
						</span>
						<span>
							<span class="text-gray-500">Capital</span>
							<span class="text-white font-bold ml-1">{liveSession ? `$${formatPrice(toNumber(liveSession.capital))}` : '--'}</span>
						</span>
						<span>
							<span class="text-gray-500">P&L</span>
							<span class="font-bold ml-1 {pnlClass(toNumber(liveSession?.total_pnl))}">
								{formatUsd(toNumber(liveSession?.total_pnl))} ({formatPct(toNumber(liveSession?.total_pnl_pct))})
							</span>
						</span>
						<span>
							<span class="text-gray-500">Win</span>
							<span class="text-white font-bold ml-1">{formatPct(toNumber(liveSession?.performance?.win_rate_pct ?? liveSession?.win_rate_pct))}</span>
						</span>
						<span>
							<span class="text-gray-500">PF</span>
							<span class="text-white font-bold ml-1">{formatRatio(toNumber(liveSession?.performance?.profit_factor ?? liveSession?.profit_factor))}</span>
						</span>
						<span>
							<span class="text-gray-500">Avg</span>
							<span class="font-bold ml-1 {pnlClass(toNumber(liveSession?.performance?.avg_pnl ?? liveSession?.avg_pnl))}">
								{formatUsd(toNumber(liveSession?.performance?.avg_pnl ?? liveSession?.avg_pnl))}
							</span>
						</span>
						<span>
							<span class="text-gray-500">Expect</span>
							<span class="font-bold ml-1 {pnlClass(toNumber(liveSession?.performance?.expectancy ?? liveSession?.expectancy))}">
								{formatUsd(toNumber(liveSession?.performance?.expectancy ?? liveSession?.expectancy))}
							</span>
						</span>
						<span>
							<span class="text-gray-500">Leverage</span>
							<span class="text-white font-bold ml-1">{ribbonLeverage}x</span>
						</span>
						<span>
							<span class="text-gray-500">Default</span>
							<span class="text-white font-bold ml-1">{humanizeLabel(liveSession?.trade_mode ?? 'long_only')}</span>
						</span>
						{#if liveBlockedCount > 0}
							<span>
								<span class="text-gray-500">Blocked</span>
								<span class="text-yellow-300 font-bold ml-1">{liveBlockedCount}</span>
							</span>
						{/if}
						{#if activeOpenTrade}
							<span class="border-l border-[#333] pl-4">
								<span class="text-gray-500">Pos</span>
								<span class="{(activeTrade.direction || '').toLowerCase() === 'long' ? 'text-green-400' : (activeTrade.direction || '').toLowerCase() === 'short' ? 'text-red-400' : 'text-gray-400'} font-bold uppercase ml-1">{activeTrade.direction || '--'}</span>
								<span class="text-white font-bold ml-1">${formatPrice(toNumber(activeTrade.entry_price))}</span>
								<span class="text-gray-500 ml-2">Size</span>
								<span class="text-white font-bold ml-1">{formatSize(toNumber(activeTrade.size))}</span>
							</span>
						{/if}
						<span class="ml-auto text-gray-500">Open {openDuration(activeTrade.opened_at)} ago</span>
					</div>
				</div>

				{#if showDetailsPanel}
					<!-- Collapsible position/details panel (mirrors paper's params panel) -->
					<div class="border-b border-[#171717] bg-[#050505] px-4 py-2 flex-shrink-0 max-h-44 overflow-y-auto">
						<div class="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] md:grid-cols-3">
							<div class="flex justify-between gap-2"><span class="text-gray-500">Trade ID</span><span class="text-gray-300 font-mono truncate" title={tradeIdValue(activeTrade)}>{tradeIdValue(activeTrade) || '--'}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Asset</span><span class="text-white font-bold">{activeTrade.asset || '--'}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Notional</span><span class="text-white font-bold">{activeTradeNotional !== null ? `$${formatPrice(activeTradeNotional)}` : '--'}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Entry</span><span class="text-gray-300">${formatPrice(toNumber(activeTrade.entry_price))}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Mark</span><span class="text-white font-bold">{activeTradeMark !== null ? `$${formatPrice(activeTradeMark)}` : '--'}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Leverage</span><span class="text-gray-300">{toNumber(activeTrade.leverage)?.toFixed(1) ?? '1.0'}x</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Opened</span><span class="text-gray-300">{formatTs(activeTrade.opened_at)}</span></div>
							<div class="flex justify-between gap-2"><span class="text-gray-500">Source</span><span class="text-gray-300 truncate">{tradeSourceLabel(activeTrade)}</span></div>
							{#if activeDeployedStrategy}
								<div class="flex justify-between gap-2"><span class="text-gray-500">Container</span><span class="text-gray-300 truncate">{deployedDisplayLabel(activeDeployedStrategy)}</span></div>
							{/if}
						</div>
						{#if tradeBadges(activeTrade).length > 0}
							<div class="mt-1.5 flex flex-wrap gap-1">
								{#each tradeBadges(activeTrade) as badge}
									<span class={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${badge.className}`}>{badge.label}</span>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Content: Grid [chart 1fr] [bottom panels 192px] -->
				<div
					class="flex-1 overflow-hidden"
					style="display: grid; grid-template-rows: 1fr 192px; min-height: 0;"
				>
					<!-- Chart area -->
					<div class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" style="min-height: 200px;">
						<div class="border-b border-[#171717] bg-[#050505] px-3 py-2">
							<div class="flex flex-col gap-2 2xl:flex-row 2xl:items-center 2xl:justify-between">
								<div class="min-w-0">
									<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
										<span class="text-[10px] font-bold uppercase tracking-[0.24em] text-gray-500">Chart</span>
										<span class="text-[11px] text-white">{activeTrade.asset || '--'} / {activeChartTimeframe}</span>
										<span class="text-[10px] text-gray-600">{tradeIdValue(activeTrade) ? 'Live trade feed' : 'Deployed container view'}</span>
									</div>
									<div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-500">
										<span>Entry ${formatPrice(toNumber(activeTrade.entry_price))}</span>
										<span>Mark {activeTradeMark !== null ? `$${formatPrice(activeTradeMark)}` : '--'}</span>
										<span>{activeChartToolHint()}</span>
									</div>
								</div>
								<div class="flex flex-wrap items-center gap-3">
									<div class="flex flex-wrap items-center gap-1">
										{#each chartTimeframeOptions as timeframe}
											<button
												type="button"
												class={timeframeButtonClass(timeframe)}
												on:click={() => setChartTimeframe(timeframe)}
											>
												{timeframe}
											</button>
										{/each}
									</div>
									<div class="flex flex-wrap items-center gap-1">
										<button
											type="button"
											class={chartToolButtonClass(showIndicatorPanel)}
											on:click={() => (showIndicatorPanel = !showIndicatorPanel)}
											disabled={Object.keys(indicatorConfig).length === 0}
										>
											Indicators
										</button>
										<button
											type="button"
											class={chartToolButtonClass(activeDrawingTool === 'horizontalLine')}
											on:click={() => toggleDrawingTool('horizontalLine')}
										>
											H-Line
										</button>
										<button
											type="button"
											class={chartToolButtonClass(activeDrawingTool === 'trendLine')}
											on:click={() => toggleDrawingTool('trendLine')}
										>
											Trend
										</button>
										<button
											type="button"
											class={chartToolButtonClass(false)}
											on:click={() => (fitContentToken += 1)}
										>
											Reset View
										</button>
										<button
											type="button"
											class={chartToolButtonClass(false)}
											on:click={clearChartDrawings}
											disabled={chartDrawings.length === 0 && !pendingTrendLineStart}
										>
											Clear
										</button>
									</div>
								</div>
							</div>
							<div class="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
								<span class="rounded-sm border border-[#1e293b] bg-[#020617] px-2 py-1 text-slate-300">
									{activeDrawingTool === 'cursor' ? 'Cursor' : activeDrawingTool === 'horizontalLine' ? 'Horizontal lines' : 'Trend lines'}
								</span>
								{#if pendingTrendLineStart}
									<span class="text-sky-300">Trend line anchor locked. Click a second point to finish.</span>
								{/if}
								{#if chartDrawings.length > 0}
									<span class="text-gray-600">{chartDrawings.length} drawing{chartDrawings.length === 1 ? '' : 's'} on chart</span>
								{/if}
							</div>
						</div>
						<div class="flex min-h-0 min-w-0 flex-1 overflow-hidden">
							{#if showIndicatorPanel && Object.keys(indicatorConfig).length > 0}
								<div class="w-44 flex-shrink-0 border-r border-[#171717] bg-[#050505] overflow-y-auto p-2">
									<div class="mb-1 flex items-center justify-between">
										<span class="text-[10px] font-bold uppercase tracking-wider text-gray-500">Indicators</span>
										<button class="text-[10px] text-gray-600 hover:text-gray-300" on:click={() => (showIndicatorPanel = false)}>close</button>
									</div>
									{#each indicatorGroups as group}
										{@const names = indicatorNamesForGroup(group)}
										{#if names.length > 0}
											<div class="mb-2">
												<div class="mb-0.5 text-[9px] uppercase tracking-wider text-gray-600">
													{group === 'overlays' ? 'Overlays' : group === 'lower' ? 'Lower pane' : 'Sidebar only'}
												</div>
												{#each names as name}
													{@const cfg = indicatorConfig[name]}
													<label class="flex cursor-pointer items-center gap-1.5 py-0.5 text-[11px]">
														{#if isChartRenderableIndicator(name, cfg)}
															<input
																type="checkbox"
																class="accent-emerald-500"
																checked={indicatorVisibility[name] ?? true}
																on:change={() => toggleIndicatorVisibility(name)}
															/>
														{:else}
															<span class="w-3"></span>
														{/if}
														<span class="h-2 w-2 flex-shrink-0 rounded-full" style={`background:${cfg?.color || '#888'}`}></span>
														<span class="flex-1 truncate text-gray-300">{name}</span>
														<span class="font-mono text-gray-500">{formatIndicatorValue(getCurrentIndicatorValue(name), name)}</span>
													</label>
												{/each}
											</div>
										{/if}
									{/each}
								</div>
							{/if}
							<div class="relative min-h-0 min-w-0 flex-1">
								{#if loadingChart}
									<div class="h-full p-4"><Skeleton rows={10} /></div>
								{:else if chartBars.length > 0}
									<ChartWorkspace
										data={chartBars}
										{entryMarkers}
										{exitMarkers}
										mainIndicators={mainIndicators.filter((i) => i.visible !== false)}
										subIndicators={subIndicators.filter((i) => i.visible !== false)}
										strategyName={activeTrade.strategy || 'Live Trade'}
										strategyMeta={`${activeTrade.asset || '--'} / ${activeChartTimeframe} / LIVE`}
										strategyParams={{}}
										showStrategyInfo={false}
										autoScroll={true}
										windowSize={200}
										drawings={chartDrawings}
										activeTool={activeDrawingTool}
										{fitContentToken}
										on:drawingPoint={handleChartDrawingPoint}
									/>
								{:else}
									<div class="flex items-center justify-center h-full text-gray-600 text-xs">
										No chart data available for {activeTrade.asset || 'this asset'}
									</div>
								{/if}
							</div>
						</div>
					</div>

					<!-- Bottom panels: Indicators | Signals | Trades (mirrors paper trades) -->
					<div class="border-t border-[#222] grid grid-cols-[1fr_0.75fr_1.5fr] overflow-hidden">
						<!-- Indicators -->
						<div class="border-r border-[#222] p-2 overflow-y-auto">
							<h3 class="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-1.5">Indicators</h3>
							{#if Object.keys(indicatorConfig).length === 0}
								<p class="text-[11px] text-gray-600">{loadingIndicators ? 'Loading…' : 'No indicators for this strategy.'}</p>
							{:else}
								<div class="space-y-0.5">
									{#each Object.keys(indicatorConfig) as name}
										{@const cfg = indicatorConfig[name]}
										{@const group = getIndicatorSidebarGroup(name, cfg)}
										<div class="flex items-center gap-1.5 text-[11px]">
											<span class="h-2 w-2 flex-shrink-0 rounded-full" style={`background:${cfg?.color || '#888'}`}></span>
											<span class="flex-1 truncate text-gray-300">{name}</span>
											<span class="rounded bg-[#111] px-1 text-[8px] uppercase tracking-wider text-gray-500">{group === 'overlays' ? 'OVR' : group === 'lower' ? 'LOW' : 'SIDE'}</span>
											<span class="font-mono text-gray-400">{formatIndicatorValue(getCurrentIndicatorValue(name), name)}</span>
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<!-- Signals (approaching) -->
						<div class="border-r border-[#222] p-2 overflow-y-auto">
							<h3 class="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-1.5">Signals</h3>
							{#if pendingSignals.length === 0}
								<p class="text-[11px] text-gray-600">No approaching signals.</p>
							{:else}
								<div class="space-y-1">
									{#each pendingSignals as sig}
										<div class="text-[11px]">
											<div class="flex items-center gap-1">
												<span class="font-bold {sig.signal_type === 'entry' ? 'text-green-400' : sig.signal_type === 'exit' ? 'text-red-400' : 'text-gray-400'}">
													{sig.signal_type === 'entry' ? '▸' : sig.signal_type === 'exit' ? '◂' : '•'}
												</span>
												<span class="truncate text-gray-300">{sig.description || sig.indicator_name}</span>
											</div>
											<div class="ml-3 text-[10px] text-gray-500">
												{sig.indicator_name}: {formatIndicatorValue(sig.current_value, sig.indicator_name)} → {formatIndicatorValue(sig.trigger_value, sig.indicator_name)}
												{#if sig.distance_pct}<span class="text-gray-600"> ({sig.distance_pct.toFixed(1)}%)</span>{/if}
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<!-- Trade History -->
						<div class="p-2 overflow-y-auto">
							<h3 class="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-1.5">Trade History</h3>
							<TradeHistoryTable rows={filteredClosedTrades} />
						</div>
					</div>
				</div>
			{:else}
				<!-- Empty state (mirrors paper trades layout) -->
				<div
					class="flex-1 overflow-hidden"
					style="display: grid; grid-template-rows: 1fr 192px; min-height: 0;"
				>
					<div class="flex-1 flex flex-col items-center justify-center text-gray-800">
						<svg class="w-20 h-20 mb-4 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
						</svg>
						<h3 class="text-lg font-bold uppercase tracking-widest mb-1">Live Trades</h3>
						<p class="text-xs text-gray-600 max-w-sm text-center">
							No open scanner positions right now. Closed trades continue streaming below.
						</p>
						<!-- Show gate status even with no positions so a paused / kill-switched system is visible. -->
						<div class="mt-4 flex flex-col items-center gap-1.5">
							<TradingGatesStrip {gates} {anyGateBlocking} />
							{#if anyGateBlocking}
								<a href="/risk" class="text-[10px] text-red-300 underline hover:text-red-200">
									New entries are blocked &mdash; review &amp; clear in Risk
								</a>
							{/if}
						</div>
					</div>

					<div class="border-t border-[#222] p-2 overflow-hidden">
						<h3 class="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-1.5">Trade History</h3>
						<div class="h-[calc(100%-20px)] overflow-auto">
							<TradeHistoryTable rows={filteredClosedTrades} headerClass="text-gray-500 border-b border-[#222] bg-[#0a0a0a]" />
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>

{#if showStrategyDrawer}
	<StrategyContainerDrawer
		strategyId={drawerStrategyId}
		displayId={drawerDisplayId}
		strategyName={drawerStrategyName}
		stage={drawerStage}
		metrics={drawerMetrics}
		marketPot={drawerMarketPot}
		showTransitions={false}
		on:close={() => (showStrategyDrawer = false)}
	/>
{/if}
