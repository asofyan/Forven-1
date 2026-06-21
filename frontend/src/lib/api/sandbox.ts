/**
 * Sandbox API client (P2-T11) — backs the /sandbox page (P2-T12),
 * the strategy badge + AST findings drawer (P2-T13), the AI Dropzone
 * AST gate (P2-T14), and the Settings → Sandbox panel (P2-T15).
 *
 * Contract is fixed by ``forven/routers/sandbox.py``. Keep these
 * interfaces in lockstep with the backend payload shapes.
 */

import { fetchApi } from './core';

// --------------------------------------------------------------------------- //
// Types                                                                       //
// --------------------------------------------------------------------------- //

export type SandboxRunKind = 'scan' | 'run';

export interface SandboxRunRow {
	id: number;
	strategy_id: string | null;
	kind: SandboxRunKind;
	child_pid: number | null;
	started_at: string;
	ended_at: string | null;
	exit_code: number | null;
	memory_peak_mb: number | null;
	cpu_seconds: number | null;
	wall_seconds: number | null;
	timed_out: number; // SQLite stores 0/1
	error: string | null;
	created_at: string;
}

export type AstFindingKind =
	| 'forbidden_import'
	| 'dangerous_call'
	| 'dynamic_attribute'
	| 'oversize_file'
	| 'too_many_lines'
	| 'syntax_error';

export interface AstFinding {
	kind: AstFindingKind;
	lineno: number;
	col: number;
	message: string;
	node_repr: string;
}

export interface SandboxRunDetail extends SandboxRunRow {
	ast_findings_json: string | null;
	security_events_json: string | null;
	ast_findings: AstFinding[] | null;
	security_events: Record<string, unknown>[] | null;
	active: boolean;
}

export interface SandboxListResponse {
	rows: SandboxRunRow[];
	total: number;
	limit: number;
	offset: number;
}

export interface AstReport {
	ok: boolean;
	findings: AstFinding[];
	file_size_bytes: number;
	line_count: number;
	row_id: number | null;
}

export interface SandboxTestResponse {
	ok: boolean;
	exit_code: number;
	timed_out: boolean;
	wall_seconds: number;
	memory_peak_mb: number | null;
	stdout_payload: Record<string, unknown> | null;
	stderr_text: string;
}

export interface SandboxKillResponse {
	ok: boolean;
	run_id: number;
	killed: boolean;
}

// --------------------------------------------------------------------------- //
// Functions                                                                   //
// --------------------------------------------------------------------------- //

export interface ListSandboxRunsOptions {
	strategyId?: string;
	kind?: SandboxRunKind;
	timedOut?: boolean;
	limit?: number;
	offset?: number;
}

export async function listSandboxRuns(
	opts: ListSandboxRunsOptions = {}
): Promise<SandboxListResponse> {
	const params = new URLSearchParams();
	if (opts.strategyId) params.set('strategy_id', opts.strategyId);
	if (opts.kind) params.set('kind', opts.kind);
	if (opts.timedOut !== undefined) params.set('timed_out', String(opts.timedOut));
	if (opts.limit !== undefined) params.set('limit', String(opts.limit));
	if (opts.offset !== undefined) params.set('offset', String(opts.offset));
	const qs = params.toString();
	return fetchApi<SandboxListResponse>(
		`/sandbox/runs${qs ? `?${qs}` : ''}`
	);
}

export async function getSandboxRun(id: number): Promise<SandboxRunDetail> {
	return fetchApi<SandboxRunDetail>(`/sandbox/runs/${id}`);
}

export async function scanStrategy(
	path: string,
	options?: { strategyId?: string }
): Promise<AstReport> {
	return fetchApi<AstReport>('/sandbox/scan', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			path,
			strategy_id: options?.strategyId ?? null
		})
	});
}

export async function testSandbox(): Promise<SandboxTestResponse> {
	return fetchApi<SandboxTestResponse>('/sandbox/test', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({}),
		timeoutMs: 60000
	});
}

export async function killSandboxRun(id: number): Promise<SandboxKillResponse> {
	return fetchApi<SandboxKillResponse>(`/sandbox/runs/${id}/kill`, {
		method: 'POST'
	});
}
