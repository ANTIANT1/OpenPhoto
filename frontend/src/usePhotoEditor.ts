import { useCallback, useRef, useState } from 'react';
import type { SetStateAction } from 'react';
import { api } from './api';
import type { Detail, Recipe } from './types';

type Session = { key: number; detail: Detail; draft: Recipe | null };

export function usePhotoEditor() {
  const [session, setSession] = useState<Session | null>(null);
  const editorRef = useRef<Session | null>(null);
  const serial = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const confirmed = useRef(new Map<string, {revision: number; recipe: Recipe}>());
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved');
  const publish = useCallback((value: Session | null) => {
    editorRef.current = value;
    setSession(value);
  }, []);
  const activate = useCallback((detail: Detail) => {
    confirmed.current.set(detail.id, {revision: detail.revision, recipe: detail.recipe});
    publish({key: ++serial.current, detail, draft: structuredClone(detail.draft || detail.recipe)});
    setSaveState('saved');
  }, [publish]);
  const clear = useCallback(() => publish(null), [publish]);
  const setDraft = useCallback((value: SetStateAction<Recipe | null>) => {
    const current = editorRef.current;
    if (current) publish({...current, draft: typeof value === 'function' ? value(current.draft) : value});
  }, [publish]);
  const updateDetail = useCallback((key: number, update: (detail: Detail) => Detail) => {
    const current = editorRef.current;
    if (current?.key === key) publish({...current, detail: update(current.detail)});
  }, [publish]);
  const saveSnapshot = useCallback((explicit?: Recipe, source = 'manual') => {
    const current = editorRef.current;
    if (!current) return Promise.resolve();
    if (explicit) setDraft(explicit);
    const recipe = structuredClone(explicit || current.draft);
    if (!recipe) return Promise.resolve();
    // Identity, revision and pixels' recipe belong to the initiating session.
    // A queued operation must never take a later frame's current refs.
    const {id, revision} = current.detail;
    const key = current.key;
    const capturedClean = JSON.stringify(recipe) === JSON.stringify(current.detail.recipe);
    const save = async () => {
      // A navigation queued during a server-side restore must wait for it,
      // without saving the formerly clean recipe back over the restored version.
      if (capturedClean) return;
      const base = confirmed.current.get(id) || {revision, recipe: current.detail.recipe};
      if (JSON.stringify(recipe) === JSON.stringify(base.recipe)) return;
      if (editorRef.current?.key === key) setSaveState('saving');
      try {
        const saved = await api<{revision: number}>(`/photos/${id}/recipe`, {
          method: 'PUT', body: JSON.stringify({recipe, expected_revision: base.revision, source})
        });
        confirmed.current.set(id, {revision: saved.revision, recipe});
        updateDetail(key, detail => ({...detail, recipe, revision: saved.revision}));
        if (editorRef.current?.key === key) setSaveState('saved');
      } catch (error) {
        if (editorRef.current?.key === key) setSaveState('error');
        throw error;
      }
    };
    const pending = queue.current.then(save, save);
    queue.current = pending;
    return pending;
  }, [setDraft, updateDetail]);
  const persistDraft = useCallback(async (explicit?: Recipe, source = 'manual') => {
    const key = editorRef.current?.key;
    await saveSnapshot(explicit, source);
    // Include edits made while a save was in flight before allowing navigation.
    while (editorRef.current?.key === key && editorRef.current?.draft &&
      JSON.stringify(editorRef.current.draft) !== JSON.stringify(editorRef.current.detail.recipe)) {
      await saveSnapshot(undefined, 'manual');
    }
  }, [saveSnapshot]);
  const replaceRecipe = useCallback(async (action: (detail: Detail) => Promise<unknown>) => {
    const key = editorRef.current?.key;
    await persistDraft();
    const replace = async () => {
      const current = editorRef.current;
      if (!current || current.key !== key) return;
      const baseline = JSON.stringify(current.draft);
      setSaveState('saving');
      try {
        await action(current.detail);
        const updated = await api<Detail>(`/photos/${current.detail.id}`);
        confirmed.current.set(updated.id, {revision:updated.revision, recipe:updated.recipe});
        const active = editorRef.current;
        if (active?.key === key) {
          publish({...active, detail:updated,
            draft:JSON.stringify(active.draft) === baseline ? structuredClone(updated.recipe) : active.draft});
          setSaveState('saved');
        }
      } catch (error) {
        if (editorRef.current?.key === key) setSaveState('error');
        throw error;
      }
    };
    const pending = queue.current.then(replace, replace);
    queue.current = pending;
    return pending;
  }, [persistDraft, publish]);
  return {detail: session?.detail || null, draft: session?.draft || null,
    editorRef, activate, clear, setDraft, updateDetail, persistDraft, replaceRecipe, saveState, setSaveState};
}
