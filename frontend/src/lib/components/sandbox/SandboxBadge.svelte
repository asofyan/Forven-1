<script lang="ts">
	import { onMount } from 'svelte';
	import { listSandboxRuns, type SandboxRunRow } from '$lib/api/sandbox';
	import AstFindingsDrawer from './AstFindingsDrawer.svelte';

	export let strategyId: string | null = null;
	/** Filesystem path of the strategy. Used to detect builtin vs custom and
	 * passed to the AST scanner when the operator clicks "Re-scan". */
	export let strategyPath: string | null = null;

	let latest: SandboxRunRow | null = null;
	let loading = true;
	let drawerOpen = false;

	$: isCustom = strategyPath
		? /(forven|forven)[\\/]+strategies[\\/]+custom[\\/]+/i.test(strategyPath)
		: true; // Conservative: treat unknown paths as custom (sandbox-eligible).

	async function load() {
		if (!strategyId) {
			loading = false;
			return;
		}
		try {
			const resp = await listSandboxRuns({
				strategyId,
				limit: 1,
				offset: 0
			});
			latest = resp.rows[0] ?? null;
		} catch {
			latest = null;
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function fmt(n: number | null, suffix: string, digits = 1): string {
		if (n === null || n === undefined) return '—';
		return `${n.toFixed(digits)}${suffix}`;
	}

	$: badgeText = (() => {
		if (!isCustom) return 'Native (builtin)';
		if (loading) return 'Sandbox: …';
		if (!latest) return 'Sandboxed: not yet run';
		const mem = latest.memory_peak_mb !== null ? `${latest.memory_peak_mb} MB peak` : '—';
		const cpu = fmt(latest.cpu_seconds, 's CPU', 2);
		if (latest.kind === 'scan') return `Sandbox: AST scan only · ${latest.error ?? 'clean'}`;
		if (latest.timed_out) return 'Sandbox: timed out';
		if (latest.exit_code === 0) return `Sandboxed: subprocess · ${mem} · ${cpu}`;
		return `Sandbox: exit ${latest.exit_code}`;
	})();

	$: tone = (() => {
		if (!isCustom) return 'native';
		if (!latest) return 'idle';
		if (latest.timed_out || (latest.exit_code ?? 0) !== 0 || latest.error) return 'bad';
		return 'good';
	})();
</script>

<button
	type="button"
	class="badge {tone}"
	on:click={() => {
		if (isCustom) drawerOpen = true;
	}}
	disabled={!isCustom}
	title={isCustom ? 'Click to view AST scan findings' : 'Built-in strategies bypass the sandbox'}
>
	<span class="dot"></span>
	{badgeText}
</button>

{#if drawerOpen}
	<AstFindingsDrawer
		{strategyId}
		{strategyPath}
		on:close={() => (drawerOpen = false)}
	/>
{/if}

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
		background: #1a1a1a;
		border: 1px solid #2a2a2a;
		border-radius: 4px;
		color: #ccc;
		font-family: inherit;
		cursor: pointer;
		transition: border-color 120ms ease, color 120ms ease;
	}

	.badge:not(:disabled):hover {
		border-color: #4f8df7;
		color: #fff;
	}

	.badge:disabled {
		cursor: default;
		opacity: 0.7;
	}

	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: #555;
	}

	.badge.good .dot {
		background: #4ade80;
	}

	.badge.bad .dot {
		background: #f87171;
	}

	.badge.idle .dot {
		background: #aaa;
	}

	.badge.native .dot {
		background: #6aa6ff;
	}
</style>
