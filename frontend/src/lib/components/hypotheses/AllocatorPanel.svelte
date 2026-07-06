<script lang="ts">
	import { onMount } from 'svelte';
	import { getAllocatorOverview, type AllocatorOverview } from '$lib/api/hypotheses';

	/** How many ranked rows to show before "show all". */
	const COLLAPSED_ROWS = 10;

	let overview: AllocatorOverview | null = null;
	let error = '';
	let loading = true;
	let showAll = false;

	export async function refresh(): Promise<void> {
		try {
			overview = await getAllocatorOverview(40);
			error = '';
		} catch (err) {
			error = err instanceof Error ? err.message : 'Allocator overview unavailable.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void refresh();
	});

	$: budget = overview?.budget;
	$: quota = overview?.short_quota;
	$: pool = overview?.pool;
	$: rows = overview?.crucibles ?? [];
	$: visibleRows = showAll ? rows : rows.slice(0, COLLAPSED_ROWS);
	$: budgetPct = budget && budget.daily > 0 ? Math.min(100, (budget.used_today / budget.daily) * 100) : 0;
	$: quotaOnTrack = quota ? quota.develops_today === 0 || quota.share_pct >= quota.target_pct : true;

	function scoreTone(score: number): string {
		if (score >= 6) return 'text-emerald-400';
		if (score >= 2) return 'text-white';
		if (score >= 0) return 'text-[#888]';
		return 'text-red-400';
	}

	function statusChip(status: string): string {
		if (status === 'proven') return 'border-emerald-800 text-emerald-400';
		if (status === 'researching') return 'border-[#333] text-[#888]';
		return 'border-[#333] text-[#666]';
	}
</script>

