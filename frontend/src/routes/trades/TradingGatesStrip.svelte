<script lang="ts">
	export let gates: {
		system_paused: boolean;
		kill_switch: boolean;
		daily_loss_halt: boolean;
		recovery_active: boolean;
		hl_price: string;
		hl_trade: string;
		hl_account: string;
	};
	export let anyGateBlocking: boolean;
</script>

<div class="flex flex-wrap items-center gap-1.5">
	{#if anyGateBlocking}
		<span class="text-[9px] font-bold text-red-400 mr-1">BLOCKED</span>
	{:else}
		<span class="text-[9px] font-bold text-green-500 mr-1">ALL GATES OK</span>
	{/if}
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.system_paused ? 'bg-red-900/60 text-red-300 border border-red-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		System {gates.system_paused ? 'PAUSED' : '✓'}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.kill_switch ? 'bg-red-900/60 text-red-300 border border-red-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Kill Switch {gates.kill_switch ? 'ACTIVE' : '✓'}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.daily_loss_halt ? 'bg-red-900/60 text-red-300 border border-red-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Daily Loss {gates.daily_loss_halt ? 'HALT' : '✓'}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.recovery_active ? 'bg-red-900/60 text-red-300 border border-red-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Recovery {gates.recovery_active ? 'ACTIVE' : '✓'}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.hl_price === 'open' ? 'bg-red-900/60 text-red-300 border border-red-700' : gates.hl_price === 'half_open' ? 'bg-yellow-900/60 text-yellow-300 border border-yellow-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Price API {gates.hl_price === 'closed' ? '✓' : gates.hl_price.toUpperCase()}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.hl_trade === 'open' ? 'bg-red-900/60 text-red-300 border border-red-700' : gates.hl_trade === 'half_open' ? 'bg-yellow-900/60 text-yellow-300 border border-yellow-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Trade API {gates.hl_trade === 'closed' ? '✓' : gates.hl_trade.toUpperCase()}
	</span>
	<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono {gates.hl_account === 'open' ? 'bg-red-900/60 text-red-300 border border-red-700' : gates.hl_account === 'half_open' ? 'bg-yellow-900/60 text-yellow-300 border border-yellow-700' : 'bg-[#111] text-gray-500 border border-[#222]'}">
		Account API {gates.hl_account === 'closed' ? '✓' : gates.hl_account.toUpperCase()}
	</span>
</div>
