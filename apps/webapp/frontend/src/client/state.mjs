// Shared, changing state of the client. Modules read and write it as state.<name>;
// one object, because imported bindings cannot be reassigned by the importing module.

/**
 * Shared mutable state for the client modules, kept in one object because imported bindings can't
 * be reassigned.
 */
export const state = {
  tripFocusAccount: '',
  timelineMaps: [],
  timelinePreviewObserver: null,
  tripScrollAbort: null,
  editingPlaceId: null,
  editingPlaceRecordId: null,
  activeMapConfig: { provider: 'openstreetmap' },
  placePreviewMap: null,
  placePreviewCircle: null,
  placePreviewClick: null,
  googleStaticWarned: false,
  refreshPlacePreview: async () => {},
  api: undefined,
  user: undefined,
  notice: undefined,
  view: undefined,
  vault: undefined,
  registering: null,
  key: undefined,
  salt: undefined,
  context: undefined,
  storeKey: undefined,
  chain: undefined,
  timer: undefined,
  map: undefined,
  states: [],
  markers: [],
  mode: 'map',
  renderEpoch: 0,
  addressQueue: Promise.resolve(),
  pending: Promise.resolve(),
};
