<script lang="ts">
	/**
	 * Settings → Sandbox (P2-T15)
	 *
	 * Surface the four flat sandbox keys (sandbox_enabled / mem_mb / cpu_s /
	 * wall_s) backed by SETTINGS_MANIFEST + the standard dirty/save shell.
	 * Adds a "Test sandbox" button that calls POST /api/sandbox/test so the
	 * operator can prove isolation works after flipping the master switch.
	 */
	import { onMount } from 'svelte';
	import {
		SETTINGS_MANIFEST,
		SETTINGS_SUBSECTIONS,
		type SettingsEntry,
	} from '$lib/settings/manifest';
	import SettingsSubsection from '$lib/components/settings/primitives/SettingsSubsection.svelte';
	import SettingsFieldRow from '$lib/components/settings/primitives/SettingsFieldRow.svelte';
	import { originalValues, pendingValues } from '$lib/settings/dirty';
	import { testSandbox, type SandboxTestResponse } from '$lib/api/sandbox';

	export let settings: Record<string, unknown>;
	export let currentValues: Record<string, unknown> = {};
	export let variant: 'default' | 'wizard' = 'default';
	export let visibleSubsections: string[] | null = null;

	const AREA = 'sandbox' as const;

	const allSubs = SETTINGS_SUBSECTIONS.filter((s) => s.area === AREA);
	$: subs = variant === 'wizard' && visibleSubsections
		? allSubs.filter((s) => visibleSubsections!.includes(s.id))
		: allSubs;
	const areaEntries = SETTINGS_MANIFEST.filter((e) => e.area === AREA);
	$: entriesBySub = Object.fromEntries(
		subs.map((s) => [s.id, areaEntries.filter((e) => e.subsection === s.id)]),
	) as Record<string, SettingsEntry[]>;

	function readByPath(obj: unknown, path: string): unknown {
		return path
			.split('.')
			.reduce<any>((cursor, key) => (cursor == null ? undefined : cursor[key]), obj);
	}

	function initialValue(entry: SettingsEntry): unknown {
		const v = readByPath(settings, entry.backendPath);
		return v === undefined ? entry.default : v;
	}

	onMount(() => {
		const origSeed: Record<string, unknown> = {};
		for (const e of areaEntries) origSeed[e.id] = initialValue(e);
		originalValues.update((o) => ({ ...o, ...origSeed }));
	});

	$: {
		const originals: Record<string, unknown> = {};
		for (const e of areaEntries) originals[e.id] = initialValue(e);
		const pend = $pendingValues;
		const areaPending: Record<string, unknown> = {};
		for (const e of areaEntries) {
			if (e.id in pend) areaPending[e.id] = pend[e.id];
		}
		currentValues = { ...currentValues, ...originals, ...areaPending };
	}

	function displayValue(entry: SettingsEntry): unknown {
		const pend = $pendingValues;
		if (entry.id in pend) return pend[entry.id];
		return initialValue(entry);
	}

	$: enabled = Boolean(displayValue(areaEntries.find((e) => e.id === 'sandbox.sandbox_enabled')!));

	let testBusy = false;
	let testResult: SandboxTestResponse | null = null;
	let testError: string | null = null;

	async function runTest() {
		testBusy = true;
		testError = null;
		testResult = null;
		try {
			testResult = await testSandbox();
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			// 503 → sandbox is disabled. Surface a friendlier message than the raw envelope.
			if (msg.includes('503') || msg.toLowerCase().includes('sandbox_disabled')) {
				testError = 'Sandbox is disabled — flip the master switch on and save before testing.';
			} else {
				testError = msg;
			}
		} finally {
			testBusy = false;
		}
	}
</script>

<div class="space-y-6">
	{#each subs as sub (sub.id)}
		{@const entries = entriesBySub[sub.id] ?? []}
		{@const usedBy = [...new Set(entries.flatMap((e) => e.usedBy))]}
		<SettingsSubsection
			label={sub.label}
			description={sub.description ?? ''}
			deepLinkTo={sub.deepLinkTo}
			{usedBy}
		>
			{#each entries as entry (entry.id)}
				<SettingsFieldRow
					id={entry.id}
					label={entry.label}
					description={entry.description}
					unit={entry.unit}
					defaultValue={entry.default}
					value={displayValue(entry)}
					type={entry.type}
					options={entry.options ?? []}
				/>
			{/each}
		</SettingsSubsection>
	{/each}

	<section class="border border-gray-800 rounded-lg bg-black p-6 space-y-3">
		<header class="border-b border-gray-800 pb-2">
			<h2 class="text-lg font-semibold text-white">Test sandbox</h2>
			<p class="text-xs text-gray-500 mt-1">
				Spawns a hello-world subprocess under the current caps and reports whether
				isolation is wired up. Save your changes first — this hits the live config.
			</p>
		</header>

		{#if !enabled}
			<p class="text-xs text-amber-400">
				Sandbox is currently disabled. Flip the master switch on and save before running the
				test.
			</p>
		{/if}

		<button
			type="button"
			on:click={runTest}
			disabled={testBusy}
			class="text-sm px-3 py-1.5 rounded border border-gray-700 text-gray-100 hover:border-blue-500 hover:text-white disabled:opacity-50"
		>
			{testBusy ? 'Running…' : 'Run hello-world test'}
		</button>

		{#if testError}
			<p class="text-xs text-red-400 font-mono" role="alert">{testError}</p>
		{/if}

		{#if testResult}
			<div
				class="border rounded px-3 py-2 text-xs {testResult.ok
					? 'border-emerald-900 bg-emerald-950/20 text-emerald-200'
					: 'border-red-900 bg-red-950/20 text-red-200'}"
			>
				<div>
					{testResult.ok ? '✓ Sandbox OK' : '✗ Sandbox failed'}
					· exit {testResult.exit_code}
					· wall {testResult.wall_seconds.toFixed(2)}s
					{#if testResult.memory_peak_mb !== null}
						· peak {testResult.memory_peak_mb} MB
					{/if}
					{#if testResult.timed_out}
						· <span class="text-amber-300">timed out</span>
					{/if}
				</div>
				{#if testResult.stderr_text}
					<pre class="mt-1 whitespace-pre-wrap text-[11px] text-gray-400">{testResult.stderr_text}</pre>
				{/if}
				{#if testResult.stdout_payload}
					<pre class="mt-1 whitespace-pre-wrap text-[11px] text-gray-400">{JSON.stringify(testResult.stdout_payload, null, 2)}</pre>
				{/if}
			</div>
		{/if}
	</section>
</div>
