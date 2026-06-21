<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		listSandboxRuns,
		killSandboxRun,
		type SandboxRunRow
	} from '$lib/api/sandbox';
	import { fetchApi } from '$lib/api/core';

	type DiagnosticsCheck = {
		name: string;
		status: 'pass' | 'warn' | 'fail';
		summary: string;
		detail: Record<string, unknown>;
	};

	type DiagnosticsSnapshot = {
		generated_at: string;
		overall: string;
		checks: DiagnosticsCheck[];
	};

	let rows: SandboxRunRow[] = [];
	let total = 0;
	let loading = true;
	let errorMsg: string | null = null;
	let sandboxEnabled = true;
	let sandboxDetail: Record<string, unknown> | null = null;
	let pollHandle: ReturnType<typeof setInterval> | null = null;
	let killing: Record<number, boolean> = {};
	const POLL_MS = 3000;

	async function loadSnapshot() {
		try {
			const snap = await fetchApi<DiagnosticsSnapshot>('/diagnostics/snapshot');
			const sandboxCheck = snap.checks.find((c) => c.name === 'sandbox_status');
			if (sandboxCheck) {
				sandboxEnabled = Boolean(sandboxCheck.detail?.enabled);
				sandboxDetail = sandboxCheck.detail;
			}
		} catch {
			// Diagnostics fetch failure shouldn't block the page — assume enabled.
			sandboxEnabled = true;
		}
	}

	async function loadRuns() {
		try {
			const resp = await listSandboxRuns({ limit: 100 });
			rows = resp.rows;
			total = resp.total;
			errorMsg = null;
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			// 503 is the "sandbox disabled" signal — render empty state, not an error.
			if (msg.includes('503') || msg.toLowerCase().includes('sandbox_disabled')) {
				sandboxEnabled = false;
				rows = [];
				total = 0;
				errorMsg = null;
			} else {
				errorMsg = msg;
			}
		}
	}

	async function refresh() {
		// Caps (mem/cpu/wall) are read once on mount — they don't change at
		// runtime — so the 3s poll only hits the lightweight /sandbox/runs.
		if (sandboxEnabled) {
			await loadRuns();
		}
	}

	async function killRun(id: number) {
		if (killing[id]) return;
		killing = { ...killing, [id]: true };
		try {
			await killSandboxRun(id);
			await loadRuns();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : String(err);
		} finally {
			killing = { ...killing, [id]: false };
		}
	}

	function startPolling() {
		if (pollHandle) return;
		pollHandle = setInterval(refresh, POLL_MS);
	}

	function stopPolling() {
		if (pollHandle) {
			clearInterval(pollHandle);
			pollHandle = null;
		}
	}

	function handleVisibility() {
		// Back off polling while the tab is hidden — Forven only runs while the
		// Tauri window is open, so there's nothing to watch when backgrounded.
		if (document.hidden) {
			stopPolling();
		} else {
			void refresh();
			startPolling();
		}
	}

	onMount(async () => {
		loading = true;
		await loadSnapshot();
		await refresh();
		loading = false;
		startPolling();
		document.addEventListener('visibilitychange', handleVisibility);
	});

	onDestroy(() => {
		stopPolling();
		if (typeof document !== 'undefined') {
			document.removeEventListener('visibilitychange', handleVisibility);
		}
	});

	function fmtSeconds(v: number | null): string {
		if (v === null || v === undefined) return '—';
		return `${v.toFixed(2)}s`;
	}

	function fmtMb(v: number | null): string {
		if (v === null || v === undefined) return '—';
		return `${v.toFixed(0)} MB`;
	}

	function parseTs(v: string | null): Date | null {
		if (!v) return null;
		// SQLite "YYYY-MM-DD HH:MM:SS" has no zone — treat as UTC to match the
		// backend, which stores wall clock in UTC.
		const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(v)
			? v
			: `${v.replace(' ', 'T')}Z`;
		const d = new Date(normalized);
		return Number.isNaN(d.getTime()) ? null : d;
	}

	function fmtTimestamp(v: string | null): string {
		const d = parseTs(v);
		if (!d) return v ?? '—';
		return d.toLocaleString();
	}

	function fmtAge(v: string | null): string {
		const d = parseTs(v);
		if (!d) return '';
		const secs = Math.max(0, (Date.now() - d.getTime()) / 1000);
		if (secs < 60) return `${Math.round(secs)}s ago`;
		const mins = secs / 60;
		if (mins < 60) return `${Math.round(mins)}m ago`;
		const hours = mins / 60;
		if (hours < 24) return `${Math.round(hours)}h ago`;
		return `${Math.round(hours / 24)}d ago`;
	}

	function statusLabel(row: SandboxRunRow): string {
		if (row.kind === 'scan') return row.error ? 'Blocked (AST)' : 'Scanned';
		if (row.timed_out) return 'Timed out';
		if (row.exit_code === 0) return 'OK';
		return `Exit ${row.exit_code ?? '—'}`;
	}

	function statusClass(row: SandboxRunRow): string {
		if (row.kind === 'scan' && row.error) return 'bad';
		if (row.timed_out) return 'bad';
		if (row.exit_code === 0) return 'good';
		return 'bad';
	}

	$: activeRows = rows.filter((r) => r.ended_at === null);
	$: completedRows = rows.filter((r) => r.ended_at !== null);
