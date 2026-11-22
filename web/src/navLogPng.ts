import type { PlatformFile } from "./platform";

// Use the browser's table layout and Canvas text, without SVG foreignObject or
// remote image/font fetching. Only the result tables enter this clean copy.
export async function exportNavLogPng(section: HTMLElement, modeText: string): Promise<PlatformFile> {
  const paper = document.createElement("div");
  paper.className = "nav-log-png-paper";
  paper.setAttribute("aria-hidden", "true");
  const title = document.createElement("h2");
  title.textContent = `NAV LOG — ${modeText}`;
  paper.append(title);
  for (const selector of [".nav-log-table", ".fuel-plan-table"]) {
    const original = section.querySelector<HTMLTableElement>(selector);
    if (!original) throw new Error("Missing NAV LOG table");
    if (selector === ".fuel-plan-table") {
      const heading = document.createElement("h3");
      heading.textContent = "TIME / FUEL PLAN";
      paper.append(heading);
    }
    const table = original.cloneNode(true) as HTMLTableElement;
    if (selector === ".nav-log-table") {
      // Selection controls remain on screen; blank VOR columns have no paper value.
      const emptyColumns = Array.from(table.tHead!.rows[0]!.cells)
        .flatMap((cell, index) => cell.dataset.pngText === "" ? [index] : [])
        .reverse();
      for (const index of emptyColumns) {
        const col = table.querySelectorAll("col")[index];
        const removedWidth = original.tHead!.rows[0]!.cells[index]!.getBoundingClientRect().width;
        for (const row of Array.from(table.rows)) row.deleteCell(index);
        col?.remove();
        const width = parseFloat(table.style.width) - removedWidth;
        table.style.width = table.style.minWidth = `${width}px`;
      }
      table.querySelectorAll(".nav-leg-spacer-row").forEach(row => row.remove());
      table.querySelectorAll(".nav-leg-heading-row").forEach((row, index) => {
        if (index === 0) return;
        const spacer = document.createElement("tr");
        spacer.className = "nav-leg-spacer-row";
        for (let column = 0; column < table.tHead!.rows[0]!.cells.length; column++) {
          spacer.append(document.createElement("td"));
        }
        row.before(spacer);
      });
    }
    table.querySelectorAll<HTMLElement>("[data-display-text]").forEach(cell => {
      const pair = cell.querySelector(".nav-log-pair");
      if (pair) cell.replaceChildren(pair);
      else cell.textContent = cell.dataset.displayText ?? "";
    });
    table.querySelectorAll<HTMLElement>("[data-png-text]").forEach(cell => {
      const text = cell.dataset.pngText ?? "";
      if (cell.matches(".vor-reference-header") && text) {
        const split = text.indexOf(" ");
        cell.replaceChildren(document.createTextNode(text.slice(0, split)), document.createElement("br"),
          document.createTextNode(text.slice(split)));
      } else cell.textContent = text;
    });
    table.querySelectorAll("button, input, select, [id]").forEach(element => {
      if (element.matches("button, input, select")) element.remove();
      else element.removeAttribute("id");
    });
    paper.append(table);
  }
  document.body.append(paper);
  const canvas = document.createElement("canvas");
  try {
    // CSS normal whitespace collapses ASCII runs; Canvas text does not. Normalize
    // the detached copy before measuring it, without touching the working names.
    const whitespace = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
    while (whitespace.nextNode()) {
      const node = whitespace.currentNode as Text;
      node.data = node.data.replace(/[\t\n\f\r ]+/g, " ");
    }
    await document.fonts.ready;
    const bounds = paper.getBoundingClientRect();
    const width = Math.ceil(Math.max(bounds.width, bounds.height * 1.25));
    const height = Math.ceil(bounds.height);
    // Never reduce text below its CSS size. Large images are encoded in strips,
    // rather than allocating a full landscape bitmap (mostly white margin).
    const scale = Math.max(1, Math.min(2, 4096 / width));
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas unavailable");
    const fills: Paint[] = [];
    const borders: (Paint & { width: number })[] = [];
    const texts: Paint[] = [];
    for (const cell of paper.querySelectorAll<HTMLElement>("table, th, td")) {
      const rect = cell.getBoundingClientRect();
      const x = rect.left - bounds.left, y = rect.top - bounds.top;
      const style = getComputedStyle(cell);
      if (cell.matches("th, td")) {
        const color = style.backgroundColor;
        fills.push({ top: y, bottom: y + rect.height, draw(ctx) {
          ctx.fillStyle = color;
          ctx.fillRect(x, y, rect.width, rect.height);
        } });
      }
      const collapsed = getComputedStyle(cell.closest("table")!).borderCollapse === "collapse";
      for (const side of ["top", "right", "bottom", "left"] as const) {
        const size = parseFloat(style.getPropertyValue(`border-${side}-width`));
        const kind = style.getPropertyValue(`border-${side}-style`);
        const color = style.getPropertyValue(`border-${side}-color`);
        if (!size || kind === "none" || kind === "hidden") continue;
        const horizontal = side === "top" || side === "bottom";
        const inset = collapsed ? 0 : size / 2;
        const position = side === "top" ? y + inset : side === "bottom" ? y + rect.height - inset
          : side === "left" ? x + inset : x + rect.width - inset;
        const begin = horizontal ? x : y, end = begin + (horizontal ? rect.width : rect.height);
        borders.push({ top: y - size, bottom: y + rect.height + size, width: size, draw(ctx) {
          ctx.strokeStyle = color;
          ctx.lineCap = "butt";
          ctx.setLineDash(kind === "dotted" ? [size, size] : kind === "dashed" ? [3 * size, 3 * size] : []);
          ctx.lineWidth = kind === "double" ? size / 3 : size;
          for (const offset of kind === "double" ? [-size / 3, size / 3] : [0]) {
            ctx.beginPath();
            ctx.moveTo(horizontal ? begin : position + offset, horizontal ? position + offset : begin);
            ctx.lineTo(horizontal ? end : position + offset, horizontal ? position + offset : end);
            ctx.stroke();
          }
        } });
      }
    }
    const walker = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      if (!node.textContent?.trim() || !node.parentElement) continue;
      const style = getComputedStyle(node.parentElement);
      const font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      context.font = font;
      let start = 0;
      while (start < node.length) {
        range.setStart(node, start);
        range.setEnd(node, start + 1);
        const first = range.getBoundingClientRect();
        let end = start + 1;
        while (end < node.length) {
          range.setStart(node, end);
          range.setEnd(node, end + 1);
          if (Math.abs(range.getBoundingClientRect().top - first.top) > 1) break;
          end += 1;
        }
        // Leading/trailing collapsible spaces have zero advance in DOM layout.
        const text = node.data.slice(start, end).replace(/^ +| +$/g, "");
        if (text) {
          const leading = /^ */.exec(node.data.slice(start, end))![0].length;
          range.setStart(node, start + leading);
          range.setEnd(node, start + leading + 1);
          const left = range.getBoundingClientRect().left - bounds.left;
          const metrics = context.measureText(text);
          const ascent = metrics.fontBoundingBoxAscent ?? parseFloat(style.fontSize) * 0.9;
          const descent = metrics.fontBoundingBoxDescent ?? parseFloat(style.fontSize) * 0.2;
          const top = first.top - bounds.top;
          const baseline = top + (first.height - ascent - descent) / 2 + ascent;
          texts.push({ top, bottom: top + first.height, draw(ctx) {
            ctx.fillStyle = "black";
            ctx.font = font;
            ctx.textBaseline = "alphabetic";
            ctx.fillText(text, left, baseline);
          } });
        }
        start = end;
      }
    }
    const paints = [...fills, ...borders.sort((a, b) => a.width - b.width), ...texts];
    const content = await encodePng(canvas, Math.ceil(width * scale), Math.ceil(height * scale),
      Math.ceil(bounds.width * scale), (left, top, tileHeight) => {
        context.setTransform(scale, 0, 0, scale, -left, -top);
        for (const paint of paints) {
          if (paint.bottom * scale >= top && paint.top * scale < top + tileHeight) paint.draw(context);
        }
      });
    return { name: "NAVLOG.png", mediaType: "image/png", content };
  } finally {
    paper.remove();
    canvas.width = 0;
    canvas.height = 0;
  }
}

