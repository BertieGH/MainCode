export interface LoginRequest {
  email: string;
  password: string;
}

export interface TenantLoginRequest extends LoginRequest {
  tenantId: number;
}

export interface AuthResult {
  success: boolean;
  token?: string;
  error?: string;
  userId?: number;
  tenantId?: number;
  role?: string;
  forcePasswordChange?: boolean;
}

export interface DecodedToken {
  nameid: string;
  email: string;
  role: string;
  tenantId?: string;
  exp: number;
}
