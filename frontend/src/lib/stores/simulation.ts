import { derived } from 'svelte/store';
import { forvenDashboard } from './forven';

export const simulationActive = derived(forvenDashboard, ($d) =>
	Boolean($d?.simulation_active)
);

export const simulationPhase = derived(forvenDashboard, ($d) =>
	$d?.simulation_phase || 'idle'
);

export const simulationTime = derived(forvenDashboard, ($d) =>
	$d?.simulation_time || ''
);

export const simulationProgress = derived(forvenDashboard, ($d) =>
	$d?.simulation_progress || 0
);

export const simulationPrices = derived(forvenDashboard, ($d) =>
	$d?.simulation_prices || {}
);
