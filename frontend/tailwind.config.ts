import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#16211c",
        dim: "#67756c",
        line: "#dce4dd",
        go: "#2f7d4f",
        stop: "#b3352c",
        warn: "#96660f",
        info: "#2b5f9e",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
