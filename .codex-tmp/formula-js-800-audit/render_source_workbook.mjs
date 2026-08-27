import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "G:/gongsi/banjinxitong/板件后续二次修改/数据库备份/公式法报价/材料重量/JS,JP,JA,JE,JK,JM计算表.xlsx";
const outputPath = "G:/gongsi/banjinxitong/板件后续二次修改/render-test-deploy/.codex-tmp/formula-js-800-audit/authoritative-js-layout.png";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const preview = await workbook.render({
  sheetName: "JS",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(outputPath, new Uint8Array(await preview.arrayBuffer()));
console.log(`SPREADSHEET_PREVIEW=${outputPath}`);
