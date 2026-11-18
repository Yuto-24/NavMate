// Runs in the page, including before the first React render.
export function observeStartupProgress() {
  const values: number[] = [], frames: { percent: number; workspace: boolean }[] = [];
  Object.assign(window, { startupProgressValues: values, startupProgressFrames: frames });
  new MutationObserver(records => {
    const changed = new Set<HTMLProgressElement>();
    for (const record of records) {
      if (record.type === "attributes" && record.target instanceof HTMLProgressElement
        && record.target.classList.contains("startup-progress")) {
        // Reading target.value for every record loses intermediate regressions.
        if (record.oldValue !== null) values.push(Number(record.oldValue));
        changed.add(record.target);
      }
    }
    for (const bar of changed) values.push(bar.value);
    const bar = document.querySelector<HTMLProgressElement>(".startup-progress");
    if (bar && !changed.has(bar)) values.push(bar.value);
  }).observe(document, { childList: true, subtree: true, attributes: true,
    attributeFilter: ["value"], attributeOldValue: true });
  const sampleFrame = () => {
    const bar = document.querySelector<HTMLProgressElement>(".startup-progress");
    if (bar) frames.push({ percent: bar.value, workspace: !!document.querySelector(".map-frame") });
    requestAnimationFrame(sampleFrame);
  };
  requestAnimationFrame(sampleFrame);
}
