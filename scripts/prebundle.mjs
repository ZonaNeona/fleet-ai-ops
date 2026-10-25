import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
await mkdir(".build", { recursive: true });
for (const name of ["recharts", "zod"])
  await build({
    stdin: { contents: `export * from '${name}';`, resolveDir: process.cwd() },
    outfile: `.build/${name}.js`,
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    minify: true,
    external: ["react", "react-dom", "react/jsx-runtime"],
    logLevel: "info",
  });
