<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import {
		createHypothesisFromUrl,
		previewHypothesisFromUrl,
		type UrlPreviewSuccess,
	} from '$lib/api';

	export let open = false;

	const dispatch = createEventDispatcher<{ created: { id: string }; close: void }>();

	type Step = 'input' | 'preview' | 'submitting';
	let step: Step = 'input';
	let url = '';
	let title = '';
	let marketThesis = '';
	let mechanism = '';
	let claimedEdge = '';
	let preview: UrlPreviewSuccess | null = null;
	let errorMsg: string | null = null;
	let previewing = false;

	$: canPreview = url.trim().length > 0 && !previewing && step !== 'submitting';

	function close(): void {
		step = 'input';
		url = '';
		title = '';
		marketThesis = '';
		mechanism = '';
		claimedEdge = '';
		preview = null;
		errorMsg = null;
		previewing = false;
		dispatch('close');
	}

	async function handlePreview(): Promise<void> {
		errorMsg = null;
		previewing = true;
		try {
			const res = await previewHypothesisFromUrl(url.trim());
			if (!res.ok) {
				errorMsg = `${res.error_code}: ${res.error}`;
				return;
			}
			preview = res;
			title = res.title || '';
			step = 'preview';
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : 'Preview failed.';
		} finally {
			previewing = false;
		}
	}

	async function handleCreate(): Promise<void> {
		if (!preview) return;
		errorMsg = null;
		step = 'submitting';
		try {
			const res = await createHypothesisFromUrl({
				url: preview.url,
				title: title.trim() || undefined,
				market_thesis: marketThesis.trim() || undefined,
				mechanism: mechanism.trim() || undefined,
				claimed_edge: claimedEdge.trim() || undefined,
			});
			if (!res.ok) {
				errorMsg = `${res.error_code}: ${res.error}`;
				step = 'preview';
				return;
			}
			dispatch('created', { id: res.hypothesis.id });
			close();
		} catch (err) {
			errorMsg = err instanceof Error ? err.message : 'Create failed.';
			step = 'preview';
		}
	}

	function backToInput(): void {
		step = 'input';
		preview = null;
		errorMsg = null;
	}

	function onBackdropClick(event: MouseEvent): void {
		if (event.target === event.currentTarget) close();
	}
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-start justify-center bg-black/70 px-4 py-10 backdrop-blur-sm"
		on:click={onBackdropClick}
		on:keydown={(e) => e.key === 'Escape' && close()}
		role="presentation"
	>
		<div
			class="w-full max-w-2xl border border-[#333] bg-[#0b0b0b] text-white shadow-2xl"
			role="dialog"
			aria-modal="true"
			aria-labelledby="url-ingest-title"
		>
			<header class="flex items-center justify-between border-b border-[#222] px-5 py-4">
				<h2 id="url-ingest-title" class="text-sm font-semibold uppercase tracking-[0.2em] text-gray-200">
					Add crucible from URL
				</h2>
				<button
					type="button"
					class="text-gray-500 hover:text-white"
					aria-label="Close"
					on:click={close}
				>
					✕
				</button>
			</header>

			<div class="space-y-4 px-5 py-5">
				{#if errorMsg}
					<div class="border border-red-700 bg-red-950/40 px-3 py-2 text-xs text-red-200">
						{errorMsg}
					</div>
				{/if}

				{#if step === 'input'}
					<label class="block text-xs uppercase tracking-[0.18em] text-gray-400">
						URL
						<input
							bind:value={url}
							type="url"
							placeholder="https://youtube.com/... or reddit/github/blog URL"
							class="mt-2 w-full border border-[#2a2a2a] bg-[#141414] px-3 py-2 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-400"
							autocomplete="off"
						/>
					</label>
					<p class="text-[11px] text-gray-500">
						We auto-detect YouTube, Reddit, GitHub, known forums, or fall back to article extraction.
					</p>
					<div class="flex justify-end gap-2 pt-2">
						<button
							type="button"
							class="border border-[#2d2d2d] bg-[#141414] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-gray-400 hover:border-gray-400 hover:text-white"
							on:click={close}
						>
							Cancel
						</button>
						<button
							type="button"
							class="border border-cyan-500/60 bg-cyan-950/40 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-100 hover:bg-cyan-900/60 disabled:opacity-50"
							on:click={handlePreview}
							disabled={!canPreview}
						>
							{previewing ? 'Fetching…' : 'Preview'}
						</button>
					</div>
				{/if}

				{#if step === 'preview' && preview}
					<div class="grid grid-cols-3 gap-3 text-[11px] text-gray-400">
						<div class="border border-[#262626] bg-[#111] px-3 py-2">
							<div class="uppercase tracking-[0.18em] text-gray-500">Source</div>
							<div class="mt-1 text-sm font-semibold text-white">{preview.source_type}</div>
						</div>
						<div class="border border-[#262626] bg-[#111] px-3 py-2">
							<div class="uppercase tracking-[0.18em] text-gray-500">Extracted bytes</div>
							<div class="mt-1 text-sm font-semibold text-white">{preview.content_bytes.toLocaleString()}</div>
						</div>
						<div class="border border-[#262626] bg-[#111] px-3 py-2">
							<div class="uppercase tracking-[0.18em] text-gray-500">Preview clipped?</div>
							<div class="mt-1 text-sm font-semibold text-white">{preview.preview_truncated ? 'Yes' : 'No'}</div>
						</div>
					</div>

					<label class="block text-xs uppercase tracking-[0.18em] text-gray-400">
						Title
						<input
							bind:value={title}
							placeholder="Auto-detected from source; you can override"
							class="mt-2 w-full border border-[#2a2a2a] bg-[#141414] px-3 py-2 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-400"
						/>
					</label>

					<label class="block text-xs uppercase tracking-[0.18em] text-gray-400">
						Market thesis (optional)
						<textarea
							bind:value={marketThesis}
							rows="2"
							placeholder="One-line thesis the agent should refine, or leave blank."
							class="mt-2 w-full border border-[#2a2a2a] bg-[#141414] px-3 py-2 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-400"
						></textarea>
					</label>

					<label class="block text-xs uppercase tracking-[0.18em] text-gray-400">
						Mechanism (optional)
						<textarea
							bind:value={mechanism}
							rows="2"
							placeholder="How the edge is captured. Leave blank to let the agent populate."
							class="mt-2 w-full border border-[#2a2a2a] bg-[#141414] px-3 py-2 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-400"
						></textarea>
					</label>

					<label class="block text-xs uppercase tracking-[0.18em] text-gray-400">
						Claimed edge (optional)
						<input
							bind:value={claimedEdge}
							placeholder="e.g., funding-rate mean reversion on BTC perps"
							class="mt-2 w-full border border-[#2a2a2a] bg-[#141414] px-3 py-2 text-sm text-white outline-none placeholder:text-gray-600 focus:border-cyan-400"
						/>
					</label>

					<details class="text-xs text-gray-400">
						<summary class="cursor-pointer select-none py-1 text-gray-500 hover:text-gray-200">
							Content preview ({Math.min(preview.content_preview.length, preview.content_bytes).toLocaleString()} chars)
						</summary>
						<pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap border border-[#222] bg-black/40 p-3 text-[11px] text-gray-300">{preview.content_preview || '(no content extracted)'}</pre>
					</details>

					<div class="flex justify-end gap-2 pt-2">
						<button
							type="button"
							class="border border-[#2d2d2d] bg-[#141414] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-gray-400 hover:border-gray-400 hover:text-white"
							on:click={backToInput}
						>
							Back
						</button>
						<button
							type="button"
							class="border border-green-600/60 bg-green-950/40 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-green-100 hover:bg-green-900/60"
							on:click={handleCreate}
						>
							Create crucible
						</button>
					</div>
				{/if}

				{#if step === 'submitting'}
					<div class="flex items-center justify-center py-6 text-xs uppercase tracking-[0.18em] text-gray-400">
						Creating crucible…
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
