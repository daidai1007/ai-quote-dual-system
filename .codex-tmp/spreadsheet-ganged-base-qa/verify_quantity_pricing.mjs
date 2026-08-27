import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = new URL("./quantity-pricing-qa.xlsx", import.meta.url);
const workbook = await SpreadsheetFile.importXlsx(
  await FileBlob.load(fileURLToPath(workbookPath)),
);
await fs.mkdir(new URL("./previews/", import.meta.url), { recursive: true });

for (const [sheetId, range] of [
  ["公式法报价单", "A10:AC17"],
  ["快速报价单", "A10:X17"],
  ["成本明细", "A1:O20"],
]) {
  const inspection = await workbook.inspect({
    kind: "table,formula",
    sheetId,
    range,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 32,
    maxChars: 12000,
  });
  console.log(inspection.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "quantity pricing formula error scan",
});
console.log(errors.ndjson);

for (const sheetName of ["公式法报价单", "快速报价单", "成本明细"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const safeName = sheetName === "公式法报价单" ? "formula"
    : sheetName === "快速报价单" ? "quick" : "cost-detail";
  await fs.writeFile(
    new URL(`./previews/quantity-${safeName}.png`, import.meta.url),
    new Uint8Array(await preview.arrayBuffer()),
  );
}
