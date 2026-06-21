<script lang="ts">
	import DataTable from '$lib/components/DataTable.svelte';
	import type { ForvenTrade } from '$lib/api';

	export let rows: ForvenTrade[];
	export let headerClass = 'text-gray-500 border-b border-[#222]';

	const historyColumns = [
		{ key: 'direction', label: 'Side' },
		{ key: 'entry_time', label: 'Entry Time' },
		{ key: 'exit_time', label: 'Exit Time' },
		{ key: 'entry_price', label: 'Entry' },
		{ key: 'exit_price', label: 'Exit' },
		{ key: 'pnl_usd', label: '$ P&L', align: 'right' as const },
		{ key: 'pnl_pct', label: 'P&L %', align: 'right' as const },
	];

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

	function formatTs(value: string | null | undefined): string {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '--';
		return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
	}

	function directionLabel(direction: string | null | undefined): 'LONG' | 'SHORT' {
		return String(direction || '').toLowerCase() === 'short' ? 'SHORT' : 'LONG';
	}

	function pnlClass(value: number | null): string {
		if (value === null) return 'text-gray-500';
		return value >= 0 ? 'text-green-400' : 'text-red-400';
	}

	function asTrade(row: unknown): ForvenTrade {
		return row as ForvenTrade;
	}

	function historyRowKey(row: unknown, index: number): string {
		const trade = asTrade(row);
		return String(trade.id ?? `${trade.strategy ?? 'trade'}-${index}`);
	}
</script>

<DataTable
	columns={historyColumns}
	{rows}
	rowKey={historyRowKey}
	tableClass="w-full text-[11px]"
	{headerClass}
	rowClass="border-b border-[#111] hover:bg-[#111]"
	emptyText="No closed trades yet"
	emptyClass="py-3 text-center text-gray-600 text-[11px]"
	stickyHeader={true}
>
	<svelte:fragment slot="cell" let:row let:column>
		{@const trade = asTrade(row)}
		{#if column.key === 'direction'}
			<span class="font-bold {directionLabel(trade.direction) === 'LONG' ? 'text-green-400' : 'text-red-400'}">
				{directionLabel(trade.direction)}
			</span>
		{:else if column.key === 'entry_time'}
			<span class="text-gray-400">{formatTs(trade.opened_at)}</span>
		{:else if column.key === 'exit_time'}
			<span class="text-gray-400">{formatTs(trade.closed_at)}</span>
		{:else if column.key === 'entry_price'}
			<span class="text-gray-400">${formatPrice(toNumber(trade.entry_price))}</span>
		{:else if column.key === 'exit_price'}
			<span class="text-gray-400">${formatPrice(toNumber(trade.exit_price))}</span>
		{:else if column.key === 'pnl_usd'}
			{@const usd = toNumber(trade.pnl_usd)}
			<span class="font-bold {pnlClass(usd)}">{formatUsd(usd)}</span>
		{:else if column.key === 'pnl_pct'}
			{@const pct = normalizePercent(toNumber(trade.pnl_pct))}
			<span class="font-bold {pnlClass(pct)}">{formatPct(pct)}</span>
		{/if}
	</svelte:fragment>
</DataTable>
