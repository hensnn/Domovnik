-- =====================================================================
--  Domácí inventář – databázové schéma v0.1 (PostgreSQL 16+)
--  Rozšíření: ltree, pg_trgm, unaccent, citext, vector (pgvector)
--  Pozn.: v projektu se bude spravovat přes Alembic; tento soubor je
--  referenční návrh (a použitelný jako první migrace).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------
-- 0) Pomocné funkce
-- ---------------------------------------------------------------------

-- unaccent() není IMMUTABLE, pro indexy potřebujeme obal
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
$$ SELECT public.unaccent('public.unaccent', $1) $$;

-- updated_at + optimistic locking (version)
CREATE OR REPLACE FUNCTION touch_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  NEW.version    := COALESCE(OLD.version, 0) + 1;
  RETURN NEW;
END $$;

-- ---------------------------------------------------------------------
-- 1) Uživatelé, tokeny, nastavení
-- ---------------------------------------------------------------------

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username      citext NOT NULL UNIQUE,
  display_name  text   NOT NULL,
  email         citext,
  password_hash text,                                  -- argon2id; NULL = jen SSO/token
  role          text   NOT NULL DEFAULT 'member'
                CHECK (role IN ('admin','member','viewer','guest')),
  locale        text   NOT NULL DEFAULT 'cs',
  timezone      text   NOT NULL DEFAULT 'Europe/Prague',
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

CREATE TABLE api_tokens (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name         text NOT NULL,
  token_hash   text NOT NULL UNIQUE,                   -- ukládá se jen hash (sha256)
  scopes       text[] NOT NULL DEFAULT '{items:read}',  -- items:read, items:write, ai:chat, admin, ...
  expires_at   timestamptz,
  last_used_at timestamptz,
  revoked_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Nastavení: katalog klíčů + JSON schéma žije v kódu (settings registry),
-- DB drží jen hodnoty. UI se z registru generuje automaticky.
CREATE TABLE settings (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope      text NOT NULL CHECK (scope IN ('global','user')),
  user_id    uuid REFERENCES users(id) ON DELETE CASCADE,
  key        text NOT NULL,                             -- např. 'tts.engine', 'mqtt.broker.host'
  value      jsonb NOT NULL,
  is_secret  boolean NOT NULL DEFAULT false,            -- hodnota šifrována (Fernet/age) na úrovni aplikace
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users(id),
  CHECK ((scope = 'global' AND user_id IS NULL) OR (scope = 'user' AND user_id IS NOT NULL))
);
CREATE UNIQUE INDEX settings_global_uq ON settings (key) WHERE scope = 'global';
CREATE UNIQUE INDEX settings_user_uq   ON settings (user_id, key) WHERE scope = 'user';

-- ---------------------------------------------------------------------
-- 2) Umístění (strom: dům › patro › místnost › nábytek › police › krabice)
-- ---------------------------------------------------------------------

CREATE TABLE locations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   uuid REFERENCES locations(id) ON DELETE RESTRICT,
  kind        text NOT NULL DEFAULT 'other'
              CHECK (kind IN ('building','floor','room','zone','furniture','shelf','drawer','box','other')),
  name        text NOT NULL,
  label_code  text NOT NULL UNIQUE,                     -- text na fyzickém štítku / QR, např. 'L-GAR-A3'
  description text,
  notes       text,
  is_movable  boolean NOT NULL DEFAULT false,           -- krabice/kufr/toolbox: přesun = změna parent_id celého podstromu
  color       text,
  icon        text,
  sort_order  int  NOT NULL DEFAULT 0,
  attributes  jsonb NOT NULL DEFAULT '{}',              -- rozměry, kapacita, ...
  path        ltree,                                    -- udržuje trigger
  depth       int,                                      -- udržuje trigger
  archived_at timestamptz,
  created_by  uuid REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  version     int NOT NULL DEFAULT 1,
  CHECK (parent_id IS DISTINCT FROM id)
);
CREATE INDEX locations_path_gist ON locations USING gist (path);
CREATE INDEX locations_parent_idx ON locations (parent_id);
CREATE UNIQUE INDEX locations_sibling_name_uq
  ON locations (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name))
  WHERE archived_at IS NULL;
CREATE INDEX locations_name_trgm ON locations USING gin (immutable_unaccent(name) gin_trgm_ops);

