import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookUrl = new URL("./bugfix-regression-qa.xlsx", import.meta.url);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(fileURLToPath(workbookUrl)));

const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 4000,
});
console.log(sheets.ndjson);

for (const [sheetId, range] of [
  ["公式法报价单", "A1:AC15"],
  ["快速报价单", "A1:Z15"],
  ["成本明细", "A1:O30"],
]) {
  const inspection = await workbook.inspect({
    kind: "table,formula",
    sheetId,
    range,
    include: "values,formulas",
    tableMaxRows: 30,
    tableMaxCols: 32,
    maxChars: 16000,
  });
  console.log(inspection.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "bugfix workbook formula error scan",
});
if ((errors.matchingCells || []).length) {
  throw new Error(`workbook contains formula errors: ${errors.ndjson}`);
}
console.log(errors.ndjson);

await fs.mkdir(new URL("./previews/", import.meta.url), { recursive: true });
for (const sheetName of ["公式法报价单", "快速报价单", "成本明细"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const safeName = sheetName === "公式法报价单" ? "bugfix-formula"
    : sheetName === "快速报价单" ? "bugfix-quick" : "bugfix-cost-detail";
  await fs.writeFile(
    new URL(`./previews/${safeName}.png`, import.meta.url),
    new Uint8Array(await preview.arrayBuffer()),
  );
}
