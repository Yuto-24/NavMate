import { useRef } from "react";
import { FileUp } from "lucide-react";

export function ProjectFileInput({ busy, onFile }: {
  busy: boolean;
  onFile: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="project-file-control">
      <button className="secondary-button full-width" type="button" disabled={busy}
        onClick={() => input.current?.click()}>
        <FileUp aria-hidden="true" size={17} />
        JSONファイルから追加
      </button>
      <input ref={input} type="file" hidden
        aria-hidden="true" aria-label="JSONファイルから追加" accept=".json,application/json" disabled={busy}
        onChange={event => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onFile(file);
        }} />
    </div>
  );
}
