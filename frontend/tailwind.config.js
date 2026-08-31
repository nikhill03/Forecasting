/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deep indigo-navy, not achromatic black — keeps warmth in the
        // shadows so the amber accent and demand hues read as pigment
        // rather than glowing on a void.
        bg: {
          DEFAULT: "#0C1019",
          surface: "#131829",
          raised: "#1B2238",
        },
        border: {
          DEFAULT: "#252D48",
          strong: "#39456B",
        },
        text: {
          DEFAULT: "#EEF0F7",
          muted: "#99A2C4",
          subtle: "#616B93",
        },
        // "Signal" — the reading the instrument highlights against the
        // noise. Warm brass/amber, deliberately not the teal/mint used
        // for the Smooth demand class so the two never get confused.
        accent: {
          DEFAULT: "#E8A23D",
          dim: "#CE8A2A",
          strong: "#A96F1D",
        },
        // Cool = steady, warm = volatile — the four demand classes map
        // directly onto the ADI × CV² quadrant's own temperature logic.
        demand: {
          smooth: "#5EEAD4",
          erratic: "#F5C451",
          intermittent: "#9C8CF5",
          lumpy: "#F2617A",
        },
        success: "#5FDBA0",
        warning: "#F0B429",
        danger: "#F2617A",
        info: "#7C9CF2",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "Inter", "system-ui", "sans-serif"],
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
        glow: "0 0 0 1px rgba(232, 162, 61, 0.18), 0 0 28px rgba(232, 162, 61, 0.10)",
        elevated: "0 12px 32px -8px rgba(3, 5, 12, 0.55)",
      },
      backgroundImage: {
        grid: "radial-gradient(circle, rgba(153,162,196,0.16) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "28px 28px",
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "slide-up": "slide-up 0.2s ease-out",
        "fade-in": "fade-in 0.15s ease-out",
        "scale-in": "scale-in 0.4s cubic-bezier(0.16, 1, 0.3, 1) both",
        drift: "drift 10s ease-in-out infinite",
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
        "scale-in": {
          "0%": { transform: "scale(0.6)", opacity: "0" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
        drift: {
          "0%, 100%": { transform: "translate(0, 0)" },
          "50%": { transform: "translate(-2%, 2%)" },
        },
      },
    },
  },
  plugins: [],
};