<div class="border border-[#222] bg-[#050505]" data-testid="allocator-panel">
	<div class="flex flex-wrap items-center justify-between gap-2 border-b border-[#1a1a1a] px-4 py-2">
		<h2 class="text-sm font-bold uppercase tracking-wider text-white">
			Research Budget
			<span class="ml-2 border border-[#333] px-1.5 py-0.5 text-[9px] font-normal tracking-wider text-[#666]"
				title="CRUX-1: both dispatch loops rank the pool by expected survivor value and share this daily develop budget">
				VALUE-RANKED
			</span>
		</h2>
		{#if pool}
			<span class="text-[11px] text-[#666]">
				{pool.total} active · {pool.by_status['proven'] ?? 0} proven ·
				<span class={pool.with_survivors > 0 ? 'text-emerald-400' : ''}>{pool.with_survivors} with survivors</span>
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="h-16 animate-pulse bg-[#0a0a0a]"></div>
	{:else if error}
		<p class="px-4 py-3 text-[11px] text-[#666]">{error}</p>
	{:else if overview}
		<div class="grid grid-cols-1 gap-px border-b border-[#1a1a1a] bg-[#1a1a1a] md:grid-cols-3">
			<div class="bg-[#050505] px-4 py-2.5">
				<div class="mb-1 flex items-baseline justify-between">
					<span class="text-[9px] uppercase tracking-wider text-[#555]">Develop budget · today</span>
					<span class="text-[11px] text-[#888]">
						<span class="font-bold text-white">{budget?.used_today ?? 0}</span> / {budget?.daily ?? 0}
					</span>
				</div>
				<div class="h-1.5 bg-[#1a1a1a]">
					<div
						class={budgetPct >= 100 ? 'h-full bg-yellow-500' : 'h-full bg-white/60'}
						style={`width:${budgetPct}%`}
					></div>
				</div>
			</div>
			<div class="bg-[#050505] px-4 py-2.5">
				<span class="block text-[9px] uppercase tracking-wider text-[#555]">Short/both quota</span>
				<span class="text-sm font-bold {quotaOnTrack ? 'text-emerald-400' : 'text-yellow-500'}">
					{quota?.share_pct ?? 0}%
				</span>
				<span class="text-[10px] text-[#666]">
					of {quota?.develops_today ?? 0} develops · target {quota?.target_pct ?? 0}%
				</span>
			</div>
			<div class="bg-[#050505] px-4 py-2.5">
				<span class="block text-[9px] uppercase tracking-wider text-[#555]">Pool composition</span>
				<span class="text-[11px] text-[#888]">
					{#each Object.entries(pool?.by_status ?? {}) as [status, count], i (status)}
						{i > 0 ? ' · ' : ''}{count} {status}
					{/each}
				</span>
			</div>
		</div>

		<div class="overflow-x-auto">
			<table class="w-full text-[11px]">
				<thead>
					<tr class="border-b border-[#1a1a1a] text-left text-[9px] uppercase tracking-wider text-[#555]">
						<th class="px-3 py-1.5">#</th>
						<th class="px-2 py-1.5">Crucible</th>
						<th class="px-2 py-1.5">Status</th>
						<th class="px-2 py-1.5">Family</th>
						<th class="px-2 py-1.5 text-right" title="CRUX-1 value score: survivors x6, gauntlet x1.5, verdict-positives x2, family prior, minus fruitless/failed develops">Score</th>
						<th class="px-2 py-1.5 text-right" title="strategies spawned">Kids</th>
						<th class="px-2 py-1.5 text-right" title="children currently in the gauntlet">Gaunt</th>
						<th class="px-2 py-1.5 text-right" title="children that reached paper/live — ground truth">Surv</th>
						<th class="px-2 py-1.5 text-right" title="fruitless + failed develop attempts (3 parks the crucible)">Strikes</th>
					</tr>
				</thead>
				<tbody>
					{#each visibleRows as crucible, index (crucible.id)}
						<tr class="border-b border-[#111] hover:bg-[#0d0d0d] {crucible.survivor_children > 0 ? 'shadow-[inset_2px_0_0_0_rgba(16,185,129,0.7)]' : ''}">
							<td class="px-3 py-1.5 text-[#555]">{index + 1}</td>
							<td class="max-w-[380px] px-2 py-1.5">
								<a href={`/hypotheses/${crucible.id}`} class="font-mono text-white hover:underline">{crucible.display_id}</a>
								<span class="ml-2 truncate text-[#666]" title={crucible.title}>{crucible.title.slice(0, 60)}</span>
							</td>
							<td class="px-2 py-1.5">
								<span class={`border px-1 py-0.5 text-[9px] uppercase tracking-wider ${statusChip(crucible.status)}`}>
									{crucible.status}
								</span>
							</td>
							<td class="px-2 py-1.5 text-[#888]">{crucible.family}</td>
							<td class={`px-2 py-1.5 text-right font-bold ${scoreTone(crucible.score)}`}>{crucible.score.toFixed(2)}</td>
							<td class="px-2 py-1.5 text-right text-[#888]">{crucible.children}</td>
							<td class="px-2 py-1.5 text-right text-[#888]">{crucible.gauntlet_children || '—'}</td>
							<td class="px-2 py-1.5 text-right {crucible.survivor_children > 0 ? 'font-bold text-emerald-400' : 'text-[#555]'}">
								{crucible.survivor_children || '—'}
							</td>
							<td class="px-2 py-1.5 text-right {crucible.fruitless_develops + crucible.failed_develops >= 2 ? 'text-yellow-500' : 'text-[#555]'}">
								{crucible.fruitless_develops + crucible.failed_develops || '—'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if rows.length > COLLAPSED_ROWS}
			<button
				class="w-full border-t border-[#1a1a1a] px-4 py-1.5 text-[10px] uppercase tracking-wider text-[#666] hover:text-white"
				on:click={() => (showAll = !showAll)}
			>
				{showAll ? `Show top ${COLLAPSED_ROWS}` : `Show all ${rows.length} ranked`}
			</button>
		{/if}
		<p class="border-t border-[#1a1a1a] px-4 py-1.5 text-[10px] text-[#555]">
			Dispatch order for both research loops. Survivors (paper/live descendants) dominate the score;
			green-edged rows are proven earners being exploited, not just explored.
		</p>
	{/if}
</div>
