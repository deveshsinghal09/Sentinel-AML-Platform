export type AnalystRole =
  | 'analyst'
  | 'senior_analyst'
  | 'supervisor'
  | 'compliance_admin'
  | 'auditor'

export interface AuthUser {
  user_id: string
  email: string
  display_name: string
  roles: AnalystRole[]
}

export interface AuthSession {
  user: AuthUser
  expires_at: string
}

export interface LoginCredentials {
  email: string
  password: string
}

export type AuthStatus =
  | 'checking'
  | 'authenticating'
  | 'authenticated'
  | 'unauthenticated'
