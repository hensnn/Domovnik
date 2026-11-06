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
}

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
  sort?: string;
  desc?: boolean;
  limit?: number;
  offset?: number;
}

export interface BulkResult {
  ok: number;
  failed: { id: string; error: string }[];
}