CREATE OR REPLACE FUNCTION locations_set_path() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent_path ltree;
  lbl         ltree;
BEGIN
  lbl := replace(NEW.id::text, '-', '_')::ltree;
  IF NEW.parent_id IS NULL THEN
    NEW.path := lbl;
  ELSE
    SELECT path INTO parent_path FROM locations WHERE id = NEW.parent_id;
    IF parent_path IS NULL THEN
      RAISE EXCEPTION 'Nadřazené umístění % neexistuje', NEW.parent_id;
    END IF;
    IF TG_OP = 'UPDATE' AND parent_path <@ OLD.path THEN
      RAISE EXCEPTION 'Přesun by vytvořil cyklus ve stromu umístění';
    END IF;
    NEW.path := parent_path || lbl;
  END IF;
  NEW.depth := nlevel(NEW.path) - 1;

  -- přesun podstromu: přepočítat potomky
  IF TG_OP = 'UPDATE' AND NEW.path IS DISTINCT FROM OLD.path THEN
    UPDATE locations
       SET path  = NEW.path || subpath(path, nlevel(OLD.path)),
           depth = nlevel(NEW.path) + (nlevel(path) - nlevel(OLD.path)) - 1
     WHERE path <@ OLD.path AND id <> NEW.id;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER locations_path_trg
  BEFORE INSERT OR UPDATE OF parent_id ON locations
  FOR EACH ROW EXECUTE FUNCTION locations_set_path();
CREATE TRIGGER locations_touch_trg
  BEFORE UPDATE ON locations
  FOR EACH ROW EXECUTE FUNCTION touch_row();

-- ---------------------------------------------------------------------
-- 3) Kategorie, vlastní pole, štítky (tagy)
-- ---------------------------------------------------------------------

CREATE TABLE categories (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   uuid REFERENCES categories(id) ON DELETE RESTRICT,
  name        text NOT NULL,
  slug        text NOT NULL UNIQUE,
  description text,
  color       text,
  icon        text,
  sort_order  int NOT NULL DEFAULT 0,
  created_by  uuid REFERENCES users(id),     -- NULL = vytvořeno systémem/AI se zaznamenáním v audit_log
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  version     int NOT NULL DEFAULT 1,
  CHECK (parent_id IS DISTINCT FROM id)
);
CREATE UNIQUE INDEX categories_sibling_name_uq
  ON categories (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name));
CREATE TRIGGER categories_touch_trg BEFORE UPDATE ON categories
  FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Definice vlastních polí (hodnoty jsou v items.attributes). category_id NULL = globální;
-- pole se dědí do podkategorií.
CREATE TABLE custom_field_defs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id uuid REFERENCES categories(id) ON DELETE CASCADE,
  key         text NOT NULL,
  label       text NOT NULL,
  type        text NOT NULL CHECK (type IN ('text','number','date','bool','select','multiselect','url')),
  options     jsonb,                     -- pro select/multiselect
  unit        text,
  is_required boolean NOT NULL DEFAULT false,
  sort_order  int NOT NULL DEFAULT 0,
  UNIQUE NULLS NOT DISTINCT (category_id, key)
);

CREATE TABLE tags (
  id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name  citext NOT NULL UNIQUE,
  color text
);

-- ---------------------------------------------------------------------
-- 4) Soubory (fotky, dokumenty) – nejdřív kvůli FK z items
-- ---------------------------------------------------------------------

CREATE TABLE files (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind         text NOT NULL CHECK (kind IN ('photo','document')),
  sha256       bytea NOT NULL UNIQUE,                  -- deduplikace
  storage_path text  NOT NULL,                         -- relativní cesta v /data/files
  original_name text,
  mime         text NOT NULL,
  size_bytes   bigint NOT NULL,
  width        int,
  height       int,
  taken_at     timestamptz,                            -- z EXIF
  exif         jsonb,                                  -- GPS se ve výchozím stavu odstraní
  blurhash     text,                                   -- placeholder při načítání
  thumbs_ready boolean NOT NULL DEFAULT false,         -- thumbnails: 256/1024 px + WebP
  ocr_text     text,                                   -- pro dokumenty/účtenky
  caption      text,
  uploaded_by  uuid REFERENCES users(id),
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 5) Věci
-- ---------------------------------------------------------------------

CREATE SEQUENCE item_label_seq START 1;

