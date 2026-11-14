// Synthetic browser API fixture: never contacts Google or consumes paid map loads.
(() => {
  const state = (window.testGoogleMaps = {
    circles: [],
    maps: [],
    overlays: [],
    polylines: [],
    markers: [],
    geocodeMode: 'ok',
  });
  class Map {
    constructor(element, options) {
      this.element = element;
      element.style.position = 'relative';
      this.zoom = options.zoom;
      this.created = { ...options };
      this.options = { ...options };
      state.maps.push(this);
    }
    fitBounds(bounds, padding) {
      this.bounds = bounds;
      this.padding = padding;
      this.zoom = 20;
      this.idle?.();
    }
    setOptions(options) {
      this.options = { ...this.options, ...options };
    }
    getZoom() {
      return this.zoom;
    }
    setZoom(zoom) {
      this.zoom = zoom;
    }
    addListener(event, listener) {
      this.listeners ||= new globalThis.Map();
      this.listeners.set(event, listener);
      return { remove: () => this.listeners.delete(event) };
    }
  }
  class OverlayView {
    setMap(map) {
      if (this.map) this.onRemove();
      this.map = map;
      if (map) {
        state.overlays.push(this);
        this.onAdd();
        this.draw();
      }
    }
    getPanes() {
      return { overlayMouseTarget: this.map.element };
    }
    getProjection() {
      return { fromLatLngToDivPixel: (p) => ({ x: 150 + p.lng, y: 150 + p.lat }) };
    }
    static preventMapHitsAndGesturesFrom() {}
  }
  class InfoWindow {
    setContent(content) {
      this.content = content;
    }
    setPosition(position) {
      this.position = position;
    }
    open({ map }) {
      this.close();
      this.element = document.createElement('div');
      this.element.className = 'test-google-popup';
      this.element.append(this.content);
      map.element.append(this.element);
    }
    close() {
      this.element?.remove();
    }
  }
  class Circle {
    constructor(options) {
      Object.assign(this, options);
      state.circles.push(this);
    }
    addListener(event, handler) {
      this.click = handler;
      return {
        remove: () => {
          this.click = null;
        },
      };
    }
    getCenter() {
      return this.center;
    }
    setMap(map) {
      this.map = map;
    }
  }
  class Geocoder {
    async geocode(query) {
      if (state.geocodeMode === 'hang') return new Promise(() => {});
      if (state.geocodeMode === 'deny') {
        throw Object.assign(new Error('REQUEST_DENIED'), { code: 'REQUEST_DENIED' });
      }
      const lat = query.location?.lat ?? 12.3456789;
      const lon = query.location?.lng ?? -23.4567891;
      return {
        results: [
          {
            formatted_address: 'Synthetic address from Google Maps',
            geometry: { location: { lat: () => lat, lng: () => lon } },
          },
        ],
      };
    }
  }
  class Polyline {
    constructor(options) {
      Object.assign(this, options);
      state.polylines.push(this);
    }
    setMap(map) {
      this.map = map;
    }
  }
  class Marker {
    constructor(options) {
      Object.assign(this, options);
      state.markers.push(this);
    }
    setMap(map) {
      this.map = map;
    }
  }
  window.google = {
    maps: {
      Map,
      OverlayView,
      InfoWindow,
      Circle,
      Polyline,
      Marker,
      Geocoder,
      LatLng: class {
        constructor(lat, lng) {
          this.lat = lat;
          this.lng = lng;
        }
      },
      LatLngBounds: class {
        constructor() {
          this.points = [];
        }
        extend(p) {
          this.points.push(p);
        }
      },
      event: {
        trigger: () => {},
        addListenerOnce: (map, event, handler) => {
          map.idle = handler;
        },
        clearInstanceListeners: (map) => {
          map.idle = null;
        },
      },
      importLibrary: async (library) => (library === 'geocoding' ? { Geocoder } : { Map }),
    },
  };
  window.naraHemGoogleReady();
})();
