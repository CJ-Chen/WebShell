export interface User {
  id: number
  username: string
  email: string
  role: 'user' | 'admin'
  status: string
  must_change_password: boolean
  created_at: string
  last_login_at: string | null
}

export interface AuthPayload {
  user: User
  csrf_token: string
}

export interface Target {
  id: string
  name: string
  host: string
  port: number
  username: string
  auth_method: 'password' | 'private_key'
  default_path: string | null
  host_key_algorithm: string | null
  host_key_fingerprint: string | null
  status: string
  last_error: string | null
  last_connected_at: string | null
  has_saved_credential: boolean
}

export interface TerminalSession {
  id: string
  target_id: string
  name: string
  persistence_mode: 'tmux' | 'shell'
  status: string
  created_at: string
  last_connected_at: string | null
}

export interface FileItem {
  name: string
  path: string
  type: 'file' | 'directory' | 'symlink' | 'other'
  size: number
  modified_at: string | null
  permissions: number | null
}

export interface FileList {
  path: string
  home_path: string
  items: FileItem[]
}

export interface DestinationRule {
  id: number
  kind: 'cidr' | 'domain'
  value: string
  port_min: number
  port_max: number
  enabled: boolean
  description: string | null
  created_at: string
}

export interface AuditLog {
  id: number
  actor_id: number | null
  action: string
  resource_type: string
  resource_id: string | null
  outcome: string
  detail: string | null
  ip_address: string | null
  created_at: string
}