CREATE TABLE items (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  label_code       text NOT NULL UNIQUE
                   DEFAULT ('I-' || lpad(nextval('item_label_seq')::text, 6, '0')),
  name             text NOT NULL,
  aliases          text[] NOT NULL DEFAULT '{}',      -- synonyma: "aku šroubovák", "vrtačka"
  description      text,
  notes            text,
  category_id      uuid REFERENCES categories(id) ON DELETE SET NULL,
  status           text NOT NULL DEFAULT 'stored'
                   CHECK (status IN ('stored','in_use','lent','repair','discarded','sold','lost')),
  is_consumable    boolean NOT NULL DEFAULT false,
  unit             text NOT NULL DEFAULT 'ks',
  min_quantity     numeric(12,3),                     -- práh pro "dochází zásoba"
  home_location_id uuid REFERENCES locations(id) ON DELETE SET NULL,   -- kam věc patří (pro "vrať na místo")
  brand            text,
  model            text,
  serial_no        text,
  ean              text,
  purchase_date    date,
  purchase_price   numeric(12,2),
  currency         char(3) NOT NULL DEFAULT 'CZK',
  purchase_place   text,
  warranty_until   date,
  expires_at       date,
  est_value        numeric(12,2),                     -- odhad hodnoty (pojištění)
  condition        text CHECK (condition IN ('new','good','worn','broken')),
  owner_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  attributes       jsonb NOT NULL DEFAULT '{}',       -- hodnoty custom_field_defs
  primary_file_id  uuid REFERENCES files(id) ON DELETE SET NULL,
  last_seen_at     timestamptz,                       -- naposledy potvrzeno při inventuře
  last_used_at     timestamptz,
  search_tsv       tsvector,                          -- udržuje trigger
  created_by       uuid REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_by       uuid REFERENCES users(id),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  version          int NOT NULL DEFAULT 1,
  deleted_at       timestamptz                        -- koš (soft delete)
);
CREATE INDEX items_category_idx   ON items (category_id) WHERE deleted_at IS NULL;
CREATE INDEX items_status_idx     ON items (status)      WHERE deleted_at IS NULL;
CREATE INDEX items_home_idx       ON items (home_location_id);
CREATE INDEX items_search_gin     ON items USING gin (search_tsv);
CREATE INDEX items_name_trgm      ON items USING gin (immutable_unaccent(name) gin_trgm_ops);
CREATE INDEX items_attributes_gin ON items USING gin (attributes jsonb_path_ops);
CREATE INDEX items_warranty_idx   ON items (warranty_until) WHERE warranty_until IS NOT NULL;
CREATE INDEX items_expires_idx    ON items (expires_at)     WHERE expires_at IS NOT NULL;
CREATE INDEX items_ean_idx        ON items (ean)            WHERE ean IS NOT NULL;

CREATE TABLE item_tags (
  item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag_id  uuid NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
  PRIMARY KEY (item_id, tag_id)
);
CREATE INDEX item_tags_tag_idx ON item_tags (tag_id);

-- Fulltext: bez diakritiky, 'simple' konfigurace (čeština nemá ve výchozí PG slovník);
-- skloňování řeší pg_trgm + sémantické hledání (embeddings) + aliasy.
CREATE OR REPLACE FUNCTION items_build_search() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  tag_text text;
BEGIN
  SELECT string_agg(t.name::text, ' ') INTO tag_text
    FROM item_tags it JOIN tags t ON t.id = it.tag_id
   WHERE it.item_id = NEW.id;

  NEW.search_tsv :=
      setweight(to_tsvector('simple', immutable_unaccent(COALESCE(NEW.name, ''))), 'A')
   || setweight(to_tsvector('simple', immutable_unaccent(COALESCE(array_to_string(NEW.aliases, ' '), ''))), 'A')
   || setweight(to_tsvector('simple', immutable_unaccent(COALESCE(tag_text, ''))), 'B')
   || setweight(to_tsvector('simple', immutable_unaccent(
        COALESCE(NEW.brand, '') || ' ' || COALESCE(NEW.model, '') || ' ' || COALESCE(NEW.serial_no, ''))), 'B')
   || setweight(to_tsvector('simple', immutable_unaccent(
        COALESCE(NEW.description, '') || ' ' || COALESCE(NEW.notes, ''))), 'C');
  RETURN NEW;
END $$;

CREATE TRIGGER items_search_trg
  BEFORE INSERT OR UPDATE ON items
  FOR EACH ROW EXECUTE FUNCTION items_build_search();
