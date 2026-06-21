<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import {
		scanStrategy,
		type AstFinding,
		type AstReport
	} from '$lib/api/sandbox';

	export let strategyId: string | null = null;
	export let strategyPath: string | null = null;

	const dispatch = createEventDispatcher<{ close: void }>();

	let report: AstReport | null = null;
	let loading = false;
	let errorMsg: string | null = null;

	async function rescan() {
		if (!strategyPath) {
			errorMsg = 'No strategy path available — cannot scan.';
			return;
		}
		loading = true;
		errorMsg = null;
		try {
			report = await scanStrategy(strategyPath, {
				strategyId: strategyId ?? undefined
			});
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	onMount(rescan);

	function close() {
		dispatch('close');
	}

	function findingClass(f: AstFinding): string {
		if (f.kind === 'forbidden_import' || f.kind === 'dangerous_call') return 'bad';
		return 'warn';
	}
</script>

<div class="overlay" role="dialog" aria-modal="true" aria-label="AST findings">
	<div class="backdrop" on:click={close} on:keydown role="presentation"></div>
	<aside class="drawer">
		<header>
			<h2>AST Scan</h2>
			<button type="button" class="close" on:click={close} aria-label="Close">×</button>
		</header>
		<div class="meta">
			<div><span class="key">Strategy</span> {strategyId ?? '—'}</div>
			<div><span class="key">Path</span> <code>{strategyPath ?? '—'}</code></div>
		</div>

		{#if loading}
			<p class="muted">Scanning…</p>
		{:else if errorMsg}
			<p class="error">{errorMsg}</p>
		{:else if report}
			<div class="status {report.ok ? 'good' : 'bad'}">
				{report.ok ? '✓ Clean' : `✗ ${report.findings.length} finding(s)`}
				<span class="muted"
					>· {report.line_count} lines · {report.file_size_bytes} bytes</span
				>
			</div>

			{#if report.findings.length > 0}
				<ul class="findings">
					{#each report.findings as f}
						<li class={findingClass(f)}>
							<div class="finding-head">
								<span class="kind">{f.kind}</span>
								<span class="loc">L{f.lineno}:{f.col}</span>
							</div>
							<div class="msg">{f.message}</div>
							{#if f.node_repr}
								<pre class="node">{f.node_repr}</pre>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		{/if}

		<footer>
			<button type="button" class="primary" on:click={rescan} disabled={loading}>
				{loading ? 'Scanning…' : 'Re-scan'}
			</button>
			<button type="button" on:click={close}>Close</button>
		</footer>
	</aside>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: flex;
		justify-content: flex-end;
	}

	.backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.55);
	}

	.drawer {
		position: relative;
		width: min(560px, 100vw);
		height: 100%;
		background: #0d0d0d;
		border-left: 1px solid #2a2a2a;
		color: #e5e5e5;
		display: flex;
		flex-direction: column;
		padding: 1rem 1.25rem;
		gap: 0.75rem;
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	header h2 {
		margin: 0;
		font-size: 1rem;
		font-weight: 600;
	}

	.close {
		background: transparent;
		border: none;
		color: #aaa;
		font-size: 1.5rem;
		cursor: pointer;
		line-height: 1;
	}

	.meta {
		font-size: 0.8125rem;
		color: #aaa;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.meta .key {
		display: inline-block;
		min-width: 80px;
		color: #777;
		text-transform: uppercase;
		font-size: 0.6875rem;
		letter-spacing: 0.05em;
	}

	.meta code {
		font-family: monospace;
		font-size: 0.8125rem;
	}

	.status {
		font-size: 0.875rem;
		padding: 0.5rem 0.75rem;
		border-radius: 4px;
	}

	.status.good {
		color: #4ade80;
		background: rgba(74, 222, 128, 0.08);
	}

	.status.bad {
		color: #f87171;
		background: rgba(248, 113, 113, 0.08);
	}

	.muted {
		color: #777;
	}

	.error {
		color: #f87171;
		font-family: monospace;
		font-size: 0.8125rem;
	}

	.findings {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
	}

	.findings li {
		padding: 0.625rem 0.75rem;
		border-radius: 4px;
		background: #131313;
		border-left: 3px solid #444;
	}

	.findings li.bad {
		border-left-color: #f87171;
	}

	.findings li.warn {
		border-left-color: #fbbf24;
	}

	.finding-head {
		display: flex;
		justify-content: space-between;
		font-size: 0.75rem;
		margin-bottom: 0.25rem;
	}

	.finding-head .kind {
		color: #ccc;
		font-weight: 500;
		text-transform: lowercase;
	}

	.finding-head .loc {
		color: #888;
		font-family: monospace;
	}

	.msg {
		font-size: 0.8125rem;
		color: #ddd;
	}

	.node {
		margin: 0.375rem 0 0;
		padding: 0.375rem 0.5rem;
		background: #0a0a0a;
		font-size: 0.75rem;
		color: #aaa;
		border-radius: 3px;
		overflow-x: auto;
	}

	footer {
		margin-top: auto;
		display: flex;
		gap: 0.5rem;
	}

	footer button {
		padding: 0.375rem 0.875rem;
		font-size: 0.8125rem;
		background: #1a1a1a;
		border: 1px solid #2a2a2a;
		color: #ccc;
		border-radius: 4px;
		cursor: pointer;
	}

	footer button:hover {
		border-color: #4f8df7;
		color: #fff;
	}

	footer button.primary {
		background: #1f3a6e;
		border-color: #4f8df7;
		color: #fff;
	}

	footer button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
