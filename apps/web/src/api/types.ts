// Typy odpovídající schématům API (apps/api/src/domovnik/schemas.py)

export type ItemStatus = "stored" | "in_use" | "lent" | "repair" | "discarded" | "sold" | "lost";
export type LocationKind =
  "building" | "floor" | "room" | "zone" | "furniture" | "shelf" | "drawer" | "box" | "other";

export interface User {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  role: "admin" | "member" | "viewer" | "guest";
  locale: string;
  timezone: string;
  is_active: boolean;
  last_login_at: string | null;
}

export interface Me {
  user: User;
  scopes: string[];
  csrf_token: string | null;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
}

export interface Location {
  id: string;
  parent_id: string | null;
  kind: LocationKind;
  name: string;
  label_code: string;
  description: string | null;
  notes: string | null;
  is_movable: boolean;
  color: string | null;
  icon: string | null;
  sort_order: number;
  attributes: Record<string, unknown>;
  depth: number | null;
  archived_at: string | null;
  version: number;
  full_name: string | null;
  item_count: number;
  direct_item_count: number;
}

export interface Category {
  id: string;
  parent_id: string | null;
  name: string;
  slug: string;
  description: string | null;
  color: string | null;
  icon: string | null;
  sort_order: number;
  version: number;
  item_count: number;
  direct_item_count: number;
  full_name: string | null;
}

export interface Tag {
  id: string;
  name: string;
  color: string | null;
  item_count: number;
}

export interface Placement {
  location_id: string;
  quantity: string;
  note: string | null;
  location_label: string | null;
  location_path: string | null;
}

export interface Item {
  id: string;
  label_code: string;
  name: string;
  aliases: string[];
  description: string | null;
  notes: string | null;
  category_id: string | null;
  category_path: string | null;
  status: ItemStatus;
  is_consumable: boolean;
  unit: string;
  min_quantity: string | null;
  home_location_id: string | null;
  brand: string | null;
  model: string | null;
  serial_no: string | null;
  ean: string | null;
  purchase_date: string | null;
  purchase_price: string | null;
  currency: string;
  purchase_place: string | null;
  warranty_until: string | null;
  expires_at: string | null;
  est_value: string | null;
  condition: string | null;
  owner_id: string | null;
  attributes: Record<string, unknown>;
  primary_file_id: string | null;
  file_count?: number;
  created_at: string;
  updated_at: string;
  version: number;
  deleted_at: string | null;
  tags: string[];
  placements: Placement[];
  total_quantity: string;
  is_low_stock: boolean;
}

export interface ItemPage {
  items: Item[];
  total: number;
  limit: number;
  offset: number;
}

export interface Movement {
  id: number;
  item_id: string;
  kind: string;
  from_location_id: string | null;
  to_location_id: string | null;
  quantity: string | null;
  moved_at: string;
  actor_id: string | null;
  source: string;
  note: string | null;
}

export interface SearchResults {
  items: Item[];
  locations: Location[];
  categories: Category[];
  /** počty všech nálezů (před ořezem limitem) */
  totals: Record<"items" | "locations" | "categories", number>;
}

export type SearchScope = "all" | "items" | "locations" | "categories";

export interface Dashboard {
  counts: Record<
    | "items"
    | "locations"
    | "categories"
    | "unplaced"
    | "uncategorized"
    | "low_stock"
    | "warranty_soon"
    | "expiring_soon"
    | "trash",
    number
  >;
  low_stock: Item[];
  warranty_soon: Item[];
  expiring_soon: Item[];
  recent_movements: Movement[];
}

export interface SettingDef {
  key: string;
  group: string;
  group_label: string;
  label: string;
  description: string;
  type: "string" | "text" | "int" | "float" | "bool" | "enum" | "string_list" | "secret";
  scope: "global" | "user";
  choices: string[];
  min: number | null;
  max: number | null;
  restart_required: boolean;
  admin_only: boolean;
  default: unknown;
  value: unknown;
  is_default: boolean;
  has_value: boolean;
}

