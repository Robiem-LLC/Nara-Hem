import sodium from 'libsodium-wrappers-sumo';

/** Resolves when libsodium has loaded. Await it before calling anything else in this module. */
export const ready = sodium.ready;

/** Serializes a value as JSON with sorted keys, matching what the server and apps sign. */
export const canonical = (value) => JSON.stringify(sort(value));

/** Encodes bytes as standard base64. */
export const b64 = (value) => sodium.to_base64(value, sodium.base64_variants.ORIGINAL);

/** Decodes standard base64. */
export const unb64 = (value) => sodium.from_base64(value, sodium.base64_variants.ORIGINAL);

/** Encodes bytes as hex. */
export const hex = (value) => sodium.to_hex(value);

/** Returns a random 128-bit ID as 32 hex characters. */
export const uuid = () => hex(sodium.randombytes_buf(16));

/** Returns a detached Ed25519 signature over the canonical JSON of body. */
export const sign = (body, key) => b64(sodium.crypto_sign_detached(canonical(body), unb64(key)));

/** Returns a copy with object keys sorted at every level. */
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sort(value[key])]),
    );
  }
  return value;
}

/** Returns the SHA-256 digest of a string or bytes as hex. */
export const hash = (value) =>
  hex(sodium.crypto_hash_sha256(typeof value === 'string' ? sodium.from_string(value) : value));

/**
 * Returns the six-digit pairing code derived from a registration and the household root key. Each
 * device computes it independently for the user to compare.
 */
export function pairingCode(registration, anchor) {
  if (!anchor || unb64(anchor).length !== 32) {
    throw new Error('Household trust anchor unavailable.');
  }
  const digest = hash('narahem.pairing-code.v1:' + anchor + ':' + hash(canonical(registration)));
  return String(parseInt(digest.slice(0, 12), 16) % 1000000).padStart(6, '0');
}

/** Returns true if a trusted device signed a roster revision approving this exact registration. */
export function verifyPairing(changes, household, anchor, registration) {
  const validated = verifyChain(changes, household, anchor);
  const registrationHash = hash(canonical(registration));
  const id = registration.id;
  let paired = false;
  let prior = null;
  for (const item of changes) {
    const body = item.body;
    if (body.pairing_target === id) {
      if (
        body.pairing_hash !== registrationHash ||
        !prior?.devices.some((d) => d.id === body.signer) ||
        prior.devices.some((d) => d.id === id) ||
        !body.devices.some(
          (d) =>
            d.id === id &&
            d.account_id === registration.account_id &&
            d.signing_key === registration.signing_key &&
            d.box_key === registration.box_key,
        )
      ) {
        throw new Error('Signed device approval does not match this device.');
      }
      paired = true;
    }
    prior = body;
  }
  if (!paired || !validated.current.devices.some((d) => d.id === id)) {
    throw new Error('Waiting for a matching signed device approval.');
  }
  return validated;
}

/** Verifies a detached Ed25519 signature over the canonical JSON of body. */
export const verify = (body, signature, key) =>
  sodium.crypto_sign_verify_detached(unb64(signature), canonical(body), unb64(key));

/** Returns a device's public roster entry. */
export const identity = (vault) => ({
  id: vault.id,
  account_id: vault.account_id,
  signing_key: vault.signing_key,
  box_key: vault.box_key,
});

/** Generates a new device: signing and encryption key pairs and its signed registration. */
export function keys(account, household, name) {
  const signing = sodium.crypto_sign_keypair();
  const box = sodium.crypto_box_keypair();
  return {
    id: uuid(),
    account_id: account,
    household,
    name,
    signing_key: b64(signing.publicKey),
    signing_secret: b64(signing.privateKey),
    box_key: b64(box.publicKey),
    box_secret: b64(box.privateKey),
    revision: 0,
    chain_hash: '',
    anchor: null,
    sequence: 0,
  };
}

/** Encrypts a record for every recipient device and the server, and signs it. */
export function encryptedRecord(
  vault,
  roster,
  kind,
  entity,
  data,
  operation = 'upsert',
  replaces = null,
  capturedAt = Date.now(),
  serverKey = null,
) {
  const body = {
    domain: 'narahem.record.v1',
    household: vault.household,
    revision: roster.revision,
    id: uuid(),
    sender: vault.id,
    sequence: vault.sequence + 1,
    kind,
    entity_id: entity,
    operation,
    replaces,
    captured_at: capturedAt,
  };
  const payload = {
    domain: 'narahem.payload.v1',
    ...Object.fromEntries(Object.entries(body).filter(([key]) => key !== 'domain')),
    data,
  };
  body.recipients = roster.devices
    .map((device) => ({
      device_id: device.id,
      box: b64(sodium.crypto_box_seal(canonical(payload), unb64(device.box_key))),
    }))
    .sort((a, b) => a.device_id.localeCompare(b.device_id));
  if (serverKey && ['location', 'event', 'place', 'profile'].includes(kind)) {
    const key = unb64(serverKey);
    if (key.length !== 32) throw new Error('Invalid server trip processing key');
    body.server_box = b64(sodium.crypto_box_seal(canonical(payload), key));
  }
  return { body, signature: sign(body, vault.signing_secret) };
}