CREATE TRIGGER items_touch_trg
  BEFORE UPDATE ON items
  FOR EACH ROW EXECUTE FUNCTION touch_row();

-- změna tagů přegeneruje search_tsv (UPDATE spustí BEFORE UPDATE trigger)
CREATE OR REPLACE FUNCTION item_tags_refresh_search() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE items SET updated_at = updated_at
   WHERE id = COALESCE(NEW.item_id, OLD.item_id);
  RETURN NULL;
END $$;
CREATE TRIGGER item_tags_search_trg
  AFTER INSERT OR DELETE ON item_tags
  FOR EACH ROW EXECUTE FUNCTION item_tags_refresh_search();

-- Sémantické hledání. Dimenze 1024 odpovídá bge-m3 / multilingual-e5-large;
-- při změně modelu se tabulka přegeneruje (viz docs).
CREATE TABLE item_embeddings (
  item_id      uuid PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  model        text NOT NULL,
  content_hash text NOT NULL,                         -- přegenerovat jen když se změnil text
  embedding    vector(1024) NOT NULL,
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX item_embeddings_hnsw ON item_embeddings USING hnsw (embedding vector_cosine_ops);

-- Vazba souborů na věci / umístění (fotka věci, fotka police, návod, účtenka…)
CREATE TABLE file_links (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id     uuid NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  item_id     uuid REFERENCES items(id) ON DELETE CASCADE,
  location_id uuid REFERENCES locations(id) ON DELETE CASCADE,
  role        text NOT NULL DEFAULT 'gallery'
              CHECK (role IN ('primary','gallery','manual','receipt','warranty','other')),
  sort_order  int NOT NULL DEFAULT 0,
  caption     text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(item_id, location_id) = 1)
);
CREATE INDEX file_links_item_idx ON file_links (item_id)     WHERE item_id IS NOT NULL;
CREATE INDEX file_links_loc_idx  ON file_links (location_id) WHERE location_id IS NOT NULL;
CREATE INDEX file_links_file_idx ON file_links (file_id);

-- ---------------------------------------------------------------------
-- 6) Kde co je: umístění věcí (množství může být rozdělené do více míst)
--    Věc bez řádku v item_placements = "nezařazeno" (příjmový koš).
-- ---------------------------------------------------------------------

CREATE TABLE item_placements (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id     uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  location_id uuid NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
  quantity    numeric(12,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  note        text,
  placed_at   timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  version     int NOT NULL DEFAULT 1,
  UNIQUE (item_id, location_id)
);
CREATE INDEX item_placements_loc_idx ON item_placements (location_id);
CREATE TRIGGER item_placements_touch_trg BEFORE UPDATE ON item_placements
  FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Historie pohybů (kdo, kdy, odkud, kam, přes jaký kanál)
CREATE TABLE movements (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  item_id          uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  kind             text NOT NULL CHECK (kind IN ('create','place','move','remove','adjust','dispose')),
  from_location_id uuid REFERENCES locations(id) ON DELETE SET NULL,
  to_location_id   uuid REFERENCES locations(id) ON DELETE SET NULL,
  quantity         numeric(12,3),
  moved_at         timestamptz NOT NULL DEFAULT now(),
  actor_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  source           text NOT NULL DEFAULT 'ui'
                   CHECK (source IN ('ui','ai','voice','api','mqtt','import','inventory')),
  change_set_id    uuid,                      -- FK doplněna níže (ai_change_sets)
  note             text
);
CREATE INDEX movements_item_idx ON movements (item_id, moved_at DESC);
CREATE INDEX movements_time_idx ON movements (moved_at DESC);

-- ---------------------------------------------------------------------
-- 7) AI: konverzace, návrhy změn (change sets), analýza fotek
-- ---------------------------------------------------------------------