type Paint = { top: number; bottom: number; draw: (context: CanvasRenderingContext2D) => void };

// PNG uses one zlib stream across its IDAT chunks. Keep raster memory bounded to
// a 2048 x 32 tile plus 32 complete scanlines, including the white landscape pad.
// https://www.w3.org/TR/png-3/#11IDAT
async function encodePng(canvas: HTMLCanvasElement, width: number, height: number, contentWidth: number,
  draw: (left: number, top: number, height: number) => void): Promise<Uint8Array<ArrayBuffer>> {
  const header = new Uint8Array(13);
  const view = new DataView(header.buffer);
  view.setUint32(0, width); view.setUint32(4, height);
  header[8] = 8; header[9] = 6; // 8-bit RGBA, no interlace.
  const parts: BlobPart[] = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), pngChunk("IHDR", header)];
  const context = canvas.getContext("2d")!;
  let top = 0;
  const rows = new ReadableStream<Uint8Array<ArrayBuffer>>({
    pull(controller) {
      if (top === height) { controller.close(); return; }
      const count = Math.min(32, height - top);
      const stride = 1 + width * 4;
      const pixels = new Uint8Array(stride * count).fill(255);
      for (let row = 0; row < count; row++) pixels[row * stride] = 0; // PNG filter None.
      for (let left = 0; left < contentWidth; left += 2048) {
        canvas.width = Math.min(2048, contentWidth - left);
        canvas.height = count;
        context.fillStyle = "white";
        context.fillRect(0, 0, canvas.width, count);
        draw(left, top, count);
        const tile = context.getImageData(0, 0, canvas.width, count).data;
        for (let row = 0; row < count; row++) {
          pixels.set(tile.subarray(row * canvas.width * 4, (row + 1) * canvas.width * 4),
            row * stride + 1 + left * 4);
        }
      }
      top += count;
      controller.enqueue(pixels);
    },
  });
  const reader = rows.pipeThrough(new CompressionStream("deflate")).getReader();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      parts.push(pngChunk("IDAT", value));
    }
  } finally {
    reader.releaseLock();
  }
  parts.push(pngChunk("IEND", new Uint8Array()));
  return new Uint8Array(await new Blob(parts, { type: "image/png" }).arrayBuffer());
}

function pngChunk(type: string, data: Uint8Array): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(data.length + 12);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, data.length);
  bytes.set(new TextEncoder().encode(type), 4);
  bytes.set(data, 8);
  let crc = 0xffffffff;
  for (const byte of bytes.subarray(4, data.length + 8)) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  view.setUint32(data.length + 8, (crc ^ 0xffffffff) >>> 0);
  return bytes;
}
