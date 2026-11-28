import type { ReactNode } from "react";
import { MapContainer } from "react-leaflet";
import type { KeyValueStorage } from "../platform";
import { MapBackground } from "./MapBackground";
import { MapDraftLayers, RouteStrip, type MapRouteBuilderProps } from "./MapRouteBuilder";
import { MapViewport } from "./MapViewport";

export function StartupRoute({ builder, storage, scope, children, confirmDisabled, retry }: {
  builder: MapRouteBuilderProps; storage: KeyValueStorage; scope: string; children: ReactNode; confirmDisabled: boolean; retry: ReactNode;
}) {
  return <div className="app-shell">
    <div className="app-workspace is-route-building">
      <section className="route-workspace is-route-building">
        <div className="map-frame">
          <MapContainer center={[31.8772, 131.4486]} zoom={9} maxZoom={19} zoomAnimation={false}
            trackResize={false} className="route-map" aria-label="飛行経路地図">
            <MapBackground imagery={false} />
            <MapDraftLayers {...builder} />
            <MapViewport storage={storage} scope={scope} projectId={null} coordinates={[]} preserveViewport />
          </MapContainer>
        </div>
        <div className="planning-pane">
          <div className="planning-pane-scroll">
            {children}
            <RouteStrip {...builder} confirmDisabled={confirmDisabled} retry={retry} />
          </div>
        </div>
      </section>
    </div>
  </div>;
}
