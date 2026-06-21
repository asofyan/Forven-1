<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		getBot,
		getTemplate,
		createBot,
		updateBot,
		listTemplates,
		type BotConfig,
		type BotTemplate,
	} from '$lib/api';
	import { fetchApi } from '$lib/api/core';

	let loading = true;
	let saving = false;
	let error: string | null = null;
	let editId: string | null = null;
	let templates: BotTemplate[] = [];
	let activeTab: 'core' | 'trading' | 'advanced' = 'core';
	let showTemplateSelector = false;

	// Form state
	let name = 'Untitled Bot';
	let model = 'gpt-4.1-mini';
	let soul = '';
	let context = '';
	let strategy = '';
	let guardrails = '';
	let capitalAllocation = 100000;
	let maxPositionPct = 10;
	let maxConcurrentPositions = 5;
	let maxDrawdownPct = 3;
	let cooldownSeconds = 60;
	let reasoningVerbosity = 'standard';
	let assetMode: 'free_roam' | 'locked' = 'free_roam';
	let lockedPairsText = '';
	let webAllowlistText = '';
	let webRateLimit = 10;
	let maxLlmCallsPerDay = 200;
	let maxConsecutiveErrors = 5;

	function populateFromConfig(config: Partial<BotConfig> | Record<string, unknown>) {
		name = (config.name as string) || name;
		model = (config.model as string) || model;
		soul = (config.soul as string) || '';
		context = (config.context as string) || '';
		strategy = (config.strategy as string) || '';
		guardrails = (config.guardrails as string) || '';
		capitalAllocation = (config.capital_allocation as number) ?? capitalAllocation;
		maxPositionPct = (config.max_position_pct as number) ?? maxPositionPct;
		maxConcurrentPositions = (config.max_concurrent_positions as number) ?? maxConcurrentPositions;
		maxDrawdownPct = (config.max_drawdown_pct as number) ?? maxDrawdownPct;
		cooldownSeconds = (config.cooldown_seconds as number) ?? cooldownSeconds;
		reasoningVerbosity = (config.reasoning_verbosity as string) || 'standard';
		assetMode = ((config.asset_mode as string) || 'free_roam') as 'free_roam' | 'locked';
		const lp = config.locked_pairs;
		lockedPairsText = Array.isArray(lp) ? lp.join(', ') : '';
		const wa = config.web_allowlist;
		webAllowlistText = Array.isArray(wa) ? wa.join('\n') : '';
		webRateLimit = (config.web_rate_limit as number) ?? 10;
		maxLlmCallsPerDay = (config.max_llm_calls_per_day as number) ?? 200;
		maxConsecutiveErrors = (config.max_consecutive_errors as number) ?? 5;
	}

	async function loadTemplateById(templateId: string) {
		try {
			const template = await getTemplate(templateId);
			if (template?.config_snapshot) {
				populateFromConfig(template.config_snapshot);
				name = template.name;
			}
		} catch {}
	}

	async function handleSave() {
		saving = true;
		error = null;
		try {
			const config: Record<string, unknown> = {
				name,
				model,
				soul: soul || null,
				context: context || null,
				strategy: strategy || null,
				guardrails: guardrails || null,
				capital_allocation: capitalAllocation,
				max_position_pct: maxPositionPct,
				max_concurrent_positions: maxConcurrentPositions,
				max_drawdown_pct: maxDrawdownPct,
				cooldown_seconds: cooldownSeconds,
				reasoning_verbosity: reasoningVerbosity,
				asset_mode: assetMode,
				locked_pairs: assetMode === 'locked' ? lockedPairsText.split(',').map((s) => s.trim()).filter(Boolean) : null,
				web_allowlist: webAllowlistText.trim() ? webAllowlistText.split('\n').map((s) => s.trim()).filter(Boolean) : null,
				web_rate_limit: webRateLimit,
				max_llm_calls_per_day: maxLlmCallsPerDay,
				max_consecutive_errors: maxConsecutiveErrors,
			};

			if (editId) {
				await updateBot(editId, config as Partial<BotConfig>);
			} else {
				await createBot(config as Partial<BotConfig>);
			}
			goto('/bot-factory');
		} catch (e: any) {
			error = e.message || 'Failed to save';
		} finally {
			saving = false;
		}
	}

	onMount(async () => {
		try {
			templates = await listTemplates();
			const params = $page.url.searchParams;
			editId = params.get('id');
			const templateId = params.get('template');

			const strategyId = params.get('strategy');

			if (editId) {
				const bot = await getBot(editId);
				if (bot) populateFromConfig(bot);
			} else if (strategyId) {
				try {
					const result: { config: Record<string, unknown> } = await fetchApi(`/bot-factory/from-strategy/${strategyId}`);
					if (result?.config) populateFromConfig(result.config);
				} catch (e: any) {
					error = `Failed to load strategy: ${e.message}`;
				}
			} else if (templateId) {
				await loadTemplateById(templateId);
			} else {
				showTemplateSelector = true;
			}
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>{editId ? 'Edit Bot' : 'Create Bot'} | Bot Factory | Forven</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-6">
	<!-- Header -->
	<div class="mb-6 flex items-center justify-between">
		<div>
			<button on:click={() => goto('/bot-factory')} class="mb-2 text-sm text-gray-500 hover:text-gray-300">&larr; Back to Bot Factory</button>
			<h1 class="text-xl font-bold text-white">{editId ? 'Edit Bot' : 'Create New Bot'}</h1>
		</div>
		<button
			on:click={handleSave}
			disabled={saving || !name.trim()}
			class="rounded-lg bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:opacity-50"
		>
			{saving ? 'Saving...' : editId ? 'Save Changes' : 'Create Bot'}
		</button>
	</div>

	{#if error}
		<div class="mb-4 rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 text-sm text-rose-300">{error}</div>
	{/if}

	{#if loading}
		<div class="py-20 text-center text-gray-500">Loading...</div>
	{:else}
		<!-- Template selector (only on create, initially) -->
		{#if showTemplateSelector && !editId && templates.length > 0}
			<div class="mb-6 rounded-xl border border-[#2a2a2a] bg-[#1a1a1a] p-5">
				<h2 class="mb-3 text-sm font-semibold text-gray-300">Start from a template</h2>
				<div class="grid grid-cols-2 gap-3">
					{#each templates as template}
						<button
							on:click={() => { populateFromConfig(template.config_snapshot); name = template.name; showTemplateSelector = false; }}
							class="rounded-lg border border-[#333] bg-[#121212] p-3 text-left transition hover:border-sky-500/30"
						>
							<div class="text-sm font-medium text-white">{template.name}</div>
							<div class="mt-0.5 text-xs text-gray-500">{template.description}</div>
						</button>
					{/each}
				</div>
				<button on:click={() => (showTemplateSelector = false)} class="mt-3 text-xs text-gray-500 hover:text-gray-300">
					or start from scratch &rarr;
				</button>
			</div>
		{/if}

		<!-- Tabs -->
		<div class="mb-4 flex gap-1 rounded-lg border border-[#2a2a2a] bg-[#121212] p-1">
			{#each [['core', 'Core'], ['trading', 'Trading'], ['advanced', 'Advanced']] as [key, label]}
				<button
					on:click={() => (activeTab = key as typeof activeTab)}
					class="flex-1 rounded-md px-3 py-1.5 text-sm transition {activeTab === key ? 'bg-[#2a2a2a] text-white font-medium' : 'text-gray-500 hover:text-gray-300'}"
				>
					{label}
				</button>
			{/each}
		</div>

		<!-- Tab content -->
		<div class="rounded-xl border border-[#2a2a2a] bg-[#1a1a1a] p-6">
			{#if activeTab === 'core'}
				<div class="space-y-4">
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="name" class="mb-1 block text-xs font-medium text-gray-400">Name</label>
							<input id="name" bind:value={name} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="model" class="mb-1 block text-xs font-medium text-gray-400">Model</label>
							<select id="model" bind:value={model} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white">
								<option value="gpt-4.1-mini">GPT-4.1 Mini</option>
								<option value="gpt-4.1">GPT-4.1</option>
								<option value="gpt-5.4-mini">GPT-5.4 Mini</option>
								<option value="gpt-5.4">GPT-5.4</option>
								<option value="minimax-m2.7">Minimax M2.7</option>
							</select>
						</div>
					</div>
					<div>
						<label for="soul" class="mb-1 block text-xs font-medium text-gray-400">Soul <span class="text-gray-600">— personality, temperament, decision style</span></label>
						<textarea id="soul" bind:value={soul} rows="4" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" placeholder="You are an aggressive momentum trader who thrives on volatility..."></textarea>
					</div>
					<div>
						<label for="strategy" class="mb-1 block text-xs font-medium text-gray-400">Strategy <span class="text-gray-600">— trading approach, broad or narrow</span></label>
						<textarea id="strategy" bind:value={strategy} rows="4" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" placeholder="Trade momentum breakouts on high-volume assets..."></textarea>
					</div>
					<div>
						<label for="context" class="mb-1 block text-xs font-medium text-gray-400">Context <span class="text-gray-600">— seed knowledge, research notes, market thesis</span></label>
						<textarea id="context" bind:value={context} rows="3" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" placeholder="BTC tends to correlate with macro risk-on sentiment..."></textarea>
					</div>
					<div>
						<label for="guardrails" class="mb-1 block text-xs font-medium text-gray-400">Guardrails <span class="text-gray-600">— behavioral rules (best-effort, LLM-interpreted)</span></label>
						<textarea id="guardrails" bind:value={guardrails} rows="3" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" placeholder="Never hold a position for more than 2 hours..."></textarea>
					</div>
				</div>
			{:else if activeTab === 'trading'}
				<div class="space-y-4">
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="capital" class="mb-1 block text-xs font-medium text-gray-400">Capital Allocation ($)</label>
							<input id="capital" type="number" bind:value={capitalAllocation} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="maxPos" class="mb-1 block text-xs font-medium text-gray-400">Max Position Size (%)</label>
							<input id="maxPos" type="number" bind:value={maxPositionPct} step="0.5" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="maxConcurrent" class="mb-1 block text-xs font-medium text-gray-400">Max Concurrent Positions</label>
							<input id="maxConcurrent" type="number" bind:value={maxConcurrentPositions} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="maxDrawdown" class="mb-1 block text-xs font-medium text-gray-400">Max Drawdown (%)</label>
							<input id="maxDrawdown" type="number" bind:value={maxDrawdownPct} step="0.5" class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="cooldown" class="mb-1 block text-xs font-medium text-gray-400">Cooldown (seconds)</label>
							<input id="cooldown" type="number" bind:value={cooldownSeconds} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="verbosity" class="mb-1 block text-xs font-medium text-gray-400">Reasoning Verbosity</label>
							<select id="verbosity" bind:value={reasoningVerbosity} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white">
								<option value="minimal">Minimal</option>
								<option value="standard">Standard</option>
								<option value="verbose">Verbose</option>
							</select>
						</div>
					</div>

					<div>
						<label class="mb-1 block text-xs font-medium text-gray-400">Asset Mode</label>
						<div class="flex gap-2">
							<button
								on:click={() => (assetMode = 'free_roam')}
								class="rounded-lg px-4 py-2 text-sm {assetMode === 'free_roam' ? 'bg-sky-600/20 border border-sky-500/30 text-sky-300' : 'border border-[#333] bg-[#121212] text-gray-400'}"
							>Free Roam</button>
							<button
								on:click={() => (assetMode = 'locked')}
								class="rounded-lg px-4 py-2 text-sm {assetMode === 'locked' ? 'bg-sky-600/20 border border-sky-500/30 text-sky-300' : 'border border-[#333] bg-[#121212] text-gray-400'}"
							>Locked Pairs</button>
						</div>
					</div>

					{#if assetMode === 'locked'}
						<div>
							<label for="pairs" class="mb-1 block text-xs font-medium text-gray-400">Locked Pairs (comma-separated)</label>
							<input id="pairs" bind:value={lockedPairsText} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" placeholder="BTC/USDT, ETH/USDT, SOL/USDT" />
						</div>
					{/if}
				</div>
			{:else if activeTab === 'advanced'}
				<div class="space-y-4">
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="llmCap" class="mb-1 block text-xs font-medium text-gray-400">Daily LLM Call Cap</label>
							<input id="llmCap" type="number" bind:value={maxLlmCallsPerDay} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
						<div>
							<label for="maxErrors" class="mb-1 block text-xs font-medium text-gray-400">Circuit Breaker (max errors)</label>
							<input id="maxErrors" type="number" bind:value={maxConsecutiveErrors} class="w-full rounded-lg border border-[#333] bg-[#121212] px-3 py-2 text-sm text-white" />
						</div>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
