import { Clock3 } from "lucide-react";
import { useId, useRef, useState, type PointerEvent } from "react";
import "./Time24Picker.css";

interface Time24PickerProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}
const two = (n: number) => String(n).padStart(2, "0");
const validTime = (value: string) => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);

/** A dialog edits a temporary value; only confirmation updates the planning form. */
export function Time24Picker({ value, onChange, disabled = false }: Time24PickerProps) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [hour, setHour] = useState(0);
  const [minute, setMinute] = useState(0);
  const [mode, setMode] = useState<"hour" | "minute">("hour");
  const [dragging, setDragging] = useState(false);
  const close = () => { dialog.current?.close(); trigger.current?.focus(); };
  const open = () => {
    const [h, m] = validTime(value) ? value.split(":").map(Number) : [0, 0];
    setHour(h ?? 0); setMinute(m ?? 0); setMode("hour"); setDragging(false);
    dialog.current?.showModal();
  };
  const pick = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const dx = event.clientX - bounds.left - bounds.width / 2;
    const dy = event.clientY - bounds.top - bounds.height / 2;
    const angle = (Math.atan2(dx, -dy) + Math.PI * 2) % (Math.PI * 2);
    if (mode === "minute") setMinute(Math.round(angle / (Math.PI * 2) * 60) % 60);
    else {
      const slot = Math.round(angle / (Math.PI * 2) * 12) % 12;
      const inner = Math.hypot(dx, dy) < bounds.width * .33;
      setHour(inner ? (slot === 0 ? 0 : slot + 12) : (slot === 0 ? 12 : slot));
    }
  };
  const selected = mode === "hour" ? hour : minute;
  const angle = (mode === "hour" ? hour % 12 / 12 : minute / 60) * 360;
  const inner = mode === "hour" && (hour === 0 || hour > 12);
  const values = mode === "hour" ? Array.from({ length: 24 }, (_, i) => i) : Array.from({ length: 12 }, (_, i) => i * 5);
  return <div className="flight-time-field time24-field">
    <label htmlFor={`${id}-input`}>ETD JST</label>
    <div className="time24-input-row">
      <input id={`${id}-input`} type="text" inputMode="text" placeholder="HH:mm" maxLength={5}
        pattern="(?:[01][0-9]|2[0-3]):[0-5][0-9]" value={value} disabled={disabled}
        onChange={event => onChange(event.target.value)} />
      <button ref={trigger} className="time24-trigger" type="button" aria-label="ETD を時計で選択"
        aria-haspopup="dialog" disabled={disabled} onClick={open}><Clock3 size={17} aria-hidden="true" /></button>
    </div>
    <dialog ref={dialog} className="time24-dialog" aria-labelledby={`${id}-title`}
      onCancel={() => { setDragging(false); }} onClose={() => { setDragging(false); trigger.current?.focus(); }}>
      <h2 id={`${id}-title`}>ETD JST の時刻選択</h2>
      <div className="time24-values">
        <button type="button" aria-label="時を選択" aria-pressed={mode === "hour"} onClick={() => setMode("hour")}>{two(hour)}</button>
        <span aria-hidden="true">:</span>
        <button type="button" aria-label="分を選択" aria-pressed={mode === "minute"} onClick={() => setMode("minute")}>{two(minute)}</button>
      </div>
      <div className="time24-dial" role="group" aria-label={mode === "hour" ? "時（24時間）" : "分"}
        onPointerDown={event => { if (event.target !== event.currentTarget) return; event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); pick(event); }}
        onPointerMove={event => { if (dragging) pick(event); }}
        onPointerUp={event => { if (!dragging) return; pick(event); setDragging(false); if (mode === "hour") setMode("minute"); }}
        onPointerCancel={() => setDragging(false)}>
        <span className="time24-hand" aria-hidden="true" style={{ height: inner ? "26%" : "40%", transform: `rotate(${angle}deg)` }} />
        {values.map(n => {
          const fraction = mode === "hour" ? n % 12 / 12 : n / 60;
          const radius = mode === "hour" && (n === 0 || n > 12) ? 26 : 40;
          const theta = fraction * Math.PI * 2;
          return <button key={n} type="button" className="time24-tick" aria-label={`${two(n)}${mode === "hour" ? "時" : "分"}`}
            data-tick={n} tabIndex={n === (mode === "minute" ? Math.floor(selected / 5) * 5 : selected) ? 0 : -1} aria-pressed={selected === n} style={{ left: `${50 + Math.sin(theta) * radius}%`, top: `${50 - Math.cos(theta) * radius}%` }}
            onClick={() => { if (mode === "hour") { setHour(n); setMode("minute"); } else setMinute(n); }}
            onKeyDown={event => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (mode === "hour") setMode("minute");
                return;
              }
              if (!["ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft"].includes(event.key)) return;
              event.preventDefault(); const delta = event.key === "ArrowUp" || event.key === "ArrowRight" ? 1 : -1;
              const next = mode === "hour" ? (hour + delta + 24) % 24 : (minute + delta + 60) % 60;
              if (mode === "hour") setHour(next); else setMinute(next);
              const tick = mode === "hour" ? next : Math.floor(next / 5) * 5;
              event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-tick="${tick}"]`)?.focus();
            }}>{two(n)}</button>;
        })}
      </div>
      <div className="time24-exact-inputs">
        <label>時<input aria-label="ETD の時" type="number" inputMode="numeric" min={0} max={23} value={hour}
          onChange={event => { const n = event.target.valueAsNumber; if (Number.isInteger(n) && n >= 0 && n <= 23) setHour(n); }} /></label>
        <label>分<input aria-label="ETD の分" type="number" inputMode="numeric" min={0} max={59} value={minute}
          onChange={event => { const n = event.target.valueAsNumber; if (Number.isInteger(n) && n >= 0 && n <= 59) setMinute(n); }} /></label>
      </div>
      <div className="time24-actions">
        <button type="button" className="secondary-button" onClick={close}>キャンセル</button>
        <button type="button" className="primary-button" disabled={disabled} onClick={() => { onChange(`${two(hour)}:${two(minute)}`); close(); }}>確定</button>
      </div>
    </dialog>
  </div>;
}