CREATE TABLE ai_conversations (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      text,
  channel    text NOT NULL DEFAULT 'text' CHECK (channel IN ('text','voice','api')),
  context    jsonb NOT NULL DEFAULT '{}',    -- např. aktuálně otevřené umístění ("jsem v garáži")
  archived   boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_messages (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user','assistant','tool','system')),
  content         text,
  tool_calls      jsonb,                      -- co asistent volal
  tool_result     jsonb,
  file_ids        uuid[] NOT NULL DEFAULT '{}',  -- přiložené fotky
  model           text,
  tokens_in       int,
  tokens_out      int,
  cost_usd        numeric(10,5),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ai_messages_conv_idx ON ai_messages (conversation_id, id);

-- Každá změna od AI (nebo hromadná operace) prochází "balíčkem změn":
-- navrženo → schváleno/aplikováno → případně vráceno (undo přes inverse).
CREATE TABLE ai_change_sets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid REFERENCES ai_conversations(id) ON DELETE SET NULL,
  user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  summary         text NOT NULL,              -- lidsky čitelný popis ("Přesunu 12 položek do Krabice B")
  status          text NOT NULL DEFAULT 'proposed'
                  CHECK (status IN ('proposed','applied','partially_applied','rejected','undone','failed','expired')),
  auto_applied    boolean NOT NULL DEFAULT false,   -- aplikováno bez potvrzení (dle nastavení důvěry)
  created_at      timestamptz NOT NULL DEFAULT now(),
  decided_at      timestamptz,
  applied_at      timestamptz,
  undone_at       timestamptz
);

CREATE TABLE ai_change_ops (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  change_set_id uuid NOT NULL REFERENCES ai_change_sets(id) ON DELETE CASCADE,
  seq           int  NOT NULL,
  op            text NOT NULL CHECK (op IN (
                  'create_item','update_item','delete_item','move_item','set_quantity',
                  'create_location','update_location','move_location','archive_location',
                  'create_category','update_category','merge_categories','delete_category',
                  'add_tag','remove_tag','create_custom_field')),
  payload       jsonb NOT NULL,               -- parametry operace
  inverse       jsonb,                        -- vyplní se při aplikaci → umožní undo
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','applied','skipped','failed','undone')),
  error         text,
  result_id     uuid,                         -- id vytvořené/změněné entity
  UNIQUE (change_set_id, seq)
);

ALTER TABLE movements
  ADD CONSTRAINT movements_change_set_fk
  FOREIGN KEY (change_set_id) REFERENCES ai_change_sets(id) ON DELETE SET NULL;

CREATE TABLE photo_analyses (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id             uuid NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  context_location_id uuid REFERENCES locations(id) ON DELETE SET NULL,   -- "fotka je z police B2"
  user_hint           text,                                               -- "tohle jsou věci po babičce"
  provider            text NOT NULL,                                      -- anthropic | ollama | openai-compat
  model               text NOT NULL,
  prompt_version      text NOT NULL,
  status              text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','running','done','failed')),
  result              jsonb,                                              -- surový strukturovaný výstup
  error               text,
  tokens_in           int,
  tokens_out          int,
  cost_usd            numeric(10,5),
  created_by          uuid REFERENCES users(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  finished_at         timestamptz
);
CREATE INDEX photo_analyses_file_idx ON photo_analyses (file_id);

CREATE TABLE photo_detections (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id           uuid NOT NULL REFERENCES photo_analyses(id) ON DELETE CASCADE,
  label                 text NOT NULL,                 -- co AI vidí
  bbox                  jsonb,                         -- [x, y, w, h] normalizované 0–1
  confidence            numeric(4,3),
  suggested             jsonb NOT NULL DEFAULT '{}',   -- name, category_path, tags, brand, quantity, attributes…
  suggested_location_id uuid REFERENCES locations(id) ON DELETE SET NULL,
  suggestion_reason     text,                          -- proč AI navrhuje toto místo
  matched_item_id       uuid REFERENCES items(id) ON DELETE SET NULL,   -- pravděpodobný duplikát
  status                text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','accepted','edited','rejected','merged')),
  item_id               uuid REFERENCES items(id) ON DELETE SET NULL,   -- výsledná věc
  decided_by            uuid REFERENCES users(id),
  decided_at            timestamptz
);
CREATE INDEX photo_detections_analysis_idx ON photo_detections (analysis_id);

-- ---------------------------------------------------------------------
-- 8) Audit log (generický trigger – pokrývá UI, API, MQTT i import)
-- ---------------------------------------------------------------------

CREATE TABLE audit_log (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at            timestamptz NOT NULL DEFAULT now(),
  actor_id      uuid,
  source        text,                      -- ui | ai | voice | api | mqtt | import
  entity_type   text NOT NULL,
  entity_id     uuid NOT NULL,
  action        text NOT NULL CHECK (action IN ('insert','update','delete')),
  before        jsonb,
  after         jsonb,
  change_set_id uuid,
  request_id    text
);
CREATE INDEX audit_entity_idx ON audit_log (entity_type, entity_id, at DESC);
CREATE INDEX audit_time_idx   ON audit_log (at DESC);

-- Aplikace na začátku transakce nastaví:
--   SET LOCAL app.actor_id = '<uuid>'; SET LOCAL app.source = 'ai'; SET LOCAL app.change_set_id = '<uuid>';
CREATE OR REPLACE FUNCTION audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  rec_id uuid;
BEGIN
  rec_id := COALESCE((to_jsonb(NEW)->>'id'), (to_jsonb(OLD)->>'id'))::uuid;
  INSERT INTO audit_log (actor_id, source, entity_type, entity_id, action, before, after, change_set_id, request_id)
  VALUES (
    NULLIF(current_setting('app.actor_id', true), '')::uuid,
    NULLIF(current_setting('app.source', true), ''),
    TG_TABLE_NAME,
    rec_id,
    lower(TG_OP),
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) - 'search_tsv' END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) - 'search_tsv' END,
    NULLIF(current_setting('app.change_set_id', true), '')::uuid,
    NULLIF(current_setting('app.request_id', true), '')
  );
  RETURN NULL;
