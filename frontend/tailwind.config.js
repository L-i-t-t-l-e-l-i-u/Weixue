/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        hw: ['"楷体"', '"KaiTi"', '"STKaiti"', 'serif'],
      },
    },
  },
  plugins: [],
};
