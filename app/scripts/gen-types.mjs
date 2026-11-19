// Genera src/engine/contract.gen.ts desde el contrato RPC del engine (JSON Schema de Pydantic).
// Nada se tipa a mano en dos lados: si cambia un modelo del engine, se regenera
// `engine/schema/rpc-1.schema.json` (`uv run pstudio schema --rpc --out …`) y después esto.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const root = (p) => fileURLToPath(new URL(p, import.meta.url));
const schema = JSON.parse(await readFile(root("../../engine/schema/rpc-1.schema.json"), "utf8"));

// Pydantic pone `title` a cada campo; json-schema-to-typescript lo convierte en un alias por
// campo (`Op1`, `Amount5`…). Solo los modelos ($defs) y los grupos conservan su nombre.
function stripTitles(node, keep = false) {
  if (node === null || typeof node !== "object") return;
  if (!keep) delete node.title;
  for (const [key, value] of Object.entries(node)) {
    if (key === "$defs") Object.values(value).forEach((model) => stripTitles(model, true));
    // Recorrer los valores (no el objeto `properties`): un campo puede llamarse "title".
    else if (key === "properties") Object.values(value).forEach((v) => stripTitles(v, node === schema));
    else stripTitles(value);
  }
}
stripTitles(schema, true);

const ts = await compile(schema, "Rpc", {
  bannerComment:
    "/* Generado por scripts/gen-types.mjs desde engine/schema/rpc-1.schema.json. No editar. */",
  additionalProperties: false,
  unreachableDefinitions: false,
  strictIndexSignatures: true,
  format: true,
  style: { semi: true, singleQuote: false, printWidth: 100 },
});
await writeFile(root("../src/engine/contract.gen.ts"), ts.replace(/\r\n/g, "\n"));
console.log("contract.gen.ts actualizado");
