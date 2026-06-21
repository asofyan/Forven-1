<script lang="ts">
	import PaperTrades from '$lib/components/trading/PaperTrades.svelte';
	import PaperSessionSummary from '$lib/components/dashboard/PaperSessionSummary.svelte';
	import type { ForvenDashboardResponse } from '$lib/api';

	export let data: { dashboard: ForvenDashboardResponse | null };
</script>

<svelte:head>
	<title>Paper Trades | Forven</title>
	<meta name="description" content="Run live and replay paper sessions with chart overlays, signals, and execution history." />
</svelte:head>

<div class="workspace-layout flex-col">
	<div class="flex-shrink-0 px-2 pt-2">
		<PaperSessionSummary />
	</div>
	<div class="flex-1 flex flex-col overflow-hidden">
		<PaperTrades dashboard={data.dashboard} />
	</div>
</div>