</script>

<svelte:head>
	<title>Sandbox — Forven</title>
</svelte:head>

<div class="sandbox-page">
	<header class="sandbox-header">
		<div>
			<h1>Sandbox</h1>
			<p class="subtitle">Subprocess isolation for AI-generated strategies</p>
		</div>
		<div class="badges">
			{#if sandboxDetail}
				<span class="badge"
					>Mem cap: {sandboxDetail.mem_mb ?? '—'} MB</span
				>
				<span class="badge">CPU: {sandboxDetail.cpu_s ?? '—'}s</span>
				<span class="badge">Wall: {sandboxDetail.wall_s ?? '—'}s</span>
			{/if}
		</div>
	</header>

	{#if loading}
		<p class="muted">Loading…</p>
	{:else if !sandboxEnabled}
		<section class="empty">
			<h2>Sandbox is disabled.</h2>
			<p>Enable it in <a href="/settings#sandbox">Settings → Sandbox</a>.</p>
			<p class="hint">
				Without the sandbox, AI-generated strategies execute in-process — they
				can ``import os``, write to your filesystem, and read your environment.
			</p>
		</section>
	{:else if errorMsg}
		<section class="empty">
			<h2>Couldn't load sandbox runs.</h2>
			<p class="error">{errorMsg}</p>
		</section>
	{:else}
		<section class="grid">
			<div class="panel">
				<h2>Active runs ({activeRows.length})</h2>
				{#if activeRows.length === 0}
					<p class="muted">No runs in flight.</p>
				{:else}
					<table>
						<thead>
							<tr>
								<th>ID</th>
								<th>Strategy</th>
								<th>Started</th>
								<th>Wall</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each activeRows as row (row.id)}
								<tr>
									<td>#{row.id}</td>
									<td>{row.strategy_id ?? '—'}</td>
									<td title={fmtTimestamp(row.started_at)}>{fmtAge(row.started_at)}</td>
									<td>{fmtSeconds(row.wall_seconds)}</td>
									<td>
										<button
											class="kill"
											disabled={killing[row.id]}
											on:click={() => killRun(row.id)}
										>
											{killing[row.id] ? 'Killing…' : 'Kill'}
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>

			<div class="panel">
				<h2>Recent runs (last {completedRows.length} of {total})</h2>
				{#if completedRows.length === 0}
					<p class="muted">No completed runs yet.</p>
				{:else}
					<table>
						<thead>
							<tr>
								<th>ID</th>
								<th>Strategy</th>
								<th>Kind</th>
								<th>Status</th>
								<th>Wall</th>
								<th>Mem peak</th>
								<th>Started</th>
							</tr>
						</thead>
						<tbody>
							{#each completedRows as row (row.id)}
								<tr>
									<td>#{row.id}</td>
									<td>{row.strategy_id ?? '—'}</td>
									<td>{row.kind}</td>
									<td><span class="status {statusClass(row)}">{statusLabel(row)}</span></td>
									<td>{fmtSeconds(row.wall_seconds)}</td>
									<td>{fmtMb(row.memory_peak_mb)}</td>
									<td title={fmtTimestamp(row.started_at)}>{fmtAge(row.started_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>

			<div class="panel">
				<h2>Recent security events</h2>
				{#if completedRows.filter((r) => r.error).length === 0}
					<p class="muted">No security events recorded.</p>
				{:else}
					<ul class="events">
						{#each completedRows.filter((r) => r.error).slice(0, 25) as row (row.id)}
							<li>
								<span class="badge bad">{row.error}</span>
								<span class="muted">run #{row.id} — {row.strategy_id ?? '—'}</span>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</section>
	{/if}
</div>

<style>
	.sandbox-page {
		padding: 1.5rem 2rem 3rem;
		color: #e5e5e5;
		max-width: 1280px;
		margin: 0 auto;
	}

	.sandbox-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		margin-bottom: 1.5rem;
	}

	.sandbox-header h1 {
		font-size: 1.75rem;
		font-weight: 600;
		margin: 0;
	}

	.subtitle {
		color: #888;
		margin: 0.25rem 0 0;
		font-size: 0.875rem;
	}

	.badges {
		display: flex;
		gap: 0.5rem;
	}

	.badge {
		display: inline-block;
		padding: 0.125rem 0.5rem;
		font-size: 0.75rem;
		background: #1a1a1a;
		border: 1px solid #2a2a2a;
		border-radius: 4px;
		color: #ccc;
	}

	.badge.bad {
		color: #f87171;
		border-color: #5a1f1f;
	}

	.empty {
		padding: 2rem;
		border: 1px dashed #333;
		border-radius: 6px;
		text-align: center;
	}

	.empty h2 {
		font-size: 1rem;
		font-weight: 500;
		margin: 0 0 0.5rem;
	}

	.empty .hint {
		color: #777;
		font-size: 0.8125rem;
		margin-top: 0.5rem;
	}

	.error {
		color: #f87171;
		font-family: monospace;
		font-size: 0.8125rem;
	}

	.grid {
		display: grid;
		gap: 1.5rem;
	}

	.panel {
		background: #0d0d0d;
		border: 1px solid #222;
		border-radius: 6px;
		padding: 1rem;
	}

	.panel h2 {
		font-size: 0.875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #aaa;
		margin: 0 0 0.75rem;
	}

	.muted {
		color: #777;
		font-size: 0.875rem;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8125rem;
	}

	thead th {
		text-align: left;
		padding: 0.375rem 0.5rem;
		border-bottom: 1px solid #2a2a2a;
		color: #888;
		font-weight: 500;
	}

	tbody td {
		padding: 0.375rem 0.5rem;
		border-bottom: 1px solid #181818;
	}

	tbody tr:hover {
		background: #131313;
	}

	a {
		color: #6aa6ff;
		text-decoration: none;
	}

	a:hover {
		text-decoration: underline;
	}

	.status {
		display: inline-block;
		font-size: 0.75rem;
		padding: 0.125rem 0.375rem;
		border-radius: 3px;
		background: #1a1a1a;
	}

	.status.good {
		color: #4ade80;
	}

	.status.bad {
		color: #f87171;
	}

	.kill {
		font-size: 0.75rem;
		padding: 0.125rem 0.5rem;
		background: #1a1010;
		border: 1px solid #5a1f1f;
		border-radius: 3px;
		color: #f87171;
		cursor: pointer;
	}

	.kill:hover:not(:disabled) {
		background: #2a1414;
	}

	.kill:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.events {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
		font-size: 0.8125rem;
	}
</style>
