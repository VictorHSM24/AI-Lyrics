/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic colors mapped via CSS variables
        surface: {
          DEFAULT: "rgb(var(--color-surface) / <alpha-value>)",
          hover: "rgb(var(--color-surface-hover) / <alpha-value>)",
          raised: "rgb(var(--color-surface-raised) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
          strong: "rgb(var(--color-border-strong) / <alpha-value>)",
        },
        text: {
          DEFAULT: "rgb(var(--color-text) / <alpha-value>)",
          muted: "rgb(var(--color-text-muted) / <alpha-value>)",
          subtle: "rgb(var(--color-text-subtle) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          hover: "rgb(var(--color-accent-hover) / <alpha-value>)",
          muted: "rgb(var(--color-accent-muted) / <alpha-value>)",
        },
        status: {
          healthy: "rgb(var(--color-status-healthy) / <alpha-value>)",
          warning: "rgb(var(--color-status-warning) / <alpha-value>)",
          error: "rgb(var(--color-status-error) / <alpha-value>)",
          offline: "rgb(var(--color-status-offline) / <alpha-value>)",
          unknown: "rgb(var(--color-status-unknown) / <alpha-value>)",
          processing: "rgb(var(--color-status-processing) / <alpha-value>)",
          paused: "rgb(var(--color-status-paused) / <alpha-value>)",
          running: "rgb(var(--color-status-running) / <alpha-value>)",
          success: "rgb(var(--color-status-success) / <alpha-value>)",
          info: "rgb(var(--color-status-info) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
