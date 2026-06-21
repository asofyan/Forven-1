import type { PageLoad } from './$types';
import {
	getForvenOpenTrades,
	getForvenRecentTrades,
	getForvenDashboard,
	listLifecycleStrategies,
} from '$lib/api';
import type { ForvenTrade, ForvenDashboardResponse, LifecycleStrategy } from '$lib/api';

export const ssr = false;

export const load: PageLoad = async () => {
	const [openResult, recentResult, dashboardResult, lifecycleResult] = await Promise.allSettled([
		getForvenOpenTrades(),
		getForvenRecentTrades(300),
		getForvenDashboard(),
		// Filter to deployed/live strategies explicitly: the unfiltered list is capped
		// at `limit` of ~2900 rows and the handful of live strategies fall outside that
		// window, so they never reached the Open Positions panel (count + unpositioned).
		listLifecycleStrategies({ state: 'deployed', limit: 500 }),
	]);

	return {
		openTrades: openResult.status === 'fulfilled' ? openResult.value : [],
		recentTrades: recentResult.status === 'fulfilled' ? recentResult.value : [],
		dashboard: dashboardResult.status === 'fulfilled' ? dashboardResult.value : null,
		deployedStrategies: lifecycleResult.status === 'fulfilled' ? lifecycleResult.value : [],
	} satisfies {
		openTrades: ForvenTrade[];
		recentTrades: ForvenTrade[];
		dashboard: ForvenDashboardResponse | null;
		deployedStrategies: LifecycleStrategy[];
	};
};
