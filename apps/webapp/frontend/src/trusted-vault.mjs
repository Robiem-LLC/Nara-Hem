/** Returns the stored wrapping key for this browser, if any. */
export const getKey = (context) => operation(context, 'readonly');

/** Stores the wrapping key. */
export const putKey = (context, key) => operation(context, 'readwrite', key);

/** Deletes the wrapping key. */
export const deleteKey = (context) => operation(context, 'readwrite', null, true);

/** Opens the IndexedDB database holding the wrapping key. The key never leaves the browser. */
async function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('narahem.device-keys', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('keys');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error('This browser cannot store device keys.'));
  });
}

/** Runs one IndexedDB read, write or delete. */
async function operation(context, mode, value, remove = false) {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('keys', mode);
      const store = tx.objectStore('keys');
      const request = remove
        ? store.delete(context)
        : value
          ? store.put(value, context)
          : store.get(context);
      let result;
      request.onsuccess = () => {
        result = request.result;
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(new Error('Browser device-key storage failed.'));
      tx.onabort = tx.onerror;
    });
  } finally {
    db.close();
  }
}

/** Creates a non-extractable AES key for wrapping the device keys. */
export const createKey = () =>
  crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);

/** Decrypts device keys stored with the wrapping key. */
export async function open(saved, key, context) {
  if (saved.version !== 1) throw new Error('Unsupported browser device storage.');
  const decode = (value) => Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
  try {
    return JSON.parse(
      new TextDecoder().decode(
        await crypto.subtle.decrypt(
          {
            name: 'AES-GCM',
            iv: decode(saved.iv),
            additionalData: new TextEncoder().encode(context),
          },
          key,
          decode(saved.box),
        ),
      ),
    );
  } catch {
    throw new Error(
      'Browser device keys could not be opened. Restore this browser profile or enroll a new ' +
        'device.',
    );
  }
}
