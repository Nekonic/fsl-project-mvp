import { render } from "preact";
import "./theme/tokens.css";
import "./theme/components.css";
import { App } from "./App";

const root = document.getElementById("app");
if (root) render(<App />, root);
