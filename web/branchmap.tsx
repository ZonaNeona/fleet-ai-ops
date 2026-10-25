import { useEffect, useRef } from "react";
import L from "leaflet";

// The demo fleet's sites: approximate points in Moscow districts
const COORDS: Record<string, [number, number]> = {
  vernadskogo: [55.6765, 37.5051],
  mitino: [55.8456, 37.3612],
  kuntsevo: [55.7309, 37.4462],
};
// OpenStreetMap tiles (no API key, with attribution); a CSS filter darkens them in the dark theme
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">участники OpenStreetMap</a>';

type Branch = { id: string; name?: string; address?: string; [key: string]: unknown };

export function BranchMap({ branches, counts }: { branches: Branch[]; counts: Record<string, number> }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const map = L.map(box.current, { scrollWheelZoom: false, zoomControl: true, attributionControl: true });
    map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 18 }).addTo(map);
    const points: L.LatLng[] = [];
    for (const b of branches) {
      const c = COORDS[b.id];
      if (!c) continue;
      const ll = L.latLng(c[0], c[1]);
      points.push(ll);
      L.marker(ll, {
        icon: L.divIcon({
          className: "map-pin",
          html: `<span>${counts[b.id] ?? ""}</span>`,
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
        title: b.name,
      })
        .bindTooltip(`<strong>${b.name}</strong><br>${b.address}`, { direction: "top", offset: [0, -16] })
        .addTo(map);
    }
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [36, 36] });
    // the card may have resized after the first paint
    const resize = new ResizeObserver(() => map.invalidateSize());
    resize.observe(box.current);
    return () => {
      resize.disconnect();
      map.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branches.map((b) => b.id).join(), JSON.stringify(counts)]);
  return <div className="branch-leaflet" ref={box} />;
}
