/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0b0d10",
          raised: "#12161b",
          hover: "#1a1f26",
        },
        line: "#23292f",
        ink: {
          DEFAULT: "#e6ebf1",
          dim: "#9aa4ae",
          faint: "#6b7480",
        },
        accent: {
          DEFAULT: "#6aa9ff",
          strong: "#4a8cff",
        },
        severity: {
          info: "#4a8cff",
          warn: "#f1a83a",
          error: "#ef5a5a",
          ok: "#3ecf8e",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Menlo", "Monaco", "monospace"],
      },
    },
  },
  plugins: [],
};
