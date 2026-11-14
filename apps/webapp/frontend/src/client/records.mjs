// Publishing encrypted records and reading the current saved places.

import * as C from '../crypto.mjs';
import { metersBetween } from './addresses.mjs';
import { deviceApi, save, sync } from './core.mjs';
import { state } from './state.mjs';

/** Returns the saved places manifest and the current records. */
export async function placeState() {
  const manifest = await deviceApi('/api/places/manifest');
  const view = await deviceApi('/api/view');
  return { manifest, records: view.records.filter((p) => p.kind === 'place') };
}

/** Encrypts and signs a record for every allowed device and uploads it. Calls run one at a time. */
export function publish(kind, entity, data, operation = 'upsert', capturedAt = Date.now()) {
  const expected = state.vault;
  const task = async () => {
    if (!expected || state.vault !== expected) throw new Error('Browser session changed.');
    await sync();
    const d = await deviceApi('/api/device');
    if (state.vault !== expected) throw new Error('Browser session changed.');
    state.vault.sequence = Math.max(state.vault.sequence, d.sequence);
    let previous = state.states.find((s) => s.kind === kind && s.entity_id === entity);
    let headers = {};
    if (kind === 'place') {
      const snapshot = await placeState();
      const old = snapshot.records.find((p) => p.entity_id === entity && p.operation === 'upsert');
      if (
        operation === 'upsert' &&
        (!old ||
          old.data.lat !== data.lat ||
          old.data.lon !== data.lon ||
          old.data.radius !== data.radius)
      ) {
        const conflict = snapshot.records.find(
          (p) =>
            p.operation === 'upsert' &&
            p.entity_id !== entity &&
            metersBetween(data.lat, data.lon, p.data.lat, p.data.lon) < data.radius + p.data.radius,
        );
        if (conflict) {
          throw new Error(
            'This area overlaps ' +
              conflict.data.name +
              '. Open Saved places to edit that place or change this area.',
          );
        }
      }
      previous = snapshot.records.find((p) => p.entity_id === entity);
      const pointer = snapshot.manifest.places.find((p) => p.id === entity);
      if (pointer && !previous) {
        throw new Error('Wait for shared-place synchronization before editing.');
      }
      headers = { 'X-Places-State': snapshot.manifest.token };
    }
    const envelope = C.encryptedRecord(
      state.vault,
      state.chain.current,
      kind,
      entity,
      data,
      operation,
      ['place', 'profile'].includes(kind) ? previous?.id || null : null,
      capturedAt,
      d.trip_processing_key,
    );
    await deviceApi('/api/records', 'POST', envelope, headers);
    state.vault.sequence = envelope.body.sequence;
    await save();
  };
  const next = state.pending.then(task);
  state.pending = next.catch(() => {});
  return next;
}
