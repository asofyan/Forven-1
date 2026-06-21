import type { LifecycleStrategy, PipelineSettings, StrategyContainerHistoryItem } from '$lib/api/lifecycle';
import {
	asMetricRecord,
	readMetricFromSources,
	readNestedMetricFromSources,
	readPercentMetricFromSources,
} from '$lib/utils/strategy';

export type QuickScreenEvidenceStatus = 'passed' | 'failed' | 'warning' | 'skipped';

export interface QuickScreenEvidenceRow {
	key: string;
	label: string;
	status: QuickScreenEvidenceStatus;
	actual: string;
	required: string;
	detail: string;
}

const REQUIRED_VALIDATION_TYPES = ['walk_forward', 'monte_carlo', 'param_jitter', 'cost_stress', 'regime_split'] as const;

type QuickScreenEvidenceSource = Record<string, unknown>;
const SUCCESS_LIKE_VALIDATION_STATUSES = new Set([
	'succeeded',
	'success',
	'pass',
	'passed',
	'done',
	'completed',
	'complete',
]);

function toFiniteNumber(value: unknown): number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim()) {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}
	return null;
}

function formatDecimal(value: number | null, digits = 2): string {
	if (value === null || !Number.isFinite(value)) return 'Unavailable';
	return value.toFixed(digits);
}

function formatCompactPercentValue(value: number, digits = 2): string {
	return value
		.toFixed(digits)
		.replace(/\.?0+$/, '');
}

function formatPercent(value: number | null, digits = 2): string {
	if (value === null || !Number.isFinite(value)) return 'Unavailable';
	return `${formatCompactPercentValue(value, digits)}%`;
}

function formatPercentThreshold(value: number | null): string {
	if (value === null || !Number.isFinite(value)) return 'Unavailable';
	return `${formatCompactPercentValue(value)}%`;
}

function normalizeValidationType(value: unknown): string | null {
	const normalized = String(value ?? '').trim().toLowerCase().replace(/[-\s]/g, '_');
	if (!normalized) return null;
	const aliases: Record<string, string> = {
		wfa: 'walk_forward',
		walkforward: 'walk_forward',
		walk_forward: 'walk_forward',
		montecarlo: 'monte_carlo',
		mc: 'monte_carlo',
		monte_carlo: 'monte_carlo',
		paramjitter: 'param_jitter',
		jitter: 'param_jitter',
		param_jitter: 'param_jitter',
		coststress: 'cost_stress',
		stress: 'cost_stress',
		cost_stress: 'cost_stress',
		regimesplit: 'regime_split',
		regime: 'regime_split',
		regime_split: 'regime_split',
	};
	return aliases[normalized] || normalized;
}

function buildMetricSources(
	strategy: LifecycleStrategy | null,
	backtests: StrategyContainerHistoryItem[]
): QuickScreenEvidenceSource[] {
	const sources: QuickScreenEvidenceSource[] = [];

	if (strategy) {
		sources.push(asMetricRecord(strategy.metrics));
		sources.push(asMetricRecord(strategy.metrics_json));
	}

	for (const item of backtests) {
		sources.push(asMetricRecord(item.metrics));
		sources.push(asMetricRecord(item.config));
	}

	return sources.filter((source) => Object.keys(source).length > 0);
}

function buildThresholdRow(args: {
	key: string;
	label: string;
	actual: string;
	required: string;
	detail: string;
	status: QuickScreenEvidenceStatus;
}): QuickScreenEvidenceRow {
	return {
		key: args.key,
		label: args.label,
		status: args.status,
		actual: args.actual,
		required: args.required,
		detail: args.detail,
	};
}

function compareThreshold(actual: number | null, required: number, passIfAbove: boolean): QuickScreenEvidenceStatus {
	if (actual === null) return 'warning';
	if (passIfAbove) return actual > required ? 'passed' : 'failed';
	return actual < required ? 'passed' : 'failed';
}

function getValidationStatusCandidate(item: StrategyContainerHistoryItem): string {
	const itemRecord = item as unknown as Record<string, unknown>;
	const values = [
		item.config?.status,
		item.metrics?.status,
		itemRecord.status,
	];
	for (const value of values) {
		const text = String(value ?? '').trim().toLowerCase();
		if (text) return text;
	}
	return '';
}

function isValidationEvidenceAccepted(item: StrategyContainerHistoryItem): boolean {
	const status = getValidationStatusCandidate(item);
	return !status || SUCCESS_LIKE_VALIDATION_STATUSES.has(status);
}

