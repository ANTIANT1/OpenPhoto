import { api } from './api';
import type { Photo } from './types';

export async function loadPhotos(query: string, signal: AbortSignal, update: (photos: Photo[]) => void, incremental = true) {
  const collected: Photo[] = [];
  let offset = 0;
  while (!signal.aborted) {
    const page = await api<{photos: Photo[]; total: number}>(`/photos?${query}&offset=${offset}&limit=250`, {signal});
    collected.push(...page.photos);
    offset += page.photos.length;
    if (signal.aborted) return;
    // Keep the first page responsive and retain all IDs across following pages.
    if (incremental || offset >= page.total || !page.photos.length) update([...new Map(collected.map(photo => [photo.id, photo])).values()]);
    if (offset >= page.total || !page.photos.length) return;
  }
}

export function comparisonPair(ids: string[], photos: Photo[], current?: Photo | null): [string, string] | null {
  const available = ids.filter((id, index) => ids.indexOf(id) === index && photos.some(p => p.id === id));
  if (available.length >= 2) return [available[0], available[1]];
  if (!current) return null;
  const peer = photos.find(p => p.group_id === current.group_id && p.id !== current.id)
    || photos.find(p => p.shoot_id === current.shoot_id && p.id !== current.id);
  return peer ? [current.id, peer.id] : null;
}
