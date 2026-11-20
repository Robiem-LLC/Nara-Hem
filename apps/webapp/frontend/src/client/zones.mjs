// Times for someone who may be in another time zone. Phones send their zone (an IANA name such as
// "America/New_York") with each location. When it gives a different clock from this browser's at
// that moment, both are shown, this browser's first: "8:00 PM EST / 10:00 PM PST" in New York for
// someone in Los Angeles. Without a zone, or in the same one, it's the plain local time.

const CLOCK = { hour: 'numeric', minute: '2-digit' };
const WITH_DATE = { year: 'numeric', month: 'numeric', day: 'numeric', ...CLOCK };

/** Returns the zone if this browser knows it, otherwise null. */
export function knownZone(zone) {
  if (typeof zone !== 'string' || !zone || zone.length > 64) return null;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return zone;
  } catch {
    return null;
  }
}

/** Returns true if the zone's clock and date read differently from this browser's at ms. */
export function differentZone(ms, zone) {
  const theirs = knownZone(zone);
  if (!theirs) return false;
  const at = new Date(ms);
  const wall = (options) =>
    new Intl.DateTimeFormat('en-US', { ...WITH_DATE, ...options }).format(at);
  return wall({ timeZone: theirs }) !== wall({});
}

/**
 * Formats ms as a time of day, or with its date when withDate is set, adding the time in zone
 * when that reads differently.
 */
export function zoneTime(ms, zone, { withDate = false } = {}) {
  const at = new Date(ms);
  const options = withDate ? WITH_DATE : CLOCK;
  if (!differentZone(ms, zone)) return at.toLocaleString([], options);
  const named = { ...options, timeZoneName: 'short' };
  return (
    at.toLocaleString([], named) +
    ' / ' +
    at.toLocaleString([], { ...named, timeZone: knownZone(zone) })
  );
}
