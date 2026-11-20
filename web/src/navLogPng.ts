import type { PlatformFile } from "./platform";

// Use the browser's table layout and Canvas text, without SVG foreignObject or
// remote image/font fetching. Only the two paper tables enter this clean copy.
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
      cell.textContent = cell.dataset.displayText ?? "";
    });
    table.querySelectorAll<HTMLElement>("[data-png-text]").forEach(cell => {
      cell.textContent = cell.dataset.pngText ?? "";
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
    await document.fonts.ready;
    const bounds = paper.getBoundingClientRect();
    // Preserve row order even for long routes: add white width for landscape,
    // never split or crop rows. Bound the bitmap for mobile canvas memory.
    const width = Math.ceil(Math.max(bounds.width, bounds.height * 1.25));
    const height = Math.ceil(bounds.height);
    const scale = Math.min(2, 4096 / width, 4096 / height);
    canvas.width = Math.ceil(width * scale);
    canvas.height = Math.ceil(height * scale);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas unavailable");
    context.scale(scale, scale);
    context.fillStyle = "white";
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "black";
    context.fillStyle = "black";
    for (const cell of paper.querySelectorAll<HTMLElement>("th, td")) {
      const rect = cell.getBoundingClientRect();
      context.lineWidth = 1;
      context.strokeRect(rect.left - bounds.left, rect.top - bounds.top, rect.width, rect.height);
    }
    const walker = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    // Range rectangles retain wrapped Japanese names and the fuel table's spans.
    // Group characters on the same line so the browser/canvas can apply kerning.
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      if (!node.textContent?.trim() || !node.parentElement) continue;
      const style = getComputedStyle(node.parentElement);
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      context.textBaseline = "alphabetic";
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
        const text = node.data.slice(start, end);
        const metrics = context.measureText(text);
        const ascent = metrics.fontBoundingBoxAscent ?? parseFloat(style.fontSize) * 0.9;
        const descent = metrics.fontBoundingBoxDescent ?? parseFloat(style.fontSize) * 0.2;
        context.fillText(text, first.left - bounds.left,
          first.top - bounds.top + (first.height - ascent - descent) / 2 + ascent);
        start = end;
      }
    }
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      value => value ? resolve(value) : reject(new Error("PNG encoding failed")), "image/png",
    ));
    return { name: "NAVLOG.png", mediaType: "image/png", content: new Uint8Array(await blob.arrayBuffer()) };
  } finally {
    paper.remove();
    canvas.width = 0;
    canvas.height = 0;
  }
}
