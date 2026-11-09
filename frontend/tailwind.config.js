/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // Grafite neutro (substitui o slate azulado em todo o sistema)
      colors: {
        slate: {
          50: '#fafafa', 100: '#f4f4f5', 200: '#e4e4e7', 300: '#d4d4d8', 400: '#a1a1aa',
          500: '#71717a', 600: '#52525b', 700: '#3f3f46', 800: '#27272a', 900: '#18181b', 950: '#09090b',
        },
        mockbird: {
          bg: '#09090b',
          surface: '#0f0f11',
          card: '#17171a',
          cardhover: '#1e1e22',
          border: '#27272a',
          borderlight: '#3f3f46',
          blue: '#5e6ad2',       // acento único
          bluedark: '#4f5bc0',
          cyan: '#a5acf5',       // acento claro para texto/ícones
          cyanbadge: '#4f5bc0',
        },
        brand: {
          50: '#f1f2fd', 100: '#e1e3fa', 200: '#c4c8f5', 300: '#a5acf5', 400: '#7f88e6',
          500: '#5e6ad2', 600: '#4f5bc0', 700: '#414ba3', 800: '#363e84', 900: '#2c3268',
        },
      },
      boxShadow: {
        panel: '0 0 0 1px rgba(255,255,255,0.04), 0 8px 24px -8px rgba(0,0,0,0.6)',
      },
    },
  },
  plugins: [],
}
