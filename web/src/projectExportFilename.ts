// Name exports by their creation time in JST, independently of the flight date.
export function projectExportFilename(projectName: string, extension: "json" | "png", at = new Date()): string {
  const name = projectName.replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, "_")
    .trim().replace(/[. ]+$/, "") || "プロジェクト";
  if (extension === "png") return `NAVLOG_${name}.png`;
  const jst = new Date(at.getTime() + 9 * 60 * 60 * 1000).toISOString();
  const timestamp = `${jst.slice(0, 10).replaceAll("-", "")}-${jst.slice(11, 16).replace(":", "")}`;
  return `${name}_${timestamp}.${extension}`;
}
