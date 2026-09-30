const token = document.querySelector<HTMLMetaElement>('meta[name="openphoto-token"]')?.content || new URLSearchParams(location.search).get('token') || '';
if (location.search.includes('token=')) history.replaceState({}, '', location.pathname);
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', 'X-OpenPhoto-Token': token, ...options.headers } });
  if (!response.ok) { const result = await response.json().catch(() => ({ detail: response.statusText })); throw new Error(typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)); }
  return response.json();
}
export const post = <T,>(path: string, body: unknown = {}): Promise<T> => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const imageUrl = (id: string, variant = 'thumb', revision = 0) => `/api/photos/${id}/image?variant=${variant}&revision=${revision}`;
