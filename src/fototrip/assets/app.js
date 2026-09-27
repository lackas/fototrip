/* fototrip — map, thumbnail markers, clustering and lightbox.
 *
 * Leaflet and Leaflet.markercluster are loaded as classic scripts and provide
 * the global L. PhotoSwipe is an ES module.
 */
import PhotoSwipeLightbox from "./vendor/photoswipe/photoswipe-lightbox.esm.js";
import PhotoSwipe from "./vendor/photoswipe/photoswipe.esm.js";

const state = {
  photos: [],
  visible: [],
  days: [],
  selectedDay: null,
  bounds: null,
};

const map = L.map("map", { zoomControl: true, worldCopyJump: false });

L.tileLayer(window.FOTOTRIP_TILES.url, {
  attribution: window.FOTOTRIP_TILES.attribution,
  maxZoom: 19,
  subdomains: "abc",
}).addTo(map);

/* A single cluster group, rebuilt whenever the visible set changes. */
const clusterGroup = L.markerClusterGroup({
  maxClusterRadius: 55,
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: true,
  zoomToBoundsOnClick: true,
  iconCreateFunction: (cluster) => {
    const children = cluster.getAllChildMarkers();
    // Show the newest photo in the cluster, so the icon changes as you zoom.
    const newest = children.reduce((a, b) =>
      a.options.photo.t >= b.options.photo.t ? a : b
    );
    const count = cluster.getChildCount();
    return L.divIcon({
      className: "",
      iconSize: [54, 54],
      html:
        `<div class="cluster-marker" style="background-image:url('${newest.options.photo.thumb}')">` +
        `<span class="count">${count}</span></div>`,
    });
  },
}).addTo(map);

function markerFor(photo, index) {
  const marker = L.marker([photo.lat, photo.lon], {
    photo,
    title: new Date(photo.t).toLocaleString(),
    icon: L.divIcon({
      className: "",
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      html: `<div class="photo-marker" style="background-image:url('${photo.thumb}')"></div>`,
    }),
  });
  marker.on("click", () => openLightboxAt(index));
  return marker;
}

/* Bounds that never collapse: a single photo, or a burst at one spot, would
 * otherwise give fitBounds a zero-area box and slam the map to max zoom. */
function paddedBounds(photos) {
  if (photos.length === 0) return null;
  const lats = photos.map((p) => p.lat);
  const lons = photos.map((p) => p.lon);
  const pad = 0.004; // ~450 m
  const spanLat = Math.max(...lats) - Math.min(...lats);
  const spanLon = Math.max(...lons) - Math.min(...lons);
  const padLat = spanLat < pad ? pad : 0;
  const padLon = spanLon < pad ? pad : 0;
  return L.latLngBounds(
    [Math.min(...lats) - padLat, Math.min(...lons) - padLon],
    [Math.max(...lats) + padLat, Math.max(...lons) + padLon]
  );
}

function fitTo(photos) {
  const bounds = paddedBounds(photos);
  if (bounds) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
  else map.setView([0, 0], 2);
}

function setVisible(photos) {
  state.visible = photos;
  clusterGroup.clearLayers();
  clusterGroup.addLayers(photos.map(markerFor));
  fitTo(photos);
  const status = document.getElementById("status");
  if (status) {
    const label = state.selectedDay ? state.selectedDay : "whole trip";
    status.textContent = `${photos.length} photo${photos.length === 1 ? "" : "s"} · ${label}`;
  }
}

/* PhotoSwipe over the currently visible set, so next/prev walks the trip. */
const lightbox = new PhotoSwipeLightbox({
  pswpModule: PhotoSwipe,
  dataSource: [],
  showHideAnimationType: "fade",
  padding: { top: 10, bottom: 10, left: 10, right: 10 },
});
lightbox.init();

function openLightboxAt(index) {
  lightbox.options.dataSource = state.visible.map((photo) => ({
    src: photo.web,
    width: photo.w,
    height: photo.h,
    alt: new Date(photo.t).toLocaleString(),
  }));
  lightbox.loadAndOpen(Math.max(0, Math.min(index, state.visible.length - 1)));
}

async function boot() {
  const response = await fetch("photos.json");
  const manifest = await response.json();
  state.photos = manifest.photos;
  state.days = manifest.days;
  state.bounds = manifest.bounds;
  setVisible(state.photos);
  window.dispatchEvent(new CustomEvent("fototrip:loaded"));
}

window.fototrip = { state, map, clusterGroup, lightbox, setVisible, openLightboxAt, fitTo };

boot();
