import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './components/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        ink: '#172026',
        muted: '#5F6B70',
        line: '#DCE3E0',
        canvas: '#F3F5F4',
        accent: '#14606E',
        'accent-strong': '#0F4E5A',
        'accent-soft': '#E3F0F2',
        marigold: '#F0A92E',
      },
      fontFamily: {
        sans: ['var(--font-body)', 'system-ui', 'sans-serif'],
        display: ['var(--font-display)', 'var(--font-body)', 'system-ui', 'sans-serif'],
      },
      boxShadow: { panel: '0 1px 2px rgba(23,32,38,.05), 0 4px 14px -6px rgba(23,32,38,.08)' },
      keyframes: {
        settle: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'none' },
        },
      },
      animation: { settle: 'settle .45s cubic-bezier(.2,.7,.2,1) both' },
    },
  },
  plugins: [],
};
export default config;
