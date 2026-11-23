import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './components/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: { extend: { colors: { ink: '#22262e', muted: '#747a86', line: '#e7e9ed', canvas: '#f6f7f9', accent: '#4d61d8' }, boxShadow: { panel: '0 1px 2px rgba(16,24,40,.04), 0 5px 16px rgba(16,24,40,.035)' } } },
  plugins: [],
};
export default config;
