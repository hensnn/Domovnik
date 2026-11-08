import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { del, get, patch, post, postForm, put } from "./client";
import type {
  AiStatus,
  ApiToken,
  BulkResult,
  Category,
  ChangeSet,
  CommitResult,
  Conversation,
  Dashboard,
  DetectionDecision,
  FileLink,
  FileRole,
  Item,
  ItemFilters,
  ItemPage,
  Location,
  LocationKind,
  Movement,
  PhotoAnalysis,
  SearchResults,
  SearchScope,
  SettingDef,
  StoredMessage,
  Tag,
  UploadResult,
  User,
} from "./types";

// --- Čtení --------------------------------------------------------------------------------

export const useLocations = (includeArchived = false) =>
  useQuery({
    queryKey: ["locations", { includeArchived }],
    queryFn: () => get<Location[]>("/locations", { include_archived: includeArchived }),
  });

export const useCategories = () =>
  useQuery({ queryKey: ["categories"], queryFn: () => get<Category[]>("/categories") });

export const useTags = () => useQuery({ queryKey: ["tags"], queryFn: () => get<Tag[]>("/tags") });

export const useItems = (filters: ItemFilters) =>
  useQuery({
    queryKey: ["items", filters],
    queryFn: () => get<ItemPage>("/items", { ...filters }),
    placeholderData: keepPreviousData,
  });

export const useItem = (id: string | undefined) =>
  useQuery({
    queryKey: ["item", id],
    queryFn: () => get<Item>(`/items/${id}`),
    enabled: !!id,
  });

export const useItemMovements = (id: string | undefined) =>
  useQuery({
    queryKey: ["item", id, "movements"],
    queryFn: () => get<Movement[]>(`/items/${id}/movements`),
    enabled: !!id,
  });

export const useDashboard = () =>
  useQuery({ queryKey: ["stats"], queryFn: () => get<Dashboard>("/stats") });

export const useSearch = (
  q: string,
  opts: { scope?: SearchScope; kinds?: LocationKind[]; limit?: number } = {},
) => {
  const { scope = "all", kinds = [], limit = 8 } = opts;
  return useQuery({
    queryKey: ["search", q, scope, kinds, limit],
    queryFn: () => get<SearchResults>("/search", { q, limit, scope, kind: kinds }),
    enabled: q.trim().length > 0 || kinds.length > 0,
    placeholderData: keepPreviousData,
  });
};

export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => get<SettingDef[]>("/settings") });

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: ["users"], queryFn: () => get<User[]>("/users"), enabled });

export const useTokens = () =>
  useQuery({ queryKey: ["tokens"], queryFn: () => get<ApiToken[]>("/tokens") });

export const useItemFiles = (id: string | undefined) =>
  useQuery({
    queryKey: ["item", id, "files"],
    queryFn: () => get<FileLink[]>(`/items/${id}/files`),
    enabled: !!id,
  });

export const useLocationFiles = (id: string | undefined) =>
  useQuery({
    queryKey: ["location-files", id],
    queryFn: () => get<FileLink[]>(`/locations/${id}/files`),
    enabled: !!id,
  });

export const useAiStatus = () =>
  useQuery({
    queryKey: ["ai", "status"],
    queryFn: () => get<AiStatus>("/ai/status"),
    retry: false,
  });

export const useConversations = () =>
  useQuery({
    queryKey: ["ai", "conversations"],
    queryFn: () => get<Conversation[]>("/ai/conversations", { limit: 50 }),
  });

// --- Zápis --------------------------------------------------------------------------------

