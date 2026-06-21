<script lang="ts">
	import type { LifecycleStrategy } from '$lib/api';

	export let strategies: LifecycleStrategy[];
	export let activeKey: string;
	export let onSelect: (strategy: LifecycleStrategy) => void;

	function normalizeStrategyKey(value: string | null | undefined): string {
		return String(value || '').trim().toLowerCase();
	}

	function deployedStrategyKey(strategy: LifecycleStrategy): string {
		return normalizeStrategyKey(strategy.id || strategy.name || '');
	}

	function deployedStateLabel(state: string | null | undefined): string {
		const normalized = normalizeStrategyKey(state);
		return normalized ? normalized.replaceAll('_', ' ') : 'deployed';
	}

	function deployedDisplayLabel(strategy: LifecycleStrategy): string {
		const displayId = String(strategy.display_id || '').trim();
		const ref = String(strategy.source_ref || '').trim();
		const name = String(strategy.name || '').trim();
		const id = String(strategy.id || '').trim();
		return displayId || ref || name || id || '--';
	}
</script>

{#if strategies.length > 0}
	<div class="mt-2 px-2 pb-2 border-t border-[#222]">
		<p class="text-[10px] uppercase tracking-wider text-gray-500 mb-2 mt-2">
			Deployed Containers
			<span class="text-gray-600 normal-case ml-1">({strategies.length})</span>
		</p>
		<div class="space-y-1.5">
			{#each strategies as strategy}
				{@const isActive = activeKey === deployedStrategyKey(strategy)}
				<button
					class="w-full border px-2 py-1.5 rounded-sm text-left transition-colors {isActive ? 'border-green-700 bg-[#0f1510]' : 'border-[#1a1a1a] bg-[#080808] hover:border-[#2a2a2a]'}"
					on:click={() => onSelect(strategy)}
				>
					<div class="flex items-center justify-between gap-2">
						<span class="text-[11px] text-gray-200 truncate">{deployedDisplayLabel(strategy)}</span>
						<span class="text-[10px] uppercase text-green-400 flex-shrink-0">{deployedStateLabel(strategy.state)}</span>
					</div>
					<div class="text-[10px] text-gray-500 truncate">
						{strategy.symbol || '--'} | {strategy.timeframe || '--'}
					</div>
				</button>
			{/each}
		</div>
	</div>
{/if}
