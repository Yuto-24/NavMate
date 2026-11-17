import { createPortal } from "react-dom";
import type { Dispatch, SetStateAction } from "react";
import { emptyCheckPointDraft as initialDraft } from "../applicationSession";
import type { CheckPointDraft as Draft } from "../applicationSession";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import type {
  CheckPointInput,
  CheckPointPlanning,
  NavSection,
  RouteNode,
  VisualReference,
} from "../types";
import { pointAbeamDistanceToSegmentNm } from "../vorRadial";

const MAX_LINKED_LEG_DISTANCE_NM = 10;

interface PickedCoordinate {
  latitude: number;
  longitude: number;
  revision: number;
}

interface CheckPointEditorProps {
  slots?: Record<string, HTMLElement>;
  draft: Draft;
  setDraft: Dispatch<SetStateAction<Draft>>;
  nodes: RouteNode[];
  sections: NavSection[];
  checkPoints: VisualReference[];
  planning: CheckPointPlanning;
  busy: boolean;
  pickedCoordinate: PickedCoordinate | null;
  pickingFromMap: boolean;
  onPickingFromMapChange: (active: boolean) => void;
  onPickedCoordinateClear: () => void;
  onReplace: (checkPoints: CheckPointInput[]) => Promise<boolean>;
}

export function CheckPointEditor({
  slots,
  draft, setDraft,
  nodes,
  sections,
  checkPoints,
  planning,
  busy,
  pickedCoordinate,
  onPickingFromMapChange,
  onPickedCoordinateClear,
  onReplace,
}: CheckPointEditorProps) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const composingRef = useRef(false);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const focusedCoordinateRef = useRef<PickedCoordinate | null>(null);
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const projectionById = useMemo(() => new Map(planning.projections.map(item => [item.checkpoint_id, item])), [planning.projections]);
  const issueById = useMemo(() => {
    const grouped = new Map<string, string[]>();
    planning.issues.forEach((issue) => {
      if (!issue.checkPointId) return;
      grouped.set(issue.checkPointId, [...(grouped.get(issue.checkPointId) ?? []), issue.message]);
    });
    return grouped;
  }, [planning.issues]);
  const latitude = Number(draft.latitude);
  const longitude = Number(draft.longitude);
  const coordinatesValid =
    draft.latitude.trim() !== "" &&
    Number.isFinite(latitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    draft.longitude.trim() !== "" &&
    Number.isFinite(longitude) &&
    longitude >= -180 &&
    longitude <= 180;
  const matchingSections = useMemo(() => {
    if (!coordinatesValid) return [];
    const point = { latitude_deg: latitude, longitude_deg: longitude };
    return sections.filter((section) => {
      const start = nodeById.get(section.from_node_id);
      const end = nodeById.get(section.to_node_id);
      if (!start || !end) return false;
      const abeamDistanceNm = pointAbeamDistanceToSegmentNm(point, start, end);
      return abeamDistanceNm !== null && abeamDistanceNm <= MAX_LINKED_LEG_DISTANCE_NM;
    });
  }, [coordinatesValid, latitude, longitude, nodeById, sections]);
  const selectedLegMatches = matchingSections.some(section => section.id === draft.linkedSectionId);
  const effectiveLinkedSectionId = slots
    ? selectedLegMatches ? draft.linkedSectionId : ""
    : matchingSections.length === 1 ? matchingSections[0]!.id
      : selectedLegMatches ? draft.linkedSectionId : "";

  useEffect(() => {
    if (!pickedCoordinate) return;
    setDraft((current) => ({
      ...current,
      latitude: pickedCoordinate.latitude.toFixed(6),
      longitude: pickedCoordinate.longitude.toFixed(6),
    }));
    setEditorOpen(true);
    onPickingFromMapChange(false);
  }, [pickedCoordinate, onPickingFromMapChange]);

  useEffect(() => {
    // Consume a MAP pick once, after the conditional form mounts. Ordinary
    // draft edits and manual focus changes must not retrigger this interaction.
    if (!editorOpen || !pickedCoordinate || focusedCoordinateRef.current === pickedCoordinate) return;
    const input = nameInputRef.current;
    if (!input) return;
    focusedCoordinateRef.current = pickedCoordinate;
    input.focus({ preventScroll: true });
    input.scrollIntoView({ block: "center", inline: "nearest" });
  }, [editorOpen, pickedCoordinate]);

  const reset = () => {
    setDraft(initialDraft());
    setEditorOpen(false);
    onPickingFromMapChange(false);
    onPickedCoordinateClear();
  };

  const inputs = checkPoints.map<CheckPointInput>((item) => ({
    id: item.id,
    name: item.name,
    latitude_deg: item.latitude_deg,
    longitude_deg: item.longitude_deg,
    linked_section_id: item.linked_section_id ?? "",
  }));

  const draftValid =
    Boolean(draft.name.trim() && effectiveLinkedSectionId) && coordinatesValid;
  const nameIsBlocking = Boolean(pickedCoordinate && !draft.name.trim());
  const submitLabel = draft.id
    ? saving ? "保存中…" : "保存"
    : saving ? "追加中…" : "追加";

  const save = async () => {
    if (!draftValid || busy || savingRef.current) return;
    // Lock synchronously: another key/click can arrive before React renders saving.
    savingRef.current = true;
    const updated: CheckPointInput = {
      ...(draft.id ? { id: draft.id } : {}),
      name: draft.name.trim(),
      latitude_deg: latitude,
      longitude_deg: longitude,
      linked_section_id: effectiveLinkedSectionId,
    };
    setSaving(true);
    try {
      const succeeded = await onReplace(
        draft.id
          ? inputs.map((item) => (item.id === draft.id ? updated : item))
          : [...inputs, updated],
      );
      if (succeeded) reset();
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const form = editorOpen ? (
        <div className={`checkpoint-form${draft.id ? "" : " is-adding"}`} role="form" aria-label={draft.id ? "チェックポイントを編集" : "チェックポイントを追加"}>
          <div className="checkpoint-form-heading">
            {draft.id && <strong>チェックポイントを編集</strong>}
            <button className="icon-button" type="button" onClick={reset} aria-label="編集を閉じる">
              <X aria-hidden="true" size={16} />
            </button>
          </div>
          <label className="checkpoint-name-field">
            <span>名称{!draft.id && "（必須）"}</span>
            <input
              ref={nameInputRef}
              aria-label="名称"
              aria-required="true"
              value={draft.name}
              maxLength={100}
              aria-invalid={nameIsBlocking || undefined}
              aria-describedby={draft.id && nameIsBlocking ? "checkpoint-name-warning" : undefined}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              onCompositionStart={() => { composingRef.current = true; }}
              onCompositionEnd={() => { composingRef.current = false; }}
              onBlur={() => { composingRef.current = false; }}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                // Some IMEs end composition before the confirming keydown (keyCode 229).
                if (composingRef.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
                event.preventDefault();
                if (!event.repeat) void save();
              }}
              placeholder="例: 岩瀬ダム"
            />
            {draft.id && <small id="checkpoint-name-warning" className="checkpoint-name-status" role="status" aria-live="polite">
              {nameIsBlocking ? "チェックポイントの名称・未入力（入力必須）" : ""}
            </small>}
          </label>
          {(matchingSections.length > 1 || (coordinatesValid && !selectedLegMatches)) && (
            <label>
              <span>関連Leg</span>
              <select
                value={effectiveLinkedSectionId}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, linkedSectionId: event.target.value }))
                }
              >
                <option value="">Legを選択</option>
                {matchingSections.map((section) => {
                  const from = nodeById.get(section.from_node_id)?.name ?? "?";
                  const to = nodeById.get(section.to_node_id)?.name ?? "?";
                  return (
                    <option key={section.id} value={section.id}>
                      Leg {section.sequence + 1}: {from} → {to}（{section.phase}）
                    </option>
                  );
                })}
              </select>
            </label>
          )}
          <p id={!draft.id ? "checkpoint-name-warning" : undefined} className="checkpoint-leg-status" role="status" aria-live="polite">
            {coordinatesValid && matchingSections.length === 0
              ? "Leg線分内にabeam点があり、横ずれ10 NM以内となる関連Legがありません。"
              : coordinatesValid && slots && draft.linkedSectionId && !selectedLegMatches && matchingSections.length > 0
                ? "選択したLegの範囲外です。地図で選び直すか、関連Legを選択してください。" : ""}
          </p>
          <div className="checkpoint-form-actions">
            <button
              className="primary-button"
              type="button"
              disabled={!draftValid || saving || busy}
              onClick={() => void save()}
            >
              {submitLabel}
            </button>
          </div>
        </div>
      ) : null;

  const renderRow = (item: VisualReference) => {
    const messages = issueById.get(item.id) ?? [];
    return (
              <article className={`checkpoint-item${messages.length ? " has-error" : ""}`} key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  {projectionById.get(item.id) && <span>Leg内 {projectionById.get(item.id)!.along_section_distance_nm.toFixed(1)} NM</span>}
                  {messages.map((message) => <em key={message}>{message}</em>)}
                </div>
                <div className="checkpoint-item-actions">
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={`${item.name}を編集`}
                    disabled={busy}
                    onClick={() => {
                      onPickedCoordinateClear();
                      onPickingFromMapChange(false);
                      setDraft({
                        id: item.id,
                        name: item.name,
                        latitude: String(item.latitude_deg),
                        longitude: String(item.longitude_deg),
                        linkedSectionId: item.linked_section_id ?? "",
                      });
                      setEditorOpen(true);
                    }}
                  >
                    <Pencil aria-hidden="true" size={15} />
                  </button>
                  <button
                    className="icon-button danger-icon-button"
                    type="button"
                    aria-label={`${item.name}を削除`}
                    onClick={() => {
                      if (!window.confirm(`チェックポイント「${item.name}」を削除しますか？`)) return;
                      void onReplace(inputs.filter((candidate) => candidate.id !== item.id));
                    }}
                    disabled={busy}
                  >
                    <Trash2 aria-hidden="true" size={15} />
                  </button>
                </div>
              </article>
            );
  };
  const sorted = [...checkPoints].sort((a, b) => (projectionById.get(a.id)?.along_section_distance_nm ?? Infinity) - (projectionById.get(b.id)?.along_section_distance_nm ?? Infinity));
  return (
    <section className="checkpoint-editor" aria-label="チェックポイント設定">
      {!slots && <div className="section-heading-row">
        <div>
          <h3>チェックポイント</h3>
        </div>
        <button
          className="secondary-button checkpoint-add-button"
          type="button"
          aria-label="チェックポイントを追加"
          onClick={() => {
            onPickedCoordinateClear();
            setDraft(initialDraft());
            setEditorOpen(true);
            onPickingFromMapChange(true);
          }}
          disabled={busy || !sections.length}
        >
          <Plus aria-hidden="true" size={16} />
          CPを追加
        </button>
      </div>}


      {!editorOpen && (draft.name || draft.latitude || draft.longitude) && (
        <button className="secondary-button" onClick={() => { setEditorOpen(true); if (!draft.id) onPickingFromMapChange(true); }}>チェックポイントの編集を続ける</button>
      )}
      {form && !slots?.[draft.linkedSectionId] && form}
      <div className="checkpoint-list">
        {sorted.filter(item => !item.linked_section_id || !slots?.[item.linked_section_id]).map(renderRow)}
      </div>
      {slots && sections.map(section => {
        const target = slots[section.id];
        return target ? createPortal(<>
          {sorted.filter(item => item.linked_section_id === section.id).map(renderRow)}
          {draft.linkedSectionId === section.id && form}
          <button type="button" className="icon-button checkpoint-inline-add" aria-label={`${section.sequence + 1}番目のLegへ地図からチェックポイントを追加`} title="CPを追加" disabled={busy} onClick={() => {
            onPickedCoordinateClear();
            setDraft({ ...initialDraft(), linkedSectionId: section.id });
            setEditorOpen(true);
            onPickingFromMapChange(true);
          }}><Plus aria-hidden="true" size={13} /><span>CPを追加</span></button>
        </>, target, section.id) : null;
      })}
    </section>
  );
}