/** Po každé změně dat zneplatní všechny cache s daty (jednoduché a spolehlivé). */
export function useInvalidateData() {
  const qc = useQueryClient();
  return () => {
    for (const key of [
      "items",
      "item",
      "locations",
      "location-files",
      "categories",
      "tags",
      "stats",
      "search",
    ]) {
      void qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function useApiMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  options: { invalidate?: boolean; onSuccess?: (res: TRes, vars: TVars) => void } = {},
) {
  const invalidate = useInvalidateData();
  return useMutation({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      if (options.invalidate !== false) invalidate();
      options.onSuccess?.(res, vars);
    },
  });
}

export const api_ = {
  createItem: (body: unknown) => post<Item>("/items", body),
  updateItem: (id: string, body: unknown, version?: number) =>
    patch<Item>(`/items/${id}`, body, version ? { "If-Match": `"${version}"` } : undefined),
  deleteItem: (id: string) => del<void>(`/items/${id}`),
  restoreItem: (id: string) => post<Item>(`/items/${id}/restore`),
  purgeItem: (id: string) => del<void>(`/items/${id}/purge`),
  moveItem: (id: string, body: unknown) => post<Item>(`/items/${id}/move`, body),
  placeItem: (id: string, body: unknown) => post<Item>(`/items/${id}/place`, body),
  adjustItem: (id: string, body: unknown) => post<Item>(`/items/${id}/adjust`, body),
  removeItem: (id: string, body: unknown) => post<Item>(`/items/${id}/remove`, body),
  bulk: (body: unknown) => post<BulkResult>("/items/bulk", body),
  createLocation: (body: unknown) => post<Location>("/locations", body),
  updateLocation: (id: string, body: unknown) => patch<Location>(`/locations/${id}`, body),
  archiveLocation: (id: string) => post<Location>(`/locations/${id}/archive`),
  unarchiveLocation: (id: string) => post<Location>(`/locations/${id}/unarchive`),
  deleteLocation: (id: string) => del<void>(`/locations/${id}`),
  createCategory: (body: unknown) => post<Category>("/categories", body),
  updateCategory: (id: string, body: unknown) => patch<Category>(`/categories/${id}`, body),
  mergeCategory: (id: string, targetId: string) =>
    post<Category>(`/categories/${id}/merge`, { target_id: targetId }),
  deleteCategory: (id: string, reassignTo?: string) =>
    del<void>(`/categories/${id}`, { reassign_to: reassignTo }),
  renameTag: (id: string, name: string) => patch<Tag>(`/tags/${id}`, { name }),
  deleteTag: (id: string) => del<void>(`/tags/${id}`),
  putSetting: (key: string, value: unknown, scope: "global" | "user") =>
    put<void>(`/settings/${key}`, { value, scope }),
  resetSetting: (key: string, scope: "global" | "user") => del<void>(`/settings/${key}`, { scope }),
  createUser: (body: unknown) => post<User>("/users", body),
  patchUser: (id: string, body: unknown) => patch<User>(`/users/${id}`, body),
  createToken: (body: unknown) => post<ApiToken & { token: string }>("/tokens", body),
  revokeToken: (id: string) => del<void>(`/tokens/${id}`),
  changePassword: (body: unknown) => post<void>("/auth/password", body),
  // AI asistent
  applyChangeSet: (id: string, skipOperationIds: string[] = []) =>
    post<ChangeSet>(`/ai/change-sets/${id}/apply`, { skip_operation_ids: skipOperationIds }),
  rejectChangeSet: (id: string) => post<ChangeSet>(`/ai/change-sets/${id}/reject`),
  undoChangeSet: (id: string) => post<ChangeSet>(`/ai/change-sets/${id}/undo`),
  deleteConversation: (id: string) => del<void>(`/ai/conversations/${id}`),
  conversationMessages: (id: string) => get<StoredMessage[]>(`/ai/conversations/${id}/messages`),
  // Soubory
  uploadFile: (
    file: File,
    target: { item_id?: string; location_id?: string; role?: FileRole; caption?: string } = {},
    signal?: AbortSignal,
  ) => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, v] of Object.entries(target)) if (v) form.append(k, v);
    return postForm<UploadResult>("/files", form, signal);
  },
  updateFileLink: (
    id: string,
    body: { role?: FileRole; caption?: string | null; is_primary?: boolean },
  ) => patch<FileLink>(`/file-links/${id}`, body),
  deleteFileLink: (id: string) => del<void>(`/file-links/${id}`),
  // Čtení fotek AI
  analyzePhoto: (body: { file_id: string; context_location_id?: string; hint?: string }) =>
    post<{ id: string; status: string }>("/photos/analyze", body),
  getAnalysis: (id: string, signal?: AbortSignal) =>
    get<PhotoAnalysis>(`/photos/analyses/${id}`, undefined, signal),
  commitAnalysis: (id: string, decisions: DetectionDecision[]) =>
    post<CommitResult>(`/photos/analyses/${id}/commit`, { decisions }),
};
