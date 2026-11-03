module.exports = {
  content: ["./web/**/*.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        cream: {
          bg: "#FAF6F0",
          card: "#F2ECE1",
          hover: "#EAE0D0",
          border: "#DED2BF",
          dark: "#D0C0A8",
        },
        wood: {
          espresso: "#2A1B12",
          umber: "#6E523E",
          walnut: "#7C4D2B",
          walnutHover: "#5E381D",
          amber: "#C87D32",
          terracotta: "#A8422B",
          sage: "#4A6B53",
        },
        chessDark: "#0f1015",
        chessCard: "#181a20",
        chessPanel: "#12141a",
        chessBorder: "#262932",
        accent: "#e63946",
        accentAmber: "#f4a261",
        accentEmerald: "#2a9d8f",
      },
      fontFamily: {
        serif: ["Fraunces", "Georgia", "serif"],
        sans: ["Plus Jakarta Sans", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
