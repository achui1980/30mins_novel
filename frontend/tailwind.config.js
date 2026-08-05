/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        paper: { 50: "#FAF6EE", 100: "#F3ECDD" },
        ink: { 900: "#2B2724", 600: "#6B6259", 300: "#D9D2C4" },
        seal: { 100: "#F5DEDA", 600: "#B33A3A", 700: "#8F2C2C" },
        pine: { 100: "#DCE6E1", 600: "#3F5B4E" },
        amber: { 600: "#C9A15B" },
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
