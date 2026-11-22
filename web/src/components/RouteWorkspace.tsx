import { AipAirspaceControl, AipAirspaceLayers } from "./AipAirspace";
import { aipCategories, aipPreferenceKey, loadAipAirspace, type AipAirspace } from "../aipAirspace";
import { Maximize, Minimize, Pencil } from "lucide-react";
import { MapDraftLayers, RouteStrip, type MapRouteBuilderProps } from "./MapRouteBuilder";
import { MapViewport } from "./MapViewport";
import { MapBackground } from "./MapBackground";
import type { KeyValueStorage } from "../platform";
import type { Dispatch, SetStateAction, ReactNode } from "react";
import type { CheckPointDraft, NodeNameDraft } from "../applicationSession";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Polygon,
  Polyline,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import { patternAltitudeFtMsl } from "../forms";
import {
  fetchRjfmTrainingAirspace,
  isApprovedRjfmAirspaceReference,
  type RjfmTrainingAirspaceBoundary,
  type RjfmTrainingAirspacePolygon,
} from "../rjfmAirspace";
import type {
  AltitudeGuidance,
  AltitudeInputMode,
  AirportOption,
  CalculationOutcome,
  CheckPointInput,
  CheckPointPlanning,
  FlightPhase,
  NavSection,
  Project,
  RjfmMapReference,
  RouteCandidate,
} from "../types";
import { CheckPointEditor } from "./CheckPointEditor";
import { rjfmCandidateClass, rjfmStatusLabels } from "./RjfmGuidancePanel";
import { RouteConfirmation } from "./RouteConfirmation";
import "./RouteWorkspacePhase.css";
import { localMode } from "../executionMode";

function MapAttributionLayout() {
  const map = useMap();
  useEffect(() => {
    const attribution = map.attributionControl?.getContainer();
    const frame = map.getContainer().closest<HTMLElement>(".map-frame");
    if (!attribution || !frame) return;
    const updateHeight = () => frame.style.setProperty(
      "--map-attribution-height", `${attribution.getBoundingClientRect().height}px`,
    );
    const observer = new ResizeObserver(updateHeight);
    observer.observe(attribution);
    updateHeight();
    return () => {
      observer.disconnect();
      frame.style.removeProperty("--map-attribution-height");
    };
  }, [map]);
  return null;
}

interface RouteWorkspaceProps {
  planningPanel?: ReactNode;
  readinessPanel?: ReactNode;
  mapBuilder?: MapRouteBuilderProps;
  onEditRoute?: () => void;
  viewportStorage: KeyValueStorage;
  viewportScope: string;
  preserveRouteViewport: boolean;
  onOpenExternalUrl: (url: string) => void;
  checkPointDraft: CheckPointDraft;
  setCheckPointDraft: Dispatch<SetStateAction<CheckPointDraft>>;
  nodeNameDraft: NodeNameDraft;
  setNodeNameDraft: Dispatch<SetStateAction<NodeNameDraft>>;
  candidate: RouteCandidate | null;
  project: Project | null;
  outcome: CalculationOutcome | null;
  calculationIsCurrent: boolean;
  altitudeGuidance: AltitudeGuidance;
  rjfmMapReference: RjfmMapReference | null;
  altitudeInputs: Record<string, string>;
  destinationAirport: AirportOption | null;
  destinationPatternAltitudeFtMsl: string;
  checkPointPlanning: CheckPointPlanning;
  busy: boolean;
  routeUseConfirmed: boolean;
  polygonRouteConfirmed: boolean;
  canConfirmRoute: boolean;
  onAltitudeInputChange: (sectionId: string, value: string) => void;
  onDestinationPatternAltitudeChange: (value: string) => void;
  onSectionChange: (
    sectionId: string,
    changes: Partial<NavSection>,
    invalidate?: boolean,
  ) => void;
  onRenameRouteNode: (nodeId: string, name: string) => Promise<void>;
  onRouteUseConfirmedChange: (checked: boolean) => void;
  onPolygonRouteConfirmedChange: (checked: boolean) => void;
  onConfirmRoute: () => void;
  onReplaceCheckPoints: (checkPoints: CheckPointInput[]) => Promise<boolean>;
}

const phaseLabels: Record<FlightPhase, string> = {
  CLIMB: "上昇",
  CRUISE: "巡航",
  DESCENT: "降下",
  VISUAL_ARRIVAL: "場周進入",
};

const altitudeBasisLabels: Record<FlightPhase, string> = {
  CLIMB: "上昇先の巡航高度",
  CRUISE: "このLegの巡航高度",
  DESCENT: "降下開始時の巡航高度",
  VISUAL_ARRIVAL: "場周進入の計画高度",
};

function isFixedAltitudeMode(inputMode: AltitudeInputMode | undefined): boolean {
  return inputMode !== undefined && inputMode !== "EDITABLE";
}

function fixedAltitudeLabels(
  inputMode: AltitudeInputMode,
  altitudeFtMsl: number,
): { primary: string; detail: string; phase: string } {
  const altitude = altitudeFtMsl.toLocaleString("ja-JP");
  if (inputMode === "RJFM_DEPARTURE_TO_UMK_FIXED") {
    return {
      primary: `UMK ${altitude} ft HIT`,
      detail: "RJFM→UMKの到達条件（固定）",
      phase: "上昇（固定）",
    };
  }
  if (inputMode === "RJFM_UMK_TO_OMARU_FIXED") {
    return {
      primary: `${altitude} ft 固定`,
      detail: "UMK→OMARUの巡航高度",
      phase: "巡航（固定）",
    };
  }
  if (inputMode === "RJFM_INBOUND_OMARU_TO_UMK_FIXED") {
    return {
      primary: `${altitude} ft 固定`,
      detail: "RJFM帰路 OMARU→UMKの到達高度",
      phase: "巡航（固定）",
    };
  }
  if (inputMode === "RJFM_INBOUND_UMK_TO_ARITA_FIXED") {
    return {
      primary: `${altitude} - 1,500 ft 固定`,
      detail: "UMK→ARITA専用降下経路の指定高度",
      phase: "降下（固定）",
    };
  }
  return {
    primary: `UMK ${altitude} ft HIT`,
    detail: `RJFM→OMARU親Leg内・OMARUまで${altitude} ft固定`,
    phase: "上昇→UMK/RCA→巡航（固定）",
  };
}

const centerRoutePointLabels = ["UMK", "OVER FIELD", "OMARU"] as const;

