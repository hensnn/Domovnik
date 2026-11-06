import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    // sdílený soubor se pevným obsahem (předává se stabilní funkce modulu, ne inline callback)
    files: ["src/lib/currentLocation.ts"],
    rules: { "react-hooks/use-memo": "off" },
  },
);
