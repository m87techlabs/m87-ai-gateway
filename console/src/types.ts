export interface Summary {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_hits: number;
  errors: number;
  usage_unknown: number;
  average_latency_ms: number;
  hours?: number;
}

export interface UsageRow {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens?: number;
  errors: number;
  cache_hits?: number;
  app_id?: string | null;
  model?: string | null;
  endpoint?: string | null;
}

export interface Bucket {
  bucket: string;
  requests: number;
  total_tokens: number;
  errors?: number;
}

export interface Usage {
  series: Bucket[];
  by_app: UsageRow[];
  by_model: UsageRow[];
  by_endpoint?: UsageRow[];
}

export interface LogEvent {
  request_id: string;
  created_at: string;
  project_id: string | null;
  app_id: string | null;
  key_id?: string | null;
  endpoint?: string | null;
  provider?: string | null;
  model: string | null;
  routed_model: string | null;
  status_code: number;
  http_status_code?: number | null;
  upstream_status?: number | null;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  error_type: string | null;
  cache_status: string | null;
  provider_attempts?: number | null;
  provider_retries?: number | null;
  streaming?: number | boolean;
  request_outcome: string | null;
  response_content_partial?: number | boolean;
  queue_wait_ms?: number | null;
  queue_outcome?: string | null;
  client_user_hash?: string | null;
  capture_enabled?: number | boolean | null;
  guardrail_action?: string | null;
  guardrail_reason?: string | null;
  request_content?: unknown;
  response_content?: unknown;
  request_content_status?: string;
  response_content_status?: string;
  request_content_truncated?: number | boolean;
  response_content_truncated?: number | boolean;
}

export interface LogsPage {
  items: LogEvent[];
  next_cursor: string | null;
}

export interface LoggingHealth {
  ok: boolean;
  capture_enabled: boolean;
  scope: string;
  items: {
    destination: string;
    last_write_ok: boolean | null;
    successful_writes: number;
    failed_writes: number;
  }[];
  traffic_retention_days: number;
  content_retention_days: number;
  usage_retention_days: number;
  export?: ExportHealth;
}

export interface ExportHealth {
  enabled: boolean;
  adapter?: string;
  delivery_state?: string;
  pending?: number;
  delivered?: number;
  failed_attempts?: number;
  dropped?: number;
  expired?: number;
  storage_ok?: boolean;
  scope?: string;
}

export interface Application {
  app_id: string;
  project_id: string;
  allowed_models: string[];
  key_prefix: string;
  active_key_count?: number;
  rate_limit_per_minute: number | null;
  max_concurrent_requests: number | null;
  created_at?: string;
}

export interface AppKey {
  key_id: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at?: string | null;
  active: boolean;
}

export interface Project {
  project_id: string;
  name: string;
  app_count: number;
  created_at?: string;
}

export interface ProviderConfig {
  enabled: boolean;
  base_url: string | null;
  timeout_seconds: number;
  api_key_env?: string | null;
}

export interface Connection {
  provider: string;
  label: string;
  requires_key: boolean;
  model_discovery: boolean;
  configured: boolean;
  has_stored_key: boolean;
  config: ProviderConfig;
  capability_matrix: Record<string, unknown>;
}

export interface Setup {
  default_model: string;
  capture_content: boolean;
  connections: Connection[];
}

export interface Check {
  name: string;
  ok: boolean;
  message: string;
}

export interface Diagnostics {
  ready: boolean;
  default_model: string;
  checks: Check[];
  active_requests: number;
  queued_requests?: number;
  scope?: string;
}

export interface FeatureField {
  name: string;
  label: string;
  kind: "number" | "terms" | "routes";
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  unit: string | null;
  help: string | null;
}

export interface Capability {
  id: string;
  name: string;
  summary: string;
}

export interface Feature {
  id: string;
  name: string;
  group: string;
  summary: string;
  note: string | null;
  status: "on" | "off" | "planned";
  enabled: boolean;
  toggleable: boolean;
  badge?: string;
  link?: string;
  values: Record<string, unknown>;
  fields: FeatureField[];
}

export interface Revision {
  revision_id: number;
  created_at: string;
  action: string;
  restored_from: number | null;
}

export interface RevisionDetail {
  scope: string;
  settings: unknown;
  changed_provider_bindings: string[];
  changed_export_binding: boolean;
}

export interface AuditEvent {
  created_at: string;
  actor: string;
  action: string;
  project_id: string | null;
  app_id: string | null;
  key_id: string | null;
  provider: string | null;
  alias: string | null;
  revision_id: number | null;
  restored_from: number | null;
}

export interface StorageReport {
  ok: boolean;
  backend: string;
  verified: boolean;
  database_bytes: number | null;
  wal_bytes: number | null;
  free_disk_bytes: number | null;
  schema_version: number | null;
  checks: Check[];
  warnings?: string[];
}

export interface ExportConfig {
  enabled: boolean;
  adapter: string;
  endpoint: string | null;
  use_stored_key: boolean;
  api_key_env: string | null;
  max_pending: number;
  retention_hours: number;
  timeout_seconds: number;
  poll_seconds: number;
  retry_seconds: number;
  max_retry_seconds: number;
}

export interface ExportSettings {
  adapters: string[];
  config: ExportConfig;
  has_stored_key: boolean;
  has_any_stored_key: boolean;
  health: ExportHealth;
  scope: string;
}

export interface Destination {
  name: string;
  type: string;
  target: string | null;
  enabled: boolean;
}