END $$;

CREATE TRIGGER items_audit_trg           AFTER INSERT OR UPDATE OR DELETE ON items           FOR EACH ROW EXECUTE FUNCTION audit_row();
CREATE TRIGGER locations_audit_trg       AFTER INSERT OR UPDATE OR DELETE ON locations       FOR EACH ROW EXECUTE FUNCTION audit_row();
CREATE TRIGGER categories_audit_trg      AFTER INSERT OR UPDATE OR DELETE ON categories      FOR EACH ROW EXECUTE FUNCTION audit_row();
CREATE TRIGGER item_placements_audit_trg AFTER INSERT OR UPDATE OR DELETE ON item_placements FOR EACH ROW EXECUTE FUNCTION audit_row();

-- ---------------------------------------------------------------------
-- 9) Zápůjčky, připomínky, inventura, pohledy, štítky, import/export
-- ---------------------------------------------------------------------

CREATE TABLE loans (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id          uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  quantity         numeric(12,3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  borrower_name    text NOT NULL,
  borrower_contact text,
  lent_at          date NOT NULL DEFAULT current_date,
  due_at           date,
  returned_at      date,
  note             text,
  created_by       uuid REFERENCES users(id)
);
CREATE INDEX loans_open_idx ON loans (item_id) WHERE returned_at IS NULL;

CREATE TABLE reminders (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id         uuid REFERENCES items(id) ON DELETE CASCADE,
  location_id     uuid REFERENCES locations(id) ON DELETE CASCADE,
  kind            text NOT NULL CHECK (kind IN ('warranty','expiry','maintenance','loan_due','low_stock','custom')),
  due_at          timestamptz NOT NULL,
  repeat_interval interval,
  message         text,
  notified_at     timestamptz,
  done_at         timestamptz,
  created_by      uuid REFERENCES users(id)
);
CREATE INDEX reminders_due_idx ON reminders (due_at) WHERE done_at IS NULL;

CREATE TABLE notifications (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       text NOT NULL,
  title      text NOT NULL,
  body       text,
  link       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at    timestamptz
);
CREATE INDEX notifications_user_idx ON notifications (user_id, read_at, created_at DESC);

-- Inventura (kontrola, že věci opravdu jsou tam, kde mají být)
CREATE TABLE inventory_sessions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  location_id uuid REFERENCES locations(id) ON DELETE SET NULL,   -- rozsah (podstrom); NULL = celý dům
  name        text NOT NULL,
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed','cancelled')),
  started_by  uuid REFERENCES users(id),
  started_at  timestamptz NOT NULL DEFAULT now(),
  closed_at   timestamptz
);
CREATE TABLE inventory_lines (
  session_id   uuid NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
  item_id      uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  location_id  uuid REFERENCES locations(id) ON DELETE SET NULL,
  expected_qty numeric(12,3),
  counted_qty  numeric(12,3),
  result       text NOT NULL DEFAULT 'unchecked'
               CHECK (result IN ('unchecked','ok','missing','extra','moved')),
  counted_at   timestamptz,
  PRIMARY KEY (session_id, item_id, location_id)
);

