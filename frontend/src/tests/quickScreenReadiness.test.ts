import { describe, expect, it } from 'vitest';

import type { LifecycleStrategy, PipelineSettings, StrategyContainerHistoryItem } from '../lib/api/lifecycle';
import { buildQuickScreenEvidenceRows } from '../lib/utils/quickScreenReadiness';

function buildBacktest(metrics: Record<string, unknown>): StrategyContainerHistoryItem {
	return {
		result_id: 'B1001',
		strategy_id: 'S0001',
		result_type: 'backtest',
		symbol: 'BTC/USDT',
		timeframe: '1h',
		start_date: '2025-01-01T00:00:00Z',
		end_date: '2025-12-31T00:00:00Z',
		metrics,
		config: {},
		created_at: '2026-04-01T00:00:00Z',
		deleted_at: null,
	};
}

const pipelineSettings: PipelineSettings = {
	version: 1,
	autopilot_enabled: false,
	autopilot_worker_concurrency: 1,
	autopilot_generation_batch_size: 1,
	autopilot_scan_symbol: 'BTC/USDT',
	autopilot_scan_timeframe: '1h',
	promotion_mode: 'quick_screen',
	min_backtest_trades: 20,
	min_sharpe_ratio: 0.5,
	max_drawdown_pct: 40,
	min_profit_factor: 1.2,
	min_paper_days: 0,
	max_paper_divergence_pct: 0,
	min_paper_trades: 0,
	min_paper_sharpe: 0,
	failed_retention_hours: 24,
	ranking_top_n: 10,
	ranking_metric: 'sharpe_ratio',
	created_at: '2026-04-01T00:00:00Z',
	created_by: 'brain',
};

function buildStrategy(metrics: LifecycleStrategy['metrics'] = null): LifecycleStrategy {
	return {
		id: 'S0001',
		display_id: 'S0001',
		hypothesis_id: null,
		hypothesis_display_id: null,
		name: 'BTC Trend Candidate',
		type: 'rsi_momentum',
		state: 'quick_screen',
		source: 'manual',
		source_ref: null,
		owner: 'brain',
		symbol: 'BTC/USDT',
		timeframe: '1h',
		definition_json: null,
		dataset_hash: null,
		policy_version: 1,
		build_version: null,
		metrics_json: null,
		metrics,
		paper_session_id: null,
		paper_started_at: null,
		last_policy_result_json: null,
		blocked_reason: null,
		model: null,
		model_id: null,
		created_at: '2026-04-01T00:00:00Z',
		updated_at: '2026-04-01T00:00:00Z',
		state_changed_at: null,
		failed_at: null,
		retention_expires_at: null,
	};
}

describe('buildQuickScreenEvidenceRows', () => {
	it('builds evidence rows from backtest metrics and validation artifacts', () => {
		const rows = buildQuickScreenEvidenceRows({
			strategy: buildStrategy(),
			backtests: [
				buildBacktest({
					in_sample_sharpe: 0.82,
					total_return_pct: 12.4,
					max_drawdown_pct: 18.7,
				}),
			],
			validationHistory: [
				{
					result_id: 'V1001',
					strategy_id: 'S0001',
					result_type: 'walk_forward',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V1002',
					strategy_id: 'S0001',
					result_type: 'monte_carlo',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V1003',
					strategy_id: 'S0001',
					result_type: 'param_jitter',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V1004',
					strategy_id: 'S0001',
					result_type: 'cost_stress',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V1005',
					strategy_id: 'S0001',
					result_type: 'regime_split',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
			],
			pipelineSettings,
		});

		expect(rows).toHaveLength(4);
		expect(rows).toEqual([
			{
				key: 'is_sharpe_ratio',
				label: 'IS Sharpe Ratio',
				status: 'passed',
				actual: '0.82',
				required: '> 0.50',
				detail: 'Actual 0.82 | Required > 0.50',
			},
			{
				key: 'validation_coverage',
				label: 'Validation Coverage',
				status: 'passed',
				actual: '5/5',
				required: 'All required artifacts present',
				detail: 'Validation artifacts present: 5/5',
			},
			{
				key: 'minimum_return',
				label: 'Minimum Return',
				status: 'passed',
				actual: '12.4%',
				required: '> 0%',
				detail: 'Actual 12.4% | Required > 0%',
			},
			{
				key: 'max_drawdown',
				label: 'Max Drawdown',
				status: 'passed',
				actual: '18.7%',
				required: '< 40%',
				detail: 'Actual 18.7% | Required < 40%',
			},
		]);
	});

	it('marks missing evidence as warning or failed rows', () => {
		const rows = buildQuickScreenEvidenceRows({
			strategy: null,
			backtests: [],
			validationHistory: [],
			pipelineSettings,
		});

		expect(rows).toEqual([
			{
				key: 'is_sharpe_ratio',
				label: 'IS Sharpe Ratio',
				status: 'warning',
				actual: 'Unavailable',
				required: '> 0.50',
				detail: 'Unavailable | Required > 0.50',
			},
			{
				key: 'validation_coverage',
				label: 'Validation Coverage',
				status: 'failed',
				actual: '0/5',
				required: 'All required artifacts present',
				detail: 'Validation artifacts present: 0/5; missing all required artifacts',
			},
			{
				key: 'minimum_return',
				label: 'Minimum Return',
				status: 'warning',
				actual: 'Unavailable',
				required: '> 0%',
				detail: 'Unavailable | Required > 0%',
			},
			{
				key: 'max_drawdown',
				label: 'Max Drawdown',
				status: 'warning',
				actual: 'Unavailable',
				required: '< 40%',
				detail: 'Unavailable | Required < 40%',
			},
		]);
	});

	it('ignores explicit failed or pending validation artifacts when counting coverage', () => {
		const rows = buildQuickScreenEvidenceRows({
			strategy: buildStrategy(),
			backtests: [
				buildBacktest({
					in_sample_sharpe: 0.82,
					total_return_pct: 12.4,
					max_drawdown_pct: 18.7,
				}),
			],
			validationHistory: [
				{
					result_id: 'V2001',
					strategy_id: 'S0001',
					result_type: 'walk_forward',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: { status: 'failed' },
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V2002',
					strategy_id: 'S0001',
					result_type: 'monte_carlo',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: { status: 'pending' },
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V2003',
					strategy_id: 'S0001',
					result_type: 'param_jitter',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: {},
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V2004',
					strategy_id: 'S0001',
					result_type: 'cost_stress',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: { status: '' },
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
				{
					result_id: 'V2005',
					strategy_id: 'S0001',
					result_type: 'regime_split',
					symbol: 'BTC/USDT',
					timeframe: '1h',
					start_date: '2025-01-01T00:00:00Z',
					end_date: '2025-12-31T00:00:00Z',
					metrics: {},
					config: { status: 'completed' },
					created_at: '2026-04-01T00:00:00Z',
					deleted_at: null,
				},
			],
			pipelineSettings,
		});

		expect(rows[1]).toMatchObject({
			key: 'validation_coverage',
			actual: '3/5',
			required: 'All required artifacts present',
		});
		expect(rows[1].detail).toContain('Validation artifacts present: 3/5');
	});
});
