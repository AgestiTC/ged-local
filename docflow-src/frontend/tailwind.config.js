/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Couleurs DocFlow AI
        primary: {
          50:  '#f0f4ff',
          100: '#dbe4ff',
          500: '#4f76f6',
          600: '#3b5fe0',
          700: '#2a46c4',
          900: '#1a2d7a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
