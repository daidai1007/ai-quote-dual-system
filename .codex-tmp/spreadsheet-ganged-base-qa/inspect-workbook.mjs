import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = fileURLToPath(new URL("./ganged-base-qa.xlsx", import.meta.url));
const previewPath = fileURLToPath(new URL("./ganged-base-qa.png", import.meta.url));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));

const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 4000,
});
console.log(sheets.ndjson);

const quick = await workbook.inspect({
  kind: "table",
  range: "快速报价单!A10:Z12",
  include: "values,formulas",
  tableMaxRows: 3,
  tableMaxCols: 26,
  maxChars: 8000,
});
console.log(quick.ndjson);

const formulas = await workbook.inspect({
  kind: "formula",
  sheetId: "快速报价单",
  range: "K10:N12",
  maxChars: 4000,
  options: { maxResults: 20 },
});
console.log(formulas.ndjson);

const detail = await workbook.inspect({
  kind: "table",
  range: "成本明细!A9:O15",
  include: "values,formulas",
  tableMaxRows: 7,
  tableMaxCols: 15,
  maxChars: 8000,
});
console.log(detail.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "ganged base formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "快速报价单",
  range: "A1:Z14",
  scale: 1.5,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
