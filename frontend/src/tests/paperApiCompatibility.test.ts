import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
	closePaperPosition,
	createPaperSession,
	deletePaperSession,
	getPaperWebSocketUrl,
	replayPause,
	replayPlay,
	replayReset,
	replaySeek,
	replaySetSpeed,
	replayStep,
	startPaperSession,
	stopPaperSession,
	updatePaperSession,
} from '../lib/api/paper';

const mockFetch = vi.fn();
globalThis.fetch = mockFetch as unknown as typeof fetch;

describe('paper compatibility API client', () => {
	beforeEach(() => {
		mockFetch.mockReset();
	});

	it('rejects unsupported standalone session mutations before fetch', async () => {
		await expect(createPaperSession('Strategy', 'BTC/USDT')).rejects.toThrow('not supported');
		await expect(updatePaperSession('compat:strategy:S00001', { symbol: 'ETH/USDT' })).rejects.toThrow('not supported');
		await expect(startPaperSession('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(stopPaperSession('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(deletePaperSession('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(closePaperPosition('compat:strategy:S00001')).rejects.toThrow('not supported');

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it('rejects unsupported replay controls before fetch', async () => {
		await expect(replayStep('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(replaySeek('compat:strategy:S00001', 4)).rejects.toThrow('not supported');
		await expect(replayPlay('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(replayPause('compat:strategy:S00001')).rejects.toThrow('not supported');
		await expect(replaySetSpeed('compat:strategy:S00001', 2)).rejects.toThrow('not supported');
		await expect(replayReset('compat:strategy:S00001')).rejects.toThrow('not supported');

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it('does not advertise a paper websocket URL for compatibility sessions', () => {
		expect(() => getPaperWebSocketUrl('compat:strategy:S00001')).toThrow('not supported');
	});
});
