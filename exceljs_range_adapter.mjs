/*
 * Minimal A1-range facade used by the quotation exporter.
 *
 * ExcelJS intentionally exposes cells/rows/columns rather than a mutable
 * rectangular Range object.  The exporter performs the same small set of
 * rectangular operations many times, so this adapter keeps those operations
 * explicit and testable without depending on a private spreadsheet runtime.
 */

const clone = (value) => {
  if (value === null || value === undefined || typeof value !== "object") return value;
  if (value instanceof Date) return new Date(value.getTime());
  return structuredClone(value);
};

const columnNumber = (letters) => {
  let value = 0;
  for (const character of String(letters).toUpperCase()) {
    value = value * 26 + character.charCodeAt(0) - 64;
  }
  return value;
};

const parseCell = (address) => {
  const match = /^([A-Z]+)(\d+)$/i.exec(String(address).trim());
  if (!match) throw new Error(`invalid Excel cell address: ${address}`);
  return { column: columnNumber(match[1]), row: Number(match[2]) };
};

export const parseRangeAddress = (address) => {
  const [startText, endText = startText] = String(address).split(":");
  const start = parseCell(startText);
  const end = parseCell(endText);
  if (end.row < start.row || end.column < start.column) {
    throw new Error(`invalid Excel range order: ${address}`);
  }
  return {
    startRow: start.row,
    endRow: end.row,
    startColumn: start.column,
    endColumn: end.column,
    rowCount: end.row - start.row + 1,
    columnCount: end.column - start.column + 1,
  };
};

const argb = (color) => {
  const value = String(color || "").replace(/^#/, "").toUpperCase();
  if (/^[0-9A-F]{6}$/.test(value)) return `FF${value}`;
  if (/^[0-9A-F]{8}$/.test(value)) return value;
  throw new Error(`invalid Excel color: ${color}`);
};

class RangeFormat {
  constructor(range) {
    this.range = range;
  }

  set columnWidth(width) {
    const value = Number(width);
    for (let column = this.range.bounds.startColumn; column <= this.range.bounds.endColumn; column += 1) {
      this.range.worksheet.getColumn(column).width = value;
    }
  }

  set rowHeight(height) {
    const value = Number(height);
    for (let row = this.range.bounds.startRow; row <= this.range.bounds.endRow; row += 1) {
      this.range.worksheet.getRow(row).height = value;
    }
  }

  set fill(color) {
    const fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: argb(color) },
    };
    this.range.forEachCell((cell) => { cell.fill = clone(fill); });
  }

  set font(font) {
    this.range.forEachCell((cell) => {
      const next = { ...(clone(cell.font) || {}), ...(clone(font) || {}) };
      if (typeof next.color === "string") next.color = { argb: argb(next.color) };
      cell.font = next;
    });
  }

  set horizontalAlignment(value) {
    this.range.forEachCell((cell) => {
      cell.alignment = { ...(clone(cell.alignment) || {}), horizontal: value };
    });
  }

  set verticalAlignment(value) {
    this.range.forEachCell((cell) => {
      cell.alignment = { ...(clone(cell.alignment) || {}), vertical: value };
    });
  }

  set wrapText(value) {
    this.range.forEachCell((cell) => {
      cell.alignment = { ...(clone(cell.alignment) || {}), wrapText: Boolean(value) };
    });
  }

  set numberFormat(value) {
    this.range.forEachCell((cell) => { cell.numFmt = String(value); });
  }

  set borders(config = {}) {
    const edgeFrom = (definition = {}) => ({
      style: definition.style || config.style || "thin",
      color: { argb: argb(definition.color || config.color || "#000000") },
    });
    this.range.forEachCell((cell) => {
      const next = { ...(clone(cell.border) || {}) };
      if (config.preset === "all") {
        const edge = edgeFrom();
        next.top = clone(edge);
        next.left = clone(edge);
        next.bottom = clone(edge);
        next.right = clone(edge);
      } else {
        let applied = false;
        for (const side of ["top", "left", "bottom", "right"]) {
          if (!config[side]) continue;
          next[side] = edgeFrom(config[side]);
          applied = true;
        }
        if (!applied) throw new Error(`unsupported border configuration: ${JSON.stringify(config)}`);
      }
      cell.border = next;
    });
  }
}

