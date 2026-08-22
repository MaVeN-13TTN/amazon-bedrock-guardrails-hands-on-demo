import type { Config } from "tailwindcss";

/**
 * The font sizes below are the legibility floors this demo is presented at: a
 * Google Meet screen share, compressed, watched on laptops and phones. They are
 * named rather than inlined so a component cannot quietly fall below the floor
 * and a reviewer can audit every floor in one place.
 *
 * Requirement 6 sets them: 16px for stage labels and conversation turns, 14px for
 * policy findings, forwarded text, hints and the disclosure.
 */
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#16211c",
        // Darkened from #67756c, which measured 4.43:1 on red-50 and 4.49:1 on
        // the body background — under the 4.5:1 floor. This clears 5.4:1 on
        // every background the UI uses.
        dim: "#5a675e",
        line: "#dce4dd",
        go: "#2f7d4f",
        stop: "#b3352c",
        warn: "#96660f",
        info: "#2b5f9e",
      },
      fontSize: {
        // Stage labels, and the control that opens the Background_View.
        stage: ["1rem", { lineHeight: "1.4rem" }],
        // Member and assistant turns, and the failure message that replaces one.
        turn: ["1rem", { lineHeight: "1.55rem" }],
        // Policy findings, forwarded text, hints, the disclosure.
        finding: ["0.875rem", { lineHeight: "1.35rem" }],
        // Raw JSON, and its enlarged state under the Requirement 6.10 control.
        raw: ["0.875rem", { lineHeight: "1.35rem" }],
        "raw-lg": ["1.25rem", { lineHeight: "1.8rem" }],
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
