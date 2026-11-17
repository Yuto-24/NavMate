import { useEffect, useLayoutEffect, useRef } from "react";
import { useMap, useMapEvents } from "react-leaflet";
import type { KeyValueStorage } from "../platform";

// Leaflet supports reset; its published ZoomPanOptions omits it.
const exactViewOptions = { animate: false, reset: true };

interface Viewport { latitude: number; longitude: number; zoom: number }
function readViewport(storage: KeyValueStorage, key: string): Viewport | null {
  try {
    const value = JSON.parse(storage.getItem(key) ?? "null") as Viewport | null;
    return value && Number.isFinite(value.latitude) && Math.abs(value.latitude) <= 90 &&
      Number.isFinite(value.longitude) && Math.abs(value.longitude) <= 180 &&
      Number.isFinite(value.zoom) && value.zoom >= 0 && value.zoom <= 19 ? value : null;
  } catch { return null; }
}
export function MapViewport({ storage, scope, projectId, coordinates, preserveViewport, importFitCoordinates }: {
  storage: KeyValueStorage; scope: string; projectId: string | null;
  coordinates: [number, number][]; preserveViewport: boolean;
  importFitCoordinates?: [number, number][] | null;
}) {
  const map = useMap();
  const initialized = useRef(false);
  const previousProject = useRef<string | null>(null);
  const initializedKey = useRef<string | null>(null);
  const prefix = `autonavlog.map-viewport.v1.${scope}`;
  const lastKey = `${prefix}.last`;
  const projectKey = projectId ? `${prefix}.project.${projectId}` : lastKey;
  const resizing = useRef(false);
  const save = () => {
    if (resizing.current) return;
    const center = map.getCenter().wrap();
    const value = JSON.stringify({ latitude: center.lat, longitude: center.lng, zoom: map.getZoom() });
    try { storage.setItem(projectKey, value); storage.setItem(lastKey, value); } catch { /* Best-effort view preference, never Project data. */ }
  };
  useMapEvents({ moveend: save });
  useEffect(() => {
    if (initializedKey.current === projectKey) {
      return;
    }
    const projectView = projectId ? readViewport(storage, projectKey) : null;
    const saved = projectView ?? readViewport(storage, lastKey);
    // Confirmation retains the draft view; opening a saved Project restores its own view.
    if (projectView || !initialized.current || previousProject.current !== null) {
      if (saved) map.setView([saved.latitude, saved.longitude], saved.zoom, exactViewOptions);
    }
    // A Project opened on this device for the first time must show its route.
    // Decide before save() creates a Project preference; draft confirmation keeps its view.
    if (projectId && !projectView && !preserveViewport && coordinates.length >= 2) {
      map.invalidateSize({ animate: false });
      map.fitBounds(coordinates, { padding: [28, 28], animate: false });
    }
    initializedKey.current = projectKey;
    initialized.current = true;
    previousProject.current = projectId;
    save();
  }, [map, storage, projectKey, preserveViewport, coordinates]);
  // A new parser candidate is fitted once. Ordinary draft edits and resize keep
  // the user's view; the request is an immutable snapshot, not live draft points.
  useEffect(() => {
    if (!importFitCoordinates || importFitCoordinates.length < 2) return;
    map.invalidateSize({ animate: false });
    map.fitBounds(importFitCoordinates, { padding: [28, 28], animate: false });
  }, [map, importFitCoordinates]);
  useLayoutEffect(() => {
    const container = map.getContainer();
    let { x: width, y: height } = map.getSize();
    const observer = new ResizeObserver(() => {
      // New remounts Local work without navigating. Ignore the old map's 0x0
      // removal notification so it cannot overwrite the view being restored.
      if (!container.isConnected || !container.clientWidth || !container.clientHeight) return;
      if (container.clientWidth === width && container.clientHeight === height) return;
      width = container.clientWidth;
      height = container.clientHeight;
      // Leaflet invalidation discards its precise center cache and rounds pixel
      // offsets. Do not persist that transient quantization as the user's view.
      const center = map.getCenter();
      const zoom = map.getZoom();
      resizing.current = true;
      try {
        map.invalidateSize({ animate: false });
        map.setView(center, zoom, exactViewOptions);
      } finally {
        resizing.current = false;
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);
  return null;
}
