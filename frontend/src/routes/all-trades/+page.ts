import type { PageLoad } from './$types';
import { getForvenAllTrades } from '$lib/api';
import type { ForvenTradesPage } from '$lib/api';

export const ssr = false;

export const load: PageLoad = async () => {
	const [result] = await Promise.allSettled([getForvenAllTrades({ limit: 200 })]);
	return {
		initialPage: result.status === 'fulfilled' ? result.value : null,
	} satisfies { initialPage: ForvenTradesPage | null };
};
