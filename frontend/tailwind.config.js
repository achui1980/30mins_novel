/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Full ramps: previously only ink 900/600/300 and amber 600 existed, so
        // classes like `text-ink-800` / `bg-amber-100` used across the reader
        // silently compiled to nothing (invisible text, invisible highlights).
        paper: { 50: "#FAF6EE", 100: "#F3ECDD", 200: "#EBE2CE" },
        ink: {
          900: "#2B2724",
          800: "#3D3833",
          700: "#4F4842",
          600: "#6B6259",
          500: "#857B70",
          400: "#A69C8E",
          300: "#D9D2C4",
          200: "#E8E1D3",
        },
        seal: { 100: "#F5DEDA", 600: "#B33A3A", 700: "#8F2C2C" },
        pine: { 100: "#DCE6E1", 600: "#3F5B4E" },
        amber: { 100: "#F6EAD2", 600: "#C9A15B" },
        danger: { 600: "#C0392B" },
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', "Inter", "system-ui", "sans-serif"],
        serif: ['"Noto Serif SC"', "Georgia", "serif"],
      },
      borderRadius: { card: "12px", btn: "8px" },
      boxShadow: {
        sm2: "0 1px 2px rgba(43,39,36,.04)",
        pop: "0 8px 24px rgba(43,39,36,.08)",
      },
    },
  },
  plugins: [],
};