/**
 * Verifies a record's signature against the roster revision it was made for, then decrypts this
 * device's copy.
 */
export function decryptRecord(envelope, vault, rosters) {
  const body = envelope.body;
  const roster = rosters.get(body.revision);
  const sender = roster?.devices.find((d) => d.id === body.sender);
  if (
    body.domain !== 'narahem.record.v1' ||
    body.household !== vault.household ||
    !sender ||
    !verify(body, envelope.signature, sender.signing_key)
  ) {
    throw new Error('Encrypted record signature or household rejected.');
  }
  if (['location', 'profile'].includes(body.kind) && body.entity_id !== sender.account_id) {
    throw new Error('Location/profile does not belong to its signed sender.');
  }
  const recipient = body.recipients.find((r) => r.device_id === vault.id);
  if (!recipient) throw new Error('This record predates approval of this device.');
  const payload = JSON.parse(
    sodium.to_string(
      sodium.crypto_box_seal_open(
        unb64(recipient.box),
        unb64(vault.box_key),
        unb64(vault.box_secret),
      ),
    ),
  );
  if (payload.domain !== 'narahem.payload.v1') throw new Error('Payload format rejected.');
  for (const key of [
    'household',
    'revision',
    'id',
    'sender',
    'sequence',
    'kind',
    'entity_id',
    'operation',
    'replaces',
    'captured_at',
  ]) {
    if (payload[key] !== body[key]) throw new Error('Encrypted record context rejected.');
  }
  return payload;
}

/**
 * Verifies a sequence of signed roster revisions from the household root key. Returns the rosters
 * by revision, the current roster, and the latest hash and revision.
 */
export function verifyChain(changes, household, anchor) {
  const rosters = new Map();
  let previous = '';
  let revision = 0;
  let current;
  for (const change of changes) {
    const b = change.body;
    if (
      b.domain !== 'narahem.roster.v1' ||
      b.household !== household ||
      b.revision !== revision + 1 ||
      b.previous !== previous
    ) {
      throw new Error('Membership chain rejected.');
    }
    const ids = b.devices.map((d) => d.id);
    if (new Set(ids).size !== ids.length || canonical([...ids].sort()) !== canonical(ids)) {
      throw new Error('Duplicate or unordered membership.');
    }
    const signer = revision
      ? current.devices.find((d) => d.id === b.signer)
      : b.devices.find((d) => d.id === b.signer);
    if (
      !signer ||
      (!revision && (b.devices.length !== 1 || signer.signing_key !== anchor)) ||
      !verify(b, change.signature, signer.signing_key)
    ) {
      throw new Error('Untrusted membership signature.');
    }
    if (revision) {
      for (const old of current.devices) {
        const next = b.devices.find((d) => d.id === old.id);
        if (next && canonical(next) !== canonical(old)) {
          throw new Error('A device key was substituted.');
        }
      }
    }
    previous = hash(canonical({ body: b, signature: change.signature }));
    if (change.hash !== previous) throw new Error('Membership digest rejected.');
    revision = b.revision;
    current = b;
    rosters.set(revision, b);
  }
  return { rosters, current, hash: previous, revision };
}

/** Derives the AES key that encrypts the stored vault from a password. */
export async function vaultKey(password, salt, usage = ['encrypt', 'decrypt']) {
  const base = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 600000 },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    usage,
  );
}

/** Encrypts the vault for storage in this browser. */
export async function sealVault(value, key, salt, context) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const box = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(context) },
    key,
    new TextEncoder().encode(JSON.stringify(value)),
  );
  return { version: 1, salt: b64(salt), iv: b64(iv), box: b64(new Uint8Array(box)) };
}

/** Decrypts a stored vault with the password. */
export async function openVault(saved, password, context) {
  if (saved.version !== 1) throw new Error('Unsupported browser vault.');
  const salt = unb64(saved.salt);
  const key = await vaultKey(password, salt);
  try {
    const value = JSON.parse(
      new TextDecoder().decode(
        await crypto.subtle.decrypt(
          {
            name: 'AES-GCM',
            iv: unb64(saved.iv),
            additionalData: new TextEncoder().encode(context),
          },
          key,
          unb64(saved.box),
        ),
      ),
    );
    return { value, key, salt };
  } catch {
    throw new Error('Could not unlock: check your browser-vault passphrase.');
  }
}

/** Clears the vault's secret fields in memory. */
export function wipe(vault) {
  if (vault) for (const key of ['signing_secret', 'box_secret', 'credential']) vault[key] = '';
}
