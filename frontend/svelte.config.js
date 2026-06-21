import adapterAuto from '@sveltejs/adapter-auto';
import adapterStatic from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const usePackaged = process.env.FORVEN_PACKAGE_BUILD === '1';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),

	kit: {
		adapter: usePackaged
			? adapterStatic({ pages: 'build', assets: 'build', fallback: 'index.html', strict: false })
			: adapterAuto(),
		prerender: {
			handleUnseenRoutes: 'warn'
		}
	}
};

export default config;