CREATE TABLE saved_views (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entity     text NOT NULL CHECK (entity IN ('items','locations','movements')),
  name       text NOT NULL,
  filters    jsonb NOT NULL DEFAULT '{}',
  columns    jsonb NOT NULL DEFAULT '[]',
  sort       jsonb NOT NULL DEFAULT '[]',
  is_shared  boolean NOT NULL DEFAULT false,
  UNIQUE (user_id, entity, name)
);

CREATE TABLE label_templates (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL UNIQUE,
  target     text NOT NULL CHECK (target IN ('item','location')),
  width_mm   numeric(6,1) NOT NULL,
  height_mm  numeric(6,1) NOT NULL,
  layout     jsonb NOT NULL,          -- QR/čárový kód, název, cesta, pole…
  is_default boolean NOT NULL DEFAULT false
);

CREATE TABLE data_jobs (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  direction  text NOT NULL CHECK (direction IN ('import','export')),
  format     text NOT NULL CHECK (format IN ('csv','xlsx','json')),
  params     jsonb NOT NULL DEFAULT '{}',        -- sloupce, filtr, mapování, dry-run
  status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  file_path  text,
  report     jsonb,                              -- počty, chyby po řádcích
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);

-- ---------------------------------------------------------------------
-- 10) Integrace: webhooky a transakční outbox (MQTT, webhooky, SSE)
-- ---------------------------------------------------------------------

CREATE TABLE webhooks (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  url         text NOT NULL,
  secret      text,                       -- šifrováno na úrovni aplikace
  events      text[] NOT NULL DEFAULT '{*}',
  is_active   boolean NOT NULL DEFAULT true,
  last_status int,
  last_error  text
);

-- Změny se zapíší do outboxu ve stejné transakci; worker je publikuje
-- do MQTT / webhooků / SSE. Zaručuje, že se nic neztratí ani nepublikuje dřív než commit.
CREATE TABLE event_outbox (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type   text NOT NULL,             -- item.created, item.moved, stock.low, location.updated, ...
  entity_type  text,
  entity_id    uuid,
  payload      jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempts     int NOT NULL DEFAULT 0
);
CREATE INDEX event_outbox_pending_idx ON event_outbox (id) WHERE published_at IS NULL;

-- ---------------------------------------------------------------------
-- 11) Pohledy
-- ---------------------------------------------------------------------

-- čitelná cesta umístění: "Dům › Garáž › Regál A › Police 3 › Krabice 'Elektro'"
CREATE VIEW v_location_paths AS
SELECT l.id,
       l.label_code,
       l.kind,
       l.depth,
       l.path,
       (SELECT string_agg(a.name, ' › ' ORDER BY a.depth)
          FROM locations a WHERE a.path @> l.path) AS full_name
  FROM locations l;

-- "Kde co je": jedna řádka na každé umístění věci
CREATE VIEW v_item_whereabouts AS
SELECT i.id            AS item_id,
       i.label_code    AS item_label,
       i.name,
       i.status,
       c.name          AS category,
       p.quantity,
       i.unit,
       lp.id           AS location_id,
       lp.label_code   AS location_label,
       lp.full_name    AS location_path
  FROM items i
  LEFT JOIN categories c        ON c.id = i.category_id
  LEFT JOIN item_placements p   ON p.item_id = i.id
  LEFT JOIN v_location_paths lp ON lp.id = p.location_id
 WHERE i.deleted_at IS NULL;

-- Celkové množství a "dochází zásoba"
CREATE VIEW v_item_stock AS
SELECT i.id AS item_id,
       i.name,
       COALESCE(sum(p.quantity), 0) AS total_qty,
       i.min_quantity,
       (i.min_quantity IS NOT NULL AND COALESCE(sum(p.quantity), 0) <= i.min_quantity) AS is_low
  FROM items i
  LEFT JOIN item_placements p ON p.item_id = i.id
 WHERE i.deleted_at IS NULL
 GROUP BY i.id;

-- Počet věcí v každém umístění včetně podstromu (pro dashboard zaplnění)
CREATE VIEW v_location_fill AS
SELECT l.id AS location_id,
       l.name,
       l.path,
       count(DISTINCT p.item_id) AS item_count
  FROM locations l
  LEFT JOIN locations d       ON d.path <@ l.path
  LEFT JOIN item_placements p ON p.location_id = d.id
 GROUP BY l.id;