export interface ApiToken {
  id: string;
  name: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ItemFilters {
  q?: string;
  category_id?: string;
  location_id?: string;
  status?: ItemStatus | "";
  tag?: string[];
  unplaced?: boolean;
  low_stock?: boolean;
  trash?: boolean;
  /** druh umístění (kterýkoli z nich) */
  location_kind?: LocationKind[];
  brand?: string;
  condition?: string;
  has_photo?: boolean;
  no_category?: boolean;
  min_price?: string;
  max_price?: string;
  purchased_after?: string;
  purchased_before?: string;
  min_qty?: string;
  max_qty?: string;
  created_after?: string;
  updated_after?: string;
  warranty_before?: string;
  expires_before?: string;
  expired?: boolean;
  warranty_active?: boolean;
  sort?: string;
  desc?: boolean;
  limit?: number;
  offset?: number;
}

export interface BulkResult {
  ok: number;
  failed: { id: string; error: string }[];
}

// --- AI asistent ------------------------------------------------------------------------

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  provider: string;
  model: string;
  trust_level: string;
  requests_today: number;
  requests_per_day_limit: number;
}

export type ChangeSetStatus =
  "proposed" | "applied" | "partially_applied" | "rejected" | "undone" | "failed";

export interface ChangeOperation {
  id: string;
  seq: number;
  op: string;
  description: string;
  status: string;
  error: string | null;
}

export interface ChangeSet {
  id: string;
  summary: string;
  status: ChangeSetStatus;
  auto_applied?: boolean;
  created_at?: string | null;
  risky: boolean;
  needs_ui_confirmation: boolean;
  reversible: boolean | null;
  operations: ChangeOperation[];
}

export interface Conversation {
  id: string;
  title: string | null;
  channel: string;
  created_at: string;
}

export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export type ChatEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "tool_call"; name: string; arguments?: Record<string, unknown> }
  | { type: "change_set"; change_set: ChangeSet }
  | { type: "message"; text: string }
  | { type: "done"; conversation_id: string; reply: string; error?: string | null }
  | { type: "error"; message: string };

// --- Soubory ----------------------------------------------------------------------------

export type FileRole = "primary" | "gallery" | "manual" | "receipt" | "warranty" | "other";

export interface FileInfo {
  id: string;
  kind: "photo" | "document";
  mime: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  original_name: string | null;
  caption: string | null;
  taken_at: string | null;
  blurhash: string | null;
  thumbs_ready: boolean;
  created_at: string;
  url: string;
  thumb_256_url: string | null;
  thumb_1024_url: string | null;
}

export interface FileLink {
  id: string;
  item_id: string | null;
  location_id: string | null;
  role: FileRole;
  is_primary: boolean;
  sort_order: number;
  caption: string | null;
  created_at: string;
  file: FileInfo;
}

export interface UploadResult {
  file: FileInfo;
  link: FileLink | null;
  duplicate: boolean;
}

// --- Čtení fotek AI (F7) ----------------------------------------------------------------

export type AnalysisStatus = "queued" | "running" | "done" | "failed";
export type DetectionStatus = "pending" | "accepted" | "edited" | "rejected" | "merged";

export interface DetectionSuggestion {
  name: string;
  category_path: string[];
  tags: string[];
  brand?: string | null;
  model?: string | null;
  quantity: number;
  unit: string;
  notes?: string | null;
  text_read?: string | null;
}

export interface Detection {
  id: string;
  label: string;
  description?: string | null;
  /** [x, y, w, h] normalizované 0–1 vůči fotce */
  bbox: [number, number, number, number] | null;
  confidence: number;
  status: DetectionStatus;
  suggested: DetectionSuggestion;
  suggested_location: {
    id: string | null;
    path: string[] | null;
    full_name?: string | null;
    reason?: string | null;
  } | null;
  matched_item: {
    id: string;
    name: string;
    label_code: string;
    location_path?: string | null;
  } | null;
  item_id?: string | null;
}

export interface PhotoAnalysis {
  id: string;
  status: AnalysisStatus;
  error?: string | null;
  file_id: string;
  scene?: string | null;
  detections: Detection[];
}

export interface DetectionOverrides {
  name?: string;
  category_path?: string[];
  tags?: string[];
  brand?: string;
  model?: string;
  quantity?: number;
  unit?: string;
  notes?: string;
  location_id?: string;
  location_path?: string[];
}

export interface DetectionDecision {
  detection_id: string;
  action: "accept" | "reject" | "merge";
  overrides?: DetectionOverrides;
}

export interface CommitResult {
  change_set: ChangeSet;
  created_item_ids: string[];
}
