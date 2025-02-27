import { createRoot } from "react-dom/client";
import "@fontsource/roboto/300.css";
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";
import { Root } from "./root";

export function init() {
  const rootElement = document.getElementById("web-app-root");
  if (rootElement) {
    const root = createRoot(rootElement);
    root.render(<Root />);
  }
}
