/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0B0E14",
          surface: "#141822",
          raised: "#1C212E",
        },
        border: {
          DEFAULT: "#2A3142",
          strong: "#3B4458",
        },
        text: {
          DEFAULT: "#E8EAED",
          muted: "#8B92A5",
          subtle: "#5A6173",
        },
        accent: {
          DEFAULT: "#5EEAD4",
          dim: "#2DD4BF",
          strong: "#14B8A6",
        },
        demand: {
          smooth: "#5EEAD4",
          erratic: "#FBBF24",
          intermittent: "#A78BFA",
          lumpy: "#FB7185",
        },
        success: "#4ADE80",
        warning: "#FBBF24",
        danger: "#FB7185",
        info: "#60A5FA",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "12px",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(94, 234, 212, 0.15), 0 0 24px rgba(94, 234, 212, 0.08)",
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "slide-up": "slide-up 0.2s ease-out",
        "fade-in": "fade-in 0.15s ease-out",
      },
      keyframes: {
        "slide-up": {
          "0%": { transform: "translateY(4px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};