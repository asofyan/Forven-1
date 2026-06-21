import { writable } from 'svelte/store';
import type {
	ForvenDashboardResponse,
	ForvenRiskStatus,
	ForvenRegimeSnapshot,
	ForvenScannerState,
	ForvenSentimentSnapshot,
	ForvenTrade,
} from '$lib/api';

// Passive writable stores — populated by heartbeat.ts via the unified
// /api/system/heartbeat endpoint.  Individual pages that need a direct
// refresh can still call the original API functions and .set() here.

export const forvenDashboard = writable<ForvenDashboardResponse | null>(null);
export const forvenRisk = writable<ForvenRiskStatus | null>(null);
export const forvenSentiment = writable<ForvenSentimentSnapshot | null>(null);
export const forvenRegime = writable<ForvenRegimeSnapshot | null>(null);
export const forvenOpenTrades = writable<ForvenTrade[]>([]);
export const forvenScannerState = writable<ForvenScannerState | null>(null);
