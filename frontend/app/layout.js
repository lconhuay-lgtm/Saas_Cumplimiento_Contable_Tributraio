import { Dosis, Open_Sans } from "next/font/google";
import "./globals.css";
import { TrabajosProvider } from "../contexts/TrabajosContext";

// Misma pareja tipografica que usa novodivisas.com (confirmado inspeccionando
// su CSS real): Dosis para titulos/marca -- da el aire "elegante corporativo"
// que se pidio -- y Open Sans para el resto del texto, mas neutro y legible
// en tablas/formularios largos. Se cargan con next/font (se auto-hospedan en
// el build, no dependen de que el navegador del usuario llegue a Google
// Fonts en tiempo real).
const dosis = Dosis({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-dosis",
  display: "swap",
});

const openSans = Open_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "600", "700", "800"],
  variable: "--font-open-sans",
  display: "swap",
});

export const metadata = {
  title: "Anzen Sol",
  description: "Anzen Sol -- tablero multi-RUC del buzon de notificaciones SUNAT",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es" className={`${dosis.variable} ${openSans.variable}`}>
      <body>
        <TrabajosProvider>{children}</TrabajosProvider>
      </body>
    </html>
  );
}