export function buildQuickScreenEvidenceRows(args: {
	strategy: LifecycleStrategy | null;
	backtests: StrategyContainerHistoryItem[];
	validationHistory: StrategyContainerHistoryItem[];
	pipelineSettings: Partial<PipelineSettings> | null;
}): QuickScreenEvidenceRow[] {
	const { strategy, backtests, validationHistory, pipelineSettings } = args;
	const strategyRecord = strategy ? asMetricRecord(strategy) : {};
	const sources = buildMetricSources(strategy, backtests);

	const inSampleSharpe = readMetricFromSources(
		strategyRecord,
		sources,
		['in_sample_sharpe', 'is_sharpe', 'is_sharpe_ratio'],
		readNestedMetricFromSources(strategyRecord, sources, ['in_sample', 'is_metrics', 'inSample'], ['sharpe_ratio', 'sharpe'])
	);
	const totalReturn = readPercentMetricFromSources(strategyRecord, sources, ['total_return_pct', 'total_return', 'pnl_pct', 'return_pct']);
	const maxDrawdown = readPercentMetricFromSources(strategyRecord, sources, ['max_drawdown_pct', 'drawdown_pct', 'max_drawdown']);
	const sharpeThreshold = pipelineSettings?.min_sharpe_ratio ?? 0.5;
	const drawdownLimit = pipelineSettings?.max_drawdown_pct ?? 40;

	const normalizedValidationTypes = new Set<string>();
	for (const item of validationHistory) {
		if (item.deleted_at) continue;
		if (!isValidationEvidenceAccepted(item)) continue;
		const normalized = normalizeValidationType(item.result_type);
		if (normalized && REQUIRED_VALIDATION_TYPES.includes(normalized as typeof REQUIRED_VALIDATION_TYPES[number])) {
			normalizedValidationTypes.add(normalized);
		}
	}

	const validationCount = normalizedValidationTypes.size;
	const missingValidationTypes = REQUIRED_VALIDATION_TYPES.filter((type) => !normalizedValidationTypes.has(type));

	const sharpeStatus = compareThreshold(inSampleSharpe, sharpeThreshold, true);
	const returnStatus = totalReturn === null ? 'warning' : totalReturn > 0 ? 'passed' : 'failed';
	const drawdownStatus = compareThreshold(maxDrawdown, drawdownLimit, false);
	const validationStatus = validationCount === REQUIRED_VALIDATION_TYPES.length ? 'passed' : (validationCount === 0 ? 'failed' : 'warning');

	return [
		buildThresholdRow({
			key: 'is_sharpe_ratio',
			label: 'IS Sharpe Ratio',
			status: sharpeStatus,
			actual: formatDecimal(inSampleSharpe),
			required: `> ${formatDecimal(sharpeThreshold)}`,
			detail: inSampleSharpe === null
				? `Unavailable | Required > ${formatDecimal(sharpeThreshold)}`
				: `Actual ${formatDecimal(inSampleSharpe)} | Required > ${formatDecimal(sharpeThreshold)}`,
		}),
		buildThresholdRow({
			key: 'validation_coverage',
			label: 'Validation Coverage',
			status: validationStatus,
			actual: `${validationCount}/${REQUIRED_VALIDATION_TYPES.length}`,
			required: 'All required artifacts present',
			detail: validationCount === REQUIRED_VALIDATION_TYPES.length
				? `Validation artifacts present: ${validationCount}/${REQUIRED_VALIDATION_TYPES.length}`
				: missingValidationTypes.length === REQUIRED_VALIDATION_TYPES.length
					? `Validation artifacts present: ${validationCount}/${REQUIRED_VALIDATION_TYPES.length}; missing all required artifacts`
					: `Validation artifacts present: ${validationCount}/${REQUIRED_VALIDATION_TYPES.length}; missing ${missingValidationTypes.join(', ')}`,
		}),
		buildThresholdRow({
			key: 'minimum_return',
			label: 'Minimum Return',
			status: returnStatus,
			actual: formatPercent(totalReturn),
			required: '> 0%',
			detail: totalReturn === null
				? 'Unavailable | Required > 0%'
				: `Actual ${formatPercent(totalReturn)} | Required > 0%`,
		}),
		buildThresholdRow({
			key: 'max_drawdown',
			label: 'Max Drawdown',
			status: drawdownStatus,
			actual: formatPercent(maxDrawdown),
			required: `< ${formatPercentThreshold(drawdownLimit)}`,
			detail: maxDrawdown === null
				? `Unavailable | Required < ${formatPercentThreshold(drawdownLimit)}`
				: `Actual ${formatPercent(maxDrawdown)} | Required < ${formatPercentThreshold(drawdownLimit)}`,
		}),
	];
}
