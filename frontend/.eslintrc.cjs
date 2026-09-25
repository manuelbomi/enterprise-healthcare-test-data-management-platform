/**
 * ESLint configuration.
 *
 * Includes jsx-a11y so accessibility issues are caught at lint time, not
 * discovered later — consistent with the "accessible-by-default" decision
 * in docs/adr/0008-frontend-stack.md.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "plugin:jsx-a11y/recommended",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  plugins: ["@typescript-eslint", "react", "react-hooks", "jsx-a11y"],
  settings: { react: { version: "detect" } },
  ignorePatterns: ["dist", "node_modules"],
  rules: {
    "react/react-in-jsx-scope": "off",
  },
};