type TrainingAirspaceState =
  | { status: "idle" | "loading" | "unavailable"; polygons: []; boundaries: [] }
  | {
      status: "ready";
      polygons: RjfmTrainingAirspacePolygon[];
      boundaries: RjfmTrainingAirspaceBoundary[];
    };

function FitBounds({
  coordinates,
  signature,
}: {
  coordinates: [number, number][];
  signature: string;
}) {
  const map = useMap();
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      map.invalidateSize({ animate: false });
      if (coordinates.length >= 2) {
        map.fitBounds(coordinates as LatLngBoundsExpression, { padding: [28, 28] });
      } else if (coordinates.length === 1 && coordinates[0]) {
        map.setView(coordinates[0], 10);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [map, signature]);
  return null;
}

function CheckPointMapPicker({
  active,
  onPick,
}: {
  active: boolean;
  onPick: (latitude: number, longitude: number) => void;
}) {
  useMapEvents({
    click(event) {
      if (active) onPick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

export function RouteWorkspace({
  planningPanel, readinessPanel,
  mapBuilder, onEditRoute, viewportStorage, viewportScope, preserveRouteViewport,
  onOpenExternalUrl,
  checkPointDraft, setCheckPointDraft, nodeNameDraft: nodeDraft, setNodeNameDraft: setNodeDraft,
  candidate,
  project,
  outcome,
  calculationIsCurrent,
  altitudeGuidance,
  rjfmMapReference,
  altitudeInputs,
  destinationAirport,
  destinationPatternAltitudeFtMsl,
  checkPointPlanning,
  busy,
  routeUseConfirmed,
  polygonRouteConfirmed,
  canConfirmRoute,
  onAltitudeInputChange,
  onDestinationPatternAltitudeChange,
  onSectionChange,
  onRenameRouteNode,
  onRouteUseConfirmedChange,
  onPolygonRouteConfirmedChange,
  onConfirmRoute,
  onReplaceCheckPoints,
}: RouteWorkspaceProps) {
  // Device preference: deliberately outside Project, account scope and calculation data.
  const [mapBackground, setMapBackground] = useState(() => {
    try { return viewportStorage.getItem("autonavlog.map-background.v1") === "imagery" ? "imagery" : "map"; }
    catch { return "map"; }
  });
  const [aip, setAip] = useState<AipAirspace | null>(null);
  const [aipFailed, setAipFailed] = useState(false);
  const [hiddenAip, setHiddenAip] = useState<string[]>(() => {
    try {
      const value: unknown = JSON.parse(viewportStorage.getItem(aipPreferenceKey) ?? "[]");
      return Array.isArray(value) ? value.filter((id): id is string => aipCategories.some(([known]) => known === id)) : [];
    } catch { return []; }
  });
  useEffect(() => {
    if (!localMode) return;
    let active = true;
    void loadAipAirspace().then(data => { if (active) setAip(data); })
      .catch(() => { if (active) setAipFailed(true); });
    return () => { active = false; };
  }, []);
  const toggleAip = (id: string) => {
    const next = hiddenAip.includes(id) ? hiddenAip.filter(value => value !== id) : [...hiddenAip, id];
    setHiddenAip(next);
    try { viewportStorage.setItem(aipPreferenceKey, JSON.stringify(next)); } catch { /* Device storage may be blocked. */ }
  };
  const [pickingCheckPoint, setPickingCheckPoint] = useState(false);
  const [phaseEditing, setPhaseEditing] = useState(false);
  const [customAltitudeSections, setCustomAltitudeSections] = useState<Record<string, boolean>>({});
  const [legendOpen, setLegendOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const routeBuilding = Boolean(mapBuilder);
  useEffect(() => { if (!routeBuilding) setFullscreen(false); }, [routeBuilding]);
  const mapFrameRef = useRef<HTMLDivElement>(null);
  const fullscreenButtonRef = useRef<HTMLButtonElement>(null);
  const [checkpointSlots, setCheckpointSlots] = useState<Record<string, HTMLElement>>({});
  const registerCheckpointSlot = useCallback((id: string, element: HTMLDivElement | null) => {
    setCheckpointSlots(current => {
      if (current[id] === element || (!element && !current[id])) return current;
      const next = { ...current };
      if (element) next[id] = element; else delete next[id];
      return next;
    });
  }, []);
  useEffect(() => {
    if (!fullscreen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = mapFrameRef.current!;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setFullscreen(false); }
      if (event.key !== "Tab") return;
      const focusable = Array.from(frame.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], select, input:not(:disabled), [tabindex="0"]'));
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !frame.contains(document.activeElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !frame.contains(document.activeElement))) {
        event.preventDefault(); first?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    fullscreenButtonRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
      fullscreenButtonRef.current?.focus({ preventScroll: true });
    };
  }, [fullscreen]);
  const editingNodeId = nodeDraft.id;
  const nodeNameDraft = nodeDraft.name;
  const setEditingNodeId = (id: string | null) => setNodeDraft(current => ({ ...current, id }));
  const setNodeNameDraft = (name: string) => setNodeDraft(current => ({ ...current, name }));
  const [nodeNameError, setNodeNameError] = useState<string | null>(null);
  const [nodeNameSaving, setNodeNameSaving] = useState(false);
  const [pickedCoordinate, setPickedCoordinate] = useState<{
    latitude: number;
    longitude: number;
    revision: number;
  } | null>(null);
  const [trainingAirspace, setTrainingAirspace] = useState<TrainingAirspaceState>({
    status: "idle",
    polygons: [],
    boundaries: [],
  });
  const parsedPatternAltitude = patternAltitudeFtMsl(
    destinationPatternAltitudeFtMsl,
  );
  const patternAltitudeBelowAirport = (
    parsedPatternAltitude !== null &&
    destinationAirport !== null &&
    parsedPatternAltitude <= destinationAirport.elevationFtMsl
  );
  const validPatternAltitude = patternAltitudeBelowAirport
    ? null
    : parsedPatternAltitude;
  const nodes = useMemo(
    () => [...(project?.route_nodes ?? [])].sort((a, b) => a.sequence - b.sequence),
    [project],
  );
  const sections = useMemo(
    () => [...(project?.sections ?? [])].sort((a, b) => a.sequence - b.sequence),
    [project],
  );
  const nodeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );
  const sectionByFromNode = useMemo(
    () => new Map(sections.map((section) => [section.from_node_id, section])),
    [sections],
  );
  const guidanceBySection = useMemo(
    () =>
      new Map(
        altitudeGuidance.sections.map((guidance) => [guidance.sectionId, guidance]),
      ),
    [altitudeGuidance.sections],
  );
  useEffect(() => {
    setPhaseEditing(false);
    setNodeNameError(null);
  }, [project?.id]);
  const cancelNodeNameEdit = () => {
    if (nodeNameSaving) return;
    setEditingNodeId(null);
    setNodeNameDraft("");
    setNodeNameError(null);
  };
  const saveNodeNameEdit = async () => {
    if (!editingNodeId || nodeNameSaving) return;
    const name = nodeNameDraft.trim();
    if (!name) {
      setNodeNameError("名称を入力してください。");
      return;
    }
    setNodeNameSaving(true);
    setNodeNameError(null);
    try {
      await onRenameRouteNode(editingNodeId, name);
      setEditingNodeId(null);
      setNodeNameDraft("");
    } catch (reason) {
      setNodeNameError(
        reason instanceof Error ? reason.message : "名称を保存できませんでした。",
      );
    } finally {
      setNodeNameSaving(false);
    }
  };
  const isPhaseLocked = useCallback(
    (section: NavSection): boolean => {
      const guidance = guidanceBySection.get(section.id);
      const startNode = nodeById.get(section.from_node_id);
      return (
        isFixedAltitudeMode(guidance?.inputMode) ||
        section.phase === "VISUAL_ARRIVAL" ||
        startNode?.role === "VISUAL_REPORTING_POINT"
      );
    },
    [guidanceBySection, nodeById],
  );
  const currentClimbSection = sections.find((section) => section.phase === "CLIMB") ?? null;
  const currentDescentSection = sections.find((section) => section.phase === "DESCENT") ?? null;
  const calculatedDescentRate = outcome?.sections
    .find((section) => section.phase === "DESCENT")
    ?.performance_metadata.descent_rate_fpm;
  const displayedDescentRate =
    typeof calculatedDescentRate === "number" &&
    (calculatedDescentRate === 500 || calculatedDescentRate === 1000)
      ? calculatedDescentRate
      : null;
  const fixedClimbExists = Boolean(currentClimbSection && isPhaseLocked(currentClimbSection));
  const fixedDescentExists = Boolean(currentDescentSection && isPhaseLocked(currentDescentSection));
  const hasEditablePhaseSections = sections.some((section) => !isPhaseLocked(section));
  const phaseOptionsForSection = (section: NavSection): FlightPhase[] => {
    const options: FlightPhase[] = [];
    const canBeClimb =
      (!fixedClimbExists || section.phase === "CLIMB") &&
      (currentDescentSection === null ||
        section.sequence < currentDescentSection.sequence ||
        section.phase === "CLIMB");
    const canBeDescent =
      (!fixedDescentExists || section.phase === "DESCENT") &&
      (currentClimbSection === null ||
        section.sequence > currentClimbSection.sequence ||
        section.phase === "DESCENT");
    if (canBeClimb) options.push("CLIMB");
    options.push("CRUISE");
    if (canBeDescent) options.push("DESCENT");
    return options;
  };
  const changePhaseBasis = (section: NavSection, nextPhase: FlightPhase) => {
    if (!phaseEditing || isPhaseLocked(section) || nextPhase === "VISUAL_ARRIVAL") return;
    if (nextPhase === "CLIMB" || nextPhase === "DESCENT") {
      const duplicates = sections.filter(
        (candidate) =>
          candidate.id !== section.id &&
          candidate.phase === nextPhase &&
          !isPhaseLocked(candidate),
      );
      duplicates.forEach((candidate) =>
        onSectionChange(candidate.id, { phase: "CRUISE" }, false),
      );
      if (section.phase !== nextPhase || duplicates.length > 0) {
        onSectionChange(section.id, { phase: nextPhase });
      }
      return;
    }
    if (section.phase !== "CRUISE") {
      onSectionChange(section.id, { phase: "CRUISE" });
    }
  };
  const checkPoints = useMemo(
    () => (project?.visual_references ?? []).filter((item) => item.role === "CHECK_POINT"),
    [project],
  );
  const rjfmGuidance = calculationIsCurrent
    ? outcome?.rjfm_departure_guidance ?? null
    : null;
  const visibleRjfmCandidates = useMemo(
    () => (rjfmGuidance?.candidates ?? []).filter(
      (item) => item.status !== "UNAVAILABLE" && item.path.length >= 2,
    ),
    [rjfmGuidance],
  );
  const civilAirspaceReference = rjfmMapReference?.civilTrainingTestAirspace ?? null;
  const civilAirspaceReferenceIsApproved = civilAirspaceReference !== null
    && isApprovedRjfmAirspaceReference(civilAirspaceReference);
  // Only the strictly allowlisted source URLs enter Leaflet's HTML attribution.
  const airspaceAttribution = civilAirspaceReferenceIsApproved
    ? `<span class="rjfm-airspace-credit"><a data-airspace-source href="${civilAirspaceReference.sourcePageUrl}" target="_blank" rel="noopener noreferrer">国土交通省</a>・<a data-airspace-source href="${civilAirspaceReference.layerMetadataUrl}" target="_blank" rel="noopener noreferrer">国土地理院</a>データを加工</span>`
    : undefined;
  const civilAirspaceRequestKey = civilAirspaceReference === null
    ? ""
    : JSON.stringify({
        availability: civilAirspaceReference.availability,
        dataUse: civilAirspaceReference.dataUse,
        contentFingerprintScope: civilAirspaceReference.contentFingerprintScope,
        sourcePageUrl: civilAirspaceReference.sourcePageUrl,
        layerMetadataUrl: civilAirspaceReference.layerMetadataUrl,
        tileUrlTemplate: civilAirspaceReference.tileUrlTemplate,
        tiles: civilAirspaceReference.tiles,
        tileUrls: civilAirspaceReference.tileUrls,
        featureNamePrefix: civilAirspaceReference.featureNamePrefix,
      });
  useEffect(() => {
    if (localMode || civilAirspaceReference === null) {
      setTrainingAirspace({ status: "idle", polygons: [], boundaries: [] });
      return undefined;
    }
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8_000);
    setTrainingAirspace({ status: "loading", polygons: [], boundaries: [] });
    void fetchRjfmTrainingAirspace(civilAirspaceReference, controller.signal)
      .then(({ polygons, boundaries }) => {
        if (active) setTrainingAirspace({ status: "ready", polygons, boundaries });
      })
      .catch(() => {
        controller.abort();
        if (active) {
          setTrainingAirspace({ status: "unavailable", polygons: [], boundaries: [] });
        }
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [civilAirspaceRequestKey]);
  const pcaCoordinates = useMemo<[number, number][]>(
    () => (rjfmMapReference?.pca.polygonVertices ?? []).map((point) => [
      point.latitudeDeg,
      point.longitudeDeg,
    ]),
    [rjfmMapReference],
  );
  const pcaFitCoordinates = useMemo<[number, number][]>(
    () => rjfmMapReference === null
      ? []
      : [
          ...pcaCoordinates,
          [
            rjfmMapReference.pca.exclusionCenter.latitudeDeg,
            rjfmMapReference.pca.exclusionCenter.longitudeDeg,
          ],
        ],
    [pcaCoordinates, rjfmMapReference],
  );

  const coordinates = useMemo<[number, number][]>(
    () =>
      nodes.length
        ? nodes.map((node) => [node.latitude_deg, node.longitude_deg])
        : candidate?.coordinates ?? [],
    [candidate, nodes],
  );
  const coordinateSignature = useMemo(
    () =>
      [
        ...coordinates,
        ...checkPoints.map<[number, number]>((item) => [item.latitude_deg, item.longitude_deg]),
        ...checkPointPlanning.projections.map<[number, number]>((item) => [
          item.abeam_latitude_deg,
          item.abeam_longitude_deg,
        ]),
        ...(rjfmGuidance?.center_route ?? []).map<[number, number]>((item) => [
          item.latitude_deg,
          item.longitude_deg,
        ]),
        ...visibleRjfmCandidates.flatMap((item) =>
          item.path.map<[number, number]>((point) => [
            point.latitude_deg,
            point.longitude_deg,
          ]),
        ),
        ...pcaFitCoordinates,
      ].map(([latitude, longitude]) => `${latitude},${longitude}`).join(";"),
    [
      checkPointPlanning.projections,
      checkPoints,
      coordinates,
      pcaFitCoordinates,
      rjfmGuidance,
      visibleRjfmCandidates,
    ],
  );
  const fitCoordinates = useMemo<[number, number][]>(
    () => [
      ...coordinates,
      ...checkPoints.map<[number, number]>((item) => [item.latitude_deg, item.longitude_deg]),
      ...checkPointPlanning.projections.map<[number, number]>((item) => [
        item.abeam_latitude_deg,
        item.abeam_longitude_deg,
      ]),
      ...(rjfmGuidance?.center_route ?? []).map<[number, number]>((item) => [
        item.latitude_deg,
        item.longitude_deg,
      ]),
      ...visibleRjfmCandidates.flatMap((item) =>
        item.path.map<[number, number]>((point) => [
          point.latitude_deg,
          point.longitude_deg,
        ]),
      ),
      ...pcaFitCoordinates,
    ],
    [
      checkPointPlanning.projections,
      checkPoints,
      coordinates,
      pcaFitCoordinates,
      rjfmGuidance,
      visibleRjfmCandidates,
    ],
  );
  const projectionById = useMemo(
    () => new Map(checkPointPlanning.projections.map((item) => [item.checkpoint_id, item])),
    [checkPointPlanning.projections],
  );
  const handleMapPick = useCallback((latitude: number, longitude: number) => {
    setPickedCoordinate((current) => ({
      latitude,
      longitude,
      revision: (current?.revision ?? 0) + 1,
    }));
  }, []);
  const handlePickingChange = useCallback((active: boolean) => {
    setPickingCheckPoint(active);
  }, []);
  const clearPickedCoordinate = useCallback(() => {
    setPickedCoordinate(null);
  }, []);
  useEffect(() => {
    const workspace = document.querySelector<HTMLElement>(".app-workspace");
    if (!workspace) return;
    const update = () => workspace.style.setProperty("--workspace-top", `${workspace.getBoundingClientRect().top + window.scrollY}px`);
    const observer = new ResizeObserver(update);
    for (const sibling of Array.from(workspace.parentElement?.children ?? [])) {
      if (sibling === workspace) break;
      observer.observe(sibling);
    }
    const mutation = new MutationObserver(update);
    mutation.observe(workspace.parentElement!, {childList:true});
    window.addEventListener("resize", update);
    update();
    return () => { observer.disconnect(); mutation.disconnect(); window.removeEventListener("resize", update); };
  }, []);

  return (
    <section className={`route-workspace${mapBuilder ? " is-route-building" : ""}`} aria-label="経路地図とLeg設定">
      {mapBuilder && <div className="draft-mobile-heading"><h2>経路</h2><p>地図で経路を作成</p></div>}
      <div
        ref={mapFrameRef}
        id="route-map-frame"
        role={fullscreen ? "dialog" : undefined}
        aria-modal={fullscreen || undefined}
        aria-label={fullscreen ? "全画面の経路地図" : undefined}
        className={`map-frame${fullscreen ? " is-fullscreen" : ""}${pickingCheckPoint ? " is-picking-checkpoint" : ""}${localMode && mapBackground === "imagery" ? " is-imagery" : ""}`}
        onClickCapture={(event) => {
          const link = event.target instanceof Element
            ? event.target.closest<HTMLAnchorElement>("a[data-airspace-source]")
            : null;
          if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          onOpenExternalUrl(link.href);
        }}
      >
        <div className="map-toolbar">
          {localMode && <AipAirspaceControl data={aip} failed={aipFailed} hidden={hiddenAip} onChange={toggleAip} />}
      {localMode && <label className="map-background-picker">
        <span>背景地図</span>
        <select value={mapBackground} onChange={(event) => {
          const value = event.target.value;
          setMapBackground(value);
          try { viewportStorage.setItem("autonavlog.map-background.v1", value); }
          catch { /* A blocked preference store must not prevent switching the map. */ }
        }}>
          <option value="map">標準地図</option>
          <option value="imagery">衛星・空中写真</option>
        </select>
      </label>}
        {mapBuilder && <button ref={fullscreenButtonRef} type="button" className="map-fullscreen-toggle" disabled={busy && !fullscreen} aria-label={fullscreen ? "地図の全画面表示を終了" : "地図を全画面表示"} aria-pressed={fullscreen} onClick={() => setFullscreen(value => !value)}>
          {fullscreen ? <Minimize aria-hidden="true" size={18} /> : <Maximize aria-hidden="true" size={18} />}
        </button>}
        </div>
        {!mapBuilder && onEditRoute && <div className="map-route-edit"><button className="secondary-button" disabled={busy} onClick={onEditRoute}>経路を編集</button><span>{nodes.length}点 / {sections.length} Leg</span></div>}
        <MapContainer
          trackResize={false}
          // Local Account changes may unmount immediately; Leaflet zoom timers outlive remove().
          zoomAnimation={!localMode}
          center={[31.8772, 131.4486]}
          zoom={9}
          minZoom={0}
          maxZoom={localMode ? 19 : 18}
          scrollWheelZoom
          className="route-map"
          aria-label="飛行経路地図"
        >
          <MapBackground imagery={localMode && mapBackground === "imagery"} />
          <MapAttributionLayout />
          {localMode && aip && <AipAirspaceLayers data={aip} hidden={hiddenAip} />}
          {rjfmMapReference && pcaCoordinates.length >= 3 && (
            <>
              <Polygon
                className="rjfm-pca-boundary"
                positions={pcaCoordinates}
                pathOptions={{
                  color: "#a45b13",
                  fillColor: "#f2a43a",
                  fillOpacity: 0.12,
                  opacity: 0.95,
                  weight: 3,
                }}
              >
                <Tooltip sticky>
                  <span>
                    宮崎特別管制区（PCA）水平境界 / 原告示高度
                    {" "}約{Math.round(rjfmMapReference.pca.sourceAltitudeLowerM / 0.3048).toLocaleString("ja-JP")}
                    –{Math.round(rjfmMapReference.pca.sourceAltitudeUpperM / 0.3048).toLocaleString("ja-JP")} ft（{rjfmMapReference.pca.sourceAltitudeLowerM.toLocaleString("ja-JP")}
                    –{rjfmMapReference.pca.sourceAltitudeUpperM.toLocaleString("ja-JP")} m）
                    <br />
                    運用判定 {rjfmMapReference.pca.operationalAltitudeLowerFtMsl.toLocaleString("ja-JP")}
                    –{rjfmMapReference.pca.operationalAltitudeUpperFtMsl.toLocaleString("ja-JP")} ft MSL（利用者承認値）
                  </span>
                </Tooltip>
              </Polygon>
              <Circle
                className="rjfm-pca-exclusion"
                center={[
                  rjfmMapReference.pca.exclusionCenter.latitudeDeg,
                  rjfmMapReference.pca.exclusionCenter.longitudeDeg,
                ]}
                radius={rjfmMapReference.pca.exclusionRadiusKm * 1000}
                pathOptions={{
                  color: "#087b78",
                  dashArray: "7 6",
                  fillColor: "#ffffff",
                  fillOpacity: 0.68,
                  opacity: 0.95,
                  weight: 3,
                }}
              >
                <Tooltip sticky>
                  PCA中心除外 {rjfmMapReference.pca.exclusionRadiusKm.toLocaleString("ja-JP")} km
                  （国交省告示）
                </Tooltip>
              </Circle>
            </>
          )}
          {trainingAirspace.polygons.map((airspace) => (
            <Polygon
              key={airspace.id}
              className="rjfm-training-airspace"
              attribution={airspaceAttribution}
              interactive={false}
              positions={airspace.positions}
              pathOptions={{
                fillColor: "#5b83cf",
                fillOpacity: 0.1,
                stroke: false,
              }}
            />
          ))}
          {trainingAirspace.boundaries.map((boundary) => (
            <Polyline
              key={boundary.id}
              className="rjfm-training-airspace-boundary"
              attribution={airspaceAttribution}
              interactive={false}
              positions={boundary.positions}
              pathOptions={{
                color: "#315caa",
                opacity: 0.82,
                weight: 2,
              }}
            />
          ))}
          {!mapBuilder && coordinates.length >= 2 && (
            <Polyline positions={coordinates} pathOptions={{ color: "#173b5e", weight: 4 }} />
          )}
          {rjfmGuidance && rjfmGuidance.center_route.length >= 2 && (
            <Polyline
              className="rjfm-center-route"
              positions={rjfmGuidance.center_route.map<[number, number]>((point) => [
                point.latitude_deg,
                point.longitude_deg,
              ])}
              pathOptions={{
                color: "#287a45",
                dashArray: "8 6",
                opacity: 0.95,
                weight: 4,
              }}
            />
          )}
          {visibleRjfmCandidates.map((item) => (
            <Polyline
              key={`rjfm-path-${item.runway}`}
              className={`rjfm-guidance-path ${rjfmCandidateClass(item)}`}
              positions={item.path.map<[number, number]>((point) => [
                point.latitude_deg,
                point.longitude_deg,
              ])}
              pathOptions={{
                color: item.status === "HARD_INVALID"
                  ? "#b42318"
                  : item.runway === "09" ? "#2368a2" : "#6e4aa0",
                dashArray: item.status === "WARNING" ? "9 5" : undefined,
                opacity: item.status === "HARD_INVALID" ? 0.82 : 0.92,
                weight: item.status === "HARD_INVALID" ? 3 : 4,
              }}
            />
          ))}
          {rjfmGuidance?.center_route.map((point, index) => (
            <CircleMarker
              key={`rjfm-center-${point.latitude_deg}-${point.longitude_deg}`}
              className="rjfm-center-marker"
              center={[point.latitude_deg, point.longitude_deg]}
              radius={index === 1 ? 7 : 6}
              pathOptions={{
                color: "#1f663a",
                fillColor: "#effaf3",
                fillOpacity: 1,
                weight: 3,
              }}
            >
              <Tooltip direction="right" offset={[7, 0]}>
                {centerRoutePointLabels[index] ?? `CENTER ${index + 1}`}
              </Tooltip>
            </CircleMarker>
          ))}
          {!mapBuilder && nodes.map((node, index) => {
            const isVrep = node.role === "VISUAL_REPORTING_POINT" || node.reference_snapshot?.kind === "VISUAL_REPORTING_POINT";
            const isAirport = node.role === "AIRPORT" || node.role === "DESTINATION";
            return (
              <CircleMarker
                key={node.id}
                center={[node.latitude_deg, node.longitude_deg]}
                radius={isAirport ? 9 : isVrep ? 8 : 6}
                pathOptions={{
                  color: isVrep ? "#0c7c78" : "#0b1f33",
                  fillColor: isVrep ? "#0c7c78" : isAirport ? "#0b1f33" : "#ffffff",
                  fillOpacity: 1,
                  weight: 3,
                }}
              >
                <Tooltip permanent direction="top" offset={[0, -7]}>
                  {isVrep ? node.name + " (VREP)" : node.name}
                </Tooltip>
              </CircleMarker>
            );
          })}
          {outcome?.derived_points.map((point) => (
            <CircleMarker
              key={`${point.type}-${point.along_route_distance_nm}`}
              center={[point.latitude_deg, point.longitude_deg]}
              radius={7}
              pathOptions={{
                color: point.type === "RCA" ? "#0c7c78" : "#b42318",
                fillColor: "#ffffff",
                fillOpacity: 1,
                weight: 3,
              }}
            >
              <Tooltip permanent direction="bottom" offset={[0, 7]}>
                {point.type}
              </Tooltip>
            </CircleMarker>
          ))}
          {checkPoints.map((checkPoint) => {
            const projection = projectionById.get(checkPoint.id);
            return (
              <Fragment key={checkPoint.id}>
                {projection && (
                  <Polyline
                    positions={[
                      [checkPoint.latitude_deg, checkPoint.longitude_deg],
                      [projection.abeam_latitude_deg, projection.abeam_longitude_deg],
                    ]}
                    pathOptions={{ color: "#9b5b13", weight: 2, dashArray: "5 5" }}
                  />
                )}
                <CircleMarker
                  className="checkpoint-confirmed-marker"
                  center={[checkPoint.latitude_deg, checkPoint.longitude_deg]}
                  radius={7}
                  pathOptions={{
                    color: "#9b5b13",
                    fillColor: "#fff7e8",
                    fillOpacity: 1,
                    weight: 3,
                  }}
                >
                  <Tooltip permanent direction="right" offset={[8, 0]}>
                    CP {checkPoint.name}
                  </Tooltip>
                </CircleMarker>
                {projection && (
                  <CircleMarker
                    center={[projection.abeam_latitude_deg, projection.abeam_longitude_deg]}
                    radius={4}
                    pathOptions={{
                      color: "#9b5b13",
                      fillColor: "#9b5b13",
                      fillOpacity: 1,
                      weight: 2,
                    }}
                  >
                    <Tooltip direction="bottom">abeam {checkPoint.name}</Tooltip>
                  </CircleMarker>
                )}
              </Fragment>
            );
          })}
          {pickedCoordinate && (
            <CircleMarker
              className="checkpoint-draft-marker"
              center={[pickedCoordinate.latitude, pickedCoordinate.longitude]}
              radius={9}
              pathOptions={{
                color: "#6e4aa0",
                dashArray: "4 3",
                fillColor: "#f4edfb",
                fillOpacity: 0.95,
                weight: 3,
              }}
            >
              <Tooltip permanent direction="right" offset={[10, 0]}>
                仮CP（未保存）
              </Tooltip>
            </CircleMarker>
          )}
          {mapBuilder && <MapDraftLayers {...mapBuilder} />}
          <MapViewport storage={viewportStorage} scope={viewportScope} projectId={project?.id ?? null} coordinates={fitCoordinates} preserveViewport={preserveRouteViewport} importFitCoordinates={mapBuilder?.importFitCoordinates} />
          <CheckPointMapPicker active={!busy && !mapBuilder && (pickingCheckPoint || pickedCoordinate !== null || Boolean(checkPointDraft.id))} onPick={handleMapPick} />
          {!mapBuilder && !project && <FitBounds
            coordinates={fitCoordinates}
            signature={coordinateSignature}
          />}
        </MapContainer>
        {(rjfmMapReference || rjfmGuidance) && (
          <div
            className="rjfm-map-legend"
            role="group"
            aria-label="RJFMガイダンス凡例"
          >
            <button type="button" className="legend-toggle" aria-label={legendOpen ? "RJFM空域凡例を最小化" : "RJFM空域凡例を表示"} aria-expanded={legendOpen} onClick={() => setLegendOpen(v => !v)}>RJFM空域 <span aria-hidden="true">{legendOpen ? "−" : "+"}</span></button>
            {rjfmMapReference && (
              <span className="rjfm-airspace-status" aria-live="polite">
                {trainingAirspace.status === "loading"
                  ? "空域情報を取得中…"
                  : trainingAirspace.status === "unavailable"
                    ? "空域情報を取得できず非表示"
                    : ""}
              </span>
            )}
            {legendOpen && <>
            {rjfmMapReference && (
              <>
                <span>
                  <i className="is-pca" aria-hidden="true" />
                  PCA：約{Math.round(rjfmMapReference.pca.sourceAltitudeLowerM / 0.3048).toLocaleString("ja-JP")}
                  –{Math.round(rjfmMapReference.pca.sourceAltitudeUpperM / 0.3048).toLocaleString("ja-JP")} ft（{rjfmMapReference.pca.sourceAltitudeLowerM.toLocaleString("ja-JP")}
                  –{rjfmMapReference.pca.sourceAltitudeUpperM.toLocaleString("ja-JP")} m）
                </span>
                <span><i className="is-pca-exclusion" aria-hidden="true" />中心除外 {rjfmMapReference.pca.exclusionRadiusKm.toLocaleString("ja-JP")} km</span>
              </>
            )}
            {rjfmGuidance && (
              <>
                <span><i className="is-center" aria-hidden="true" />Newta CENTER</span>
                {visibleRjfmCandidates.map((item) => (
                  <span key={`legend-${item.runway}`}>
                    <i className={rjfmCandidateClass(item)} aria-hidden="true" />
                    RWY {item.runway} {rjfmStatusLabels[item.status]}
                  </span>
                ))}
              </>
            )}

            </>}
          </div>
        )}
        {!mapBuilder && !coordinates.length && (
          <div className="map-empty">
            <strong>経路はまだありません</strong>
            <span>KML/KMZを読み込み、飛行経路候補を選択してください。</span>
          </div>
        )}
      </div>

      <RouteConfirmation
        visible={Boolean(candidate && !project && !mapBuilder)}
        polygon={candidate?.kind === "polygon"}
        routeUseConfirmed={routeUseConfirmed}
        polygonRouteConfirmed={polygonRouteConfirmed}
        canConfirm={canConfirmRoute}
        busy={busy}
        onRouteUseConfirmedChange={onRouteUseConfirmedChange}
        onPolygonRouteConfirmedChange={onPolygonRouteConfirmedChange}
        onConfirm={onConfirmRoute}
      />

      <div className="planning-pane"><div className="planning-pane-scroll">

      {!mapBuilder && planningPanel}
      {mapBuilder && <RouteStrip {...mapBuilder}>{planningPanel}</RouteStrip>}
      {project && !mapBuilder && (
        <CheckPointEditor
          slots={checkpointSlots}
          draft={checkPointDraft}
          setDraft={setCheckPointDraft}
          nodes={nodes}
          sections={sections}
          checkPoints={checkPoints}
          planning={checkPointPlanning}
          busy={busy}
          pickedCoordinate={pickedCoordinate}
          pickingFromMap={pickingCheckPoint}
          onPickingFromMapChange={handlePickingChange}
          onPickedCoordinateClear={clearPickedCoordinate}
          onReplace={onReplaceCheckPoints}
        />
      )}

      {!mapBuilder && <>
      {project && phaseEditing && (
        <div className="phase-edit-note" role="status">
          CLIMB / DESCENT を別Legへ選ぶと、既存の同Phaseは自動でCRUISEへ戻ります。
          RCA・EOC・性能・時間・燃料計算が変わるため、計画意図を確認して変更してください。
        </div>
      )}
      <div className="route-timeline-heading"><strong>経路</strong>{project && hasEditablePhaseSections && <button className="phase-edit-toggle" type="button" disabled={busy} aria-pressed={phaseEditing} onClick={() => setPhaseEditing(v=>!v)}>{phaseEditing ? "飛行段階の編集を完了" : "飛行段階を編集"}</button>}</div>
      <ol className="route-timeline">
            {!mapBuilder && nodes.map((node, index) => {
              const section = sectionByFromNode.get(node.id);
              const legResults = section ? outcome?.sections.filter(r => r.section_id === section.id) ?? [] : [];
              const currentLeg = calculationIsCurrent ? legResults[0] : null;
              const currentDistance = calculationIsCurrent && legResults.length ? legResults.reduce((total,r)=>total+(r.zone_distance_nm.automatic_value ?? 0),0) : null;
              const guidance = section
                ? guidanceBySection.get(section.id)
                : undefined;
              const fixedAltitude = section && isFixedAltitudeMode(guidance?.inputMode)
                ? guidance?.fixedAltitudeFtMsl ?? section.planned_altitude_ft_msl
                : null;
              const fixedLabels = fixedAltitude !== null && guidance
                ? fixedAltitudeLabels(guidance.inputMode, fixedAltitude)
                : null;
              const enteredAltitude = section ? altitudeInputs[section.id] : undefined;
              const effectiveAltitude = section
                ? enteredAltitude === undefined
                  ? section.planned_altitude_ft_msl
                  : enteredAltitude.trim() === ""
                    ? null
                    : Number(enteredAltitude)
                : null;
              const isCandidateAltitude = Boolean(
                effectiveAltitude !== null &&
                Number.isFinite(effectiveAltitude) &&
                guidance?.candidateAltitudesFtMsl.some(
                  (candidateAltitude) =>
                    candidateAltitude === effectiveAltitude,
                ),
              );
              const hasAltitudeCandidateWarning =
                fixedAltitude === null &&
                Boolean(guidance?.appliesToCruisingAltitudeInput) &&
                effectiveAltitude !== null &&
                Number.isFinite(effectiveAltitude) &&
                effectiveAltitude > 3000 &&
                !isCandidateAltitude;
              const phaseLocked = Boolean(section && isPhaseLocked(section));
              const pointContent = (
                <div className="route-point-content" id={`route-point-${node.id}`}>
                  <span className="point-index" aria-hidden="true" />
                  {editingNodeId === node.id ? (
                    <div className="route-name-editor">
                      <input
                        aria-label={`${node.name}の名称`}
                        autoFocus
                        disabled={busy || nodeNameSaving}
                        value={nodeNameDraft}
                        onChange={(event) => setNodeNameDraft(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            void saveNodeNameEdit();
                          }
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelNodeNameEdit();
                          }
                        }}
                      />
                      <button
                        className="route-name-save primary-button"
                        type="button"
                        disabled={busy || nodeNameSaving}
                        onClick={() => void saveNodeNameEdit()}
                      >
                        {nodeNameSaving ? "保存中" : "保存"}
                      </button>
                      <button
                        className="route-name-cancel secondary-button"
                        type="button"
                        disabled={busy || nodeNameSaving}
                        onClick={cancelNodeNameEdit}
                      >
                        取消
                      </button>
                      {nodeNameError && <small className="field-error">{nodeNameError}</small>}
                    </div>
                  ) : (
                    <div className="route-name-display">
                      <strong>{node.name}</strong>
                      {node.role !== "AIRPORT" && node.role !== "DESTINATION" && (
                        <button
                          className="route-name-edit"
                          aria-label={`${node.name}を編集`} title="名称を編集"
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setEditingNodeId(node.id);
                            setNodeNameDraft(node.name);
                            setNodeNameError(null);
                          }}
                        >
                          <Pencil aria-hidden="true" size={15} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
              const isVrepAltitude = node.role === "VISUAL_REPORTING_POINT" && section?.phase === "VISUAL_ARRIVAL";
              const altitudeControl = (
<div className={hasAltitudeCandidateWarning ? "timeline-altitude altitude-warning-cell" : "timeline-altitude"}>
                      {section && <div className="timeline-altitude-label">{isVrepAltitude ? "VREP通過高度" : "巡航高度"}</div>}
                      {section && fixedLabels ? (
                        <div
                          className="fixed-altitude-control"
                          aria-label={`${node.name}出発Legの固定高度`}
                        >
                          <strong>{fixedLabels.primary}</strong>
                          <small>{fixedLabels.detail}</small>
                        </div>
                      ) : section ? (
                        <div className="altitude-controls">
                          <div className="altitude-input-row">
                            {guidance?.appliesToCruisingAltitudeInput && (
                              <select
                                className="table-select altitude-candidate-select"
                                aria-label={
                                  section.phase === "CRUISE"
                                    ? node.name + "出発Legの巡航高度候補"
                                    : node.name +
                                      "出発Legの" +
                                      altitudeBasisLabels[section.phase] +
                                      "候補"
                                }
                                value={
                                  isCandidateAltitude && !customAltitudeSections[section.id]
                                    ? String(effectiveAltitude)
                                    : "custom"
                                }
                                onChange={(event) => {
                                  setCustomAltitudeSections(prev => ({...prev, [section.id]: event.target.value === "custom"}));
                                  if (event.target.value !== "custom") {
                                    onAltitudeInputChange(section.id, event.target.value);
                                  }
                                }}
                              >
                                {guidance.candidateAltitudesFtMsl.map((altitude) => (
                                  <option key={altitude} value={altitude}>
                                    {altitude.toLocaleString("ja-JP")} ft
                                  </option>
                                ))}
                                <option value="custom">任意値</option>
                              </select>
                            )}
                            {(!guidance?.appliesToCruisingAltitudeInput || !isCandidateAltitude || customAltitudeSections[section.id]) && <span className="altitude-unit-input"><input
                              className="table-number-input"
                              aria-label={isVrepAltitude ? node.name + "のVREP通過高度" : node.name + "出発Legの計画高度"}
                              type="number"
                              min="100"
                              max="25000"
                              step="100"
                              value={altitudeInputs[section.id] ?? String(section.planned_altitude_ft_msl)}
                              aria-description="単位 ft"
                              placeholder="入力"
                              onChange={(event) => {
                                setCustomAltitudeSections(current => ({ ...current, [section.id]: true }));
                                onAltitudeInputChange(section.id, event.target.value);
                              }}
                            /><span aria-hidden="true">ft</span></span>}
                          </div>
                          {hasAltitudeCandidateWarning ? <small className="field-error">巡航高度の候補外（警告）</small> : section && customAltitudeSections[section.id] && guidance?.appliesToCruisingAltitudeInput ? <small className="inline-warning custom-altitude-warning">任意値を使用します。巡航高度を確認してください。</small> : null}
                        </div>
                      ) : node.role === "DESTINATION" ? (
                        <div className="arrival-altitude-control">
                          <label>
                            <span>場周高度</span>
                            <span className="altitude-unit-input"><input
                              className="arrival-pattern-input"
                              aria-description="単位 ft"
                              aria-label="今回採用する場周経路高度"
                              aria-describedby={`${node.id}-pattern-altitude-help`}
                              aria-invalid={validPatternAltitude === null}
                              type="number"
                              min="100"
                              max="25000"
                              step="100"
                              value={destinationPatternAltitudeFtMsl}
                              onChange={(event) =>
                                onDestinationPatternAltitudeChange(event.target.value)
                              }
                            /><span aria-hidden="true">ft</span></span>
                          </label>
                          <div className="arrival-airport-reference">
                            <span>飛行場標高</span>
                            <strong>
                              {destinationAirport?.elevationFtMsl.toLocaleString("ja-JP") ?? "—"}
                              {" ft MSL"}
                            </strong>
                          </div>

                          <small
                            id={`${node.id}-pattern-altitude-help`}
                            className={`arrival-altitude-help ${validPatternAltitude === null ? "field-error" : ""}`}
                          >
                            {validPatternAltitude === null
                              ? patternAltitudeBelowAirport
                                ? "採用場周経路高度は飛行場標高より高くしてください。"
                                : "100～25,000 ftの範囲で100 ft単位の整数を入力してください。"
                              : ""}
                          </small>
                        </div>
                      ) : (
                        "—"
                      )}
                    </div>
              );
              return (
                <li key={node.id} className="timeline-stop" data-node-id={node.id} data-node-role={node.role}>
                  <div className={`timeline-node${isVrepAltitude || node.role === "DESTINATION" ? " has-node-altitude" : ""}`}>{pointContent}{(isVrepAltitude || node.role === "DESTINATION") && <div className="timeline-node-altitude">{altitudeControl}</div>}<small className="timeline-node-kind">{index === 0 ? "FROM" : node.role === "DESTINATION" ? "TO" : node.role === "VISUAL_REPORTING_POINT" ? "VREP" : "WP"}</small></div>
                  <section className={section ? "timeline-leg" : "timeline-arrival"} aria-label={section ? `${node.name}から次の地点までの区間` : "到着空港の高度"} data-section-id={section?.id} data-from-node-id={section?.from_node_id} data-to-node-id={section?.to_node_id}>
                    {section && <div className="timeline-leg-metrics">{currentLeg && <><span>TC {currentLeg.true_course_deg.automatic_value?.toFixed(0)}°</span><span>MC {currentLeg.magnetic_course_deg.automatic_value?.toFixed(0)}°</span></>}{currentDistance != null && <span>Dist {currentDistance.toFixed(1)} NM</span>}</div>}
                    <div className="timeline-leg-controls">
                    {!isVrepAltitude && node.role !== "DESTINATION" && altitudeControl}
                    <div className={`timeline-phase${isVrepAltitude ? " is-visual-arrival" : ""}`}>
                      {section && <div className="timeline-altitude-label">飛行段階</div>}
                      <div className="route-phase-content">
                        <div className="route-phase-primary">
                          {section && fixedLabels ? (
                            <span
                              className="fixed-phase"
                              aria-label={`${node.name}出発Legの固定Phase`}
                            >
                              {fixedLabels.phase}
                            </span>
                          ) : section && phaseLocked ? (
                            <span
                              className="phase-locked-value"
                              aria-label={`${node.name}出発Legの固定Phase`}
                            >
                              {phaseLabels[section.phase]}（固定）
                            </span>
                          ) : section ? (
                            <select
                              className={`table-select phase-select${phaseEditing ? " is-editing" : " is-readonly"}`}
                              aria-label={`${node.name}出発LegのPhase`}
                              aria-disabled={!phaseEditing}
                              tabIndex={phaseEditing ? 0 : -1}
                              title={
                                phaseEditing
                                  ? "CLIMBまたはDESCENTを選ぶと同Phaseの基準Legが移動します。"
                                  : undefined
                              }
                              value={section.phase}
                              onPointerDown={(event) => {
                                if (!phaseEditing) event.preventDefault();
                              }}
                              onKeyDown={(event) => {
                                if (!phaseEditing) event.preventDefault();
                              }}
                              onChange={(event) =>
                                changePhaseBasis(section, event.target.value as FlightPhase)
                              }
                            >
                              {phaseOptionsForSection(section).map((phase) => (
                                <option key={phase} value={phase}>
                                  {phaseLabels[phase]}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="phase-arrival-value">到着</span>
                          )}
                        </div>
                        {section?.phase === "DESCENT" && displayedDescentRate !== null && (
                          <small className="descent-rate-result">
                            計算結果 {displayedDescentRate} fpm
                          </small>
                        )}
                      </div>
                    </div>
                    </div>
                    {section && <CheckpointSlot sectionId={section.id} register={registerCheckpointSlot} />}
                  </section>
                </li>
              );
            })}
      </ol>
      </>}
      </div><div className="planning-pane-footer">{readinessPanel}</div></div>
    </section>
  );
}

function CheckpointSlot({ sectionId, register }: { sectionId: string; register: (id: string, element: HTMLDivElement | null) => void }) {
  const ref = useCallback((element: HTMLDivElement | null) => register(sectionId, element), [register, sectionId]);
  return <div className="timeline-cps" ref={ref} />;
}