class ExcelRange {
  constructor(worksheet, address) {
    this.worksheet = worksheet;
    this.address = address;
    this.bounds = parseRangeAddress(address);
    this.format = new RangeFormat(this);
  }

  forEachCell(callback) {
    for (let row = this.bounds.startRow; row <= this.bounds.endRow; row += 1) {
      for (let column = this.bounds.startColumn; column <= this.bounds.endColumn; column += 1) {
        callback(this.worksheet.getCell(row, column), row, column);
      }
    }
  }

  get values() {
    const matrix = [];
    for (let row = this.bounds.startRow; row <= this.bounds.endRow; row += 1) {
      const values = [];
      for (let column = this.bounds.startColumn; column <= this.bounds.endColumn; column += 1) {
        values.push(this.worksheet.getCell(row, column).value ?? null);
      }
      matrix.push(values);
    }
    return matrix;
  }

  set values(matrix) {
    if (!Array.isArray(matrix) || matrix.length !== this.bounds.rowCount) {
      throw new Error(`row count does not match range ${this.address}`);
    }
    matrix.forEach((rowValues, rowOffset) => {
      if (!Array.isArray(rowValues) || rowValues.length !== this.bounds.columnCount) {
        throw new Error(`column count does not match range ${this.address}`);
      }
      rowValues.forEach((value, columnOffset) => {
        this.worksheet.getCell(
          this.bounds.startRow + rowOffset,
          this.bounds.startColumn + columnOffset,
        ).value = value === "" ? null : clone(value);
      });
    });
  }

  copyFrom(source, mode = "all") {
    if (!(source instanceof ExcelRange)) throw new Error("copy source must be an Excel range");
    if (source.bounds.rowCount !== this.bounds.rowCount
      || source.bounds.columnCount !== this.bounds.columnCount) {
      throw new Error(`copy range shape mismatch: ${source.address} -> ${this.address}`);
    }
    const snapshot = [];
    source.forEachCell((cell) => {
      snapshot.push({
        value: clone(cell.value),
        style: mode === "all" ? clone(cell.style) : null,
        note: mode === "all" ? clone(cell.note) : null,
      });
    });
    let index = 0;
    this.forEachCell((cell) => {
      const sourceCell = snapshot[index];
      index += 1;
      if (mode === "formulas") {
        if (sourceCell.value && typeof sourceCell.value === "object" && sourceCell.value.formula) {
          cell.value = sourceCell.value;
        }
        return;
      }
      cell.value = sourceCell.value === "" ? null : sourceCell.value;
      if (mode === "all") {
        cell.style = sourceCell.style || {};
        if (sourceCell.note) cell.note = sourceCell.note;
      }
    });
  }

  clear({ applyTo = "all" } = {}) {
    this.forEachCell((cell) => {
      cell.value = null;
      if (applyTo === "all") {
        cell.style = {};
        cell.note = undefined;
      }
    });
  }

  merge() {
    this.worksheet.mergeCells(this.address);
  }
}

export const attachRangeApi = (worksheet) => {
  if (typeof worksheet.getRange !== "function") {
    Object.defineProperty(worksheet, "getRange", {
      configurable: true,
      enumerable: false,
      value(address) { return new ExcelRange(this, address); },
    });
  }
  return worksheet;
};

export const attachWorkbookRangeApi = (workbook) => {
  workbook.worksheets.forEach(attachRangeApi);
  return workbook;
};

export const plainCellValue = (value) => {
  if (value && typeof value === "object") {
    if (Object.hasOwn(value, "result")) return value.result;
    if (Array.isArray(value.richText)) return value.richText.map((item) => item.text || "").join("");
    if (Object.hasOwn(value, "text")) return value.text;
  }
  return value ?? null;
};

export const rangePlainValues = (worksheet, address) => worksheet
  .getRange(address)
  .values
  .map((row) => row.map(plainCellValue));

export const scanWorkbookFormulaErrors = (workbook) => {
  const pattern = /#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A)/i;
  const errors = [];
  for (const worksheet of workbook.worksheets) {
    worksheet.eachRow({ includeEmpty: false }, (row) => {
      row.eachCell({ includeEmpty: false }, (cell) => {
        const value = plainCellValue(cell.value);
        if (typeof value === "string" && pattern.test(value)) {
          errors.push(`${worksheet.name}!${cell.address}=${value}`);
        }
      });
    });
  }
  return errors;
};
