/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,jsx}",
    "./components/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // "sans" es la fuente por defecto de Tailwind (body, botones,
        // parrafos); "heading" se usa a mano en titulos y en la marca del
        // sidebar. Mismo par que novodivisas.com: Dosis + Open Sans.
        sans: ["var(--font-open-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        heading: ["var(--font-dosis)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // Gris ejecutivo / slate -- base neutra del sistema de diseño.
        // Coincide con la paleta Tailwind "slate" de fabrica, se declara
        // explicita aca para que quede documentado que es una decision de
        // diseno, no un accidente de usar los defaults.
        surface: "#f8fafc", // fondo principal (gris quirurgico ultra-claro)
        ink: "#0f172a", // texto principal / titulos
        // Acento corporativo unico -- reservado para CTAs y estados criticos.
        // Azul profesional inspirado en NovoDivisas (paneles financieros
        // tipo fintech/banca) -- reemplaza al esmeralda anterior.
        accent: {
          DEFAULT: "#2563eb", // blue-600
          dark: "#1d4ed8", // blue-700
          light: "#eff6ff", // blue-50
        },
      },
      boxShadow: {
        // Sombra "casi imperceptible" del brief -- se usa en vez de
        // shadow-md/shadow-lg por defecto de Tailwind, que se ven mas
        // "genericas".
        soft: "0 8px 30px rgb(0,0,0,0.04)",
        "soft-lg": "0 12px 40px rgb(0,0,0,0.06)",
      },
      keyframes: {
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 0.5s ease-out both",
      },
    },
  },
  plugins: [],
};
