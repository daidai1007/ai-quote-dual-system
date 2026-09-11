// Deliberately small arithmetic grammar. No eval, Function, property access or SQL.
export const RESULT_ALIASES = Object.freeze({ 材料质量: '材料重量' });
export function parseFormula(source) {
  if (typeof source === 'number' && Number.isFinite(source)) return { type: 'number', value: source };
  if (typeof source !== 'string' || !source.trim()) throw new Error('公式为空');
  const text = source.trim().replace(/^=/, '').replaceAll('（', '(').replaceAll('）', ')');
  if (text.length > 4096) throw new Error('公式过长');
  const tokens = []; let pos = 0;
  const pattern = /\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+)|([\p{L}_][\p{L}\p{N}_]*)|([()+\-*/^,]))/uy;
  while (pos < text.length) {
    if (!text.slice(pos).trim()) break;
    pattern.lastIndex = pos;
    const match = pattern.exec(text);
    if (!match) throw new Error(`不支持的公式字符：${text.slice(pos, pos + 12)}`);
    tokens.push(match[1] ? { type: 'number', value: Number(match[1]) }
      : match[2] ? { type: 'name', value: RESULT_ALIASES[match[2]] || match[2] }
      : { type: match[3] });
    pos = pattern.lastIndex;
  }
  let cursor = 0, depth = 0;
  const peek = () => tokens[cursor]?.type;
  const take = (type) => { if (peek() !== type) throw new Error(`公式缺少 ${type}`); return tokens[cursor++]; };
  const functions = new Set(['MIN', 'MAX', 'ABS', 'ROUND']);
  function primary() {
    if (++depth > 64) throw new Error('公式嵌套过深');
    let node;
    if (peek() === '+' || peek() === '-') node = { type: 'unary', op: tokens[cursor++].type, arg: primary() };
    else if (peek() === 'number') node = tokens[cursor++];
    else if (peek() === '(') { cursor++; node = expression(); take(')'); }
    else if (peek() === 'name') {
      const name = tokens[cursor++].value;
      if (peek() === '(') {
        if (!functions.has(name)) throw new Error(`不支持的函数：${name}`);
        cursor++; const args = [expression()];
        while (peek() === ',') { cursor++; args.push(expression()); }
        take(')'); node = { type: 'call', name, args };
      } else node = { type: 'variable', name };
    } else throw new Error('公式不完整或有连续运算符');
    depth--; return node;
  }
  function expression(minimum = 0) {
    let left = primary();
    const powers = { '+': 1, '-': 1, '*': 2, '/': 2, '^': 3 };
    while (powers[peek()] > minimum) {
      const op = tokens[cursor++].type;
      const right = expression(op === '^' ? powers[op] - 1 : powers[op]);
      left = { type: 'binary', op, left, right };
    }
    return left;
  }
  const tree = expression();
  if (cursor !== tokens.length) throw new Error('公式存在多余内容');
  return tree;
}
export function formulaVariables(source) {
  const names = new Set();
  function visit(n) {
    if (n.type === 'variable') names.add(n.name);
    for (const child of [n.left, n.right, n.arg, ...(n.args || [])].filter(Boolean)) visit(child);
  }
  visit(parseFormula(source)); return [...names];
}
export function evaluateFormula(source, variables) {
  function calculate(n) {
    let result;
    if (n.type === 'number') result = n.value;
    else if (n.type === 'variable') {
      const value = variables[n.name];
      if (value === undefined || value === null || value === '' || typeof value === 'boolean') throw new Error(`缺少参数：${n.name}`);
      result = Number(value);
    } else if (n.type === 'unary') result = (n.op === '-' ? -1 : 1) * calculate(n.arg);
    else if (n.type === 'binary') {
      const a = calculate(n.left), b = calculate(n.right);
      if (n.op === '/' && b === 0) throw new Error('公式除数为0');
      result = { '+': () => a + b, '-': () => a - b, '*': () => a * b, '/': () => a / b, '^': () => a ** b }[n.op]();
    } else {
      const args = n.args.map(calculate);
      if (n.name === 'ABS' && args.length === 1) result = Math.abs(args[0]);
      else if (n.name === 'ROUND' && args.length === 2 && Number.isInteger(args[1]) && Math.abs(args[1]) <= 12) result = round(args[0], args[1]);
      else if (n.name === 'MIN') result = Math.min(...args);
      else if (n.name === 'MAX') result = Math.max(...args);
      else throw new Error(`函数参数错误：${n.name}`);
    }
    if (!Number.isFinite(result) || Math.abs(result) > 1e15) throw new Error('公式结果不是有效有限数值');
    return result;
  }
  return calculate(parseFormula(source));
}
export function round(value, places = 2) {
  const scale = 10 ** places;
  return Math.sign(value) * Math.round((Math.abs(value) + Number.EPSILON * Math.max(1, Math.abs(value))) * scale) / scale;
}
