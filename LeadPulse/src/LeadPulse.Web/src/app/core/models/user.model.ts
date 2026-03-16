export interface UserResponse {
  id: number;
  firstName: string;
  lastName: string;
  email: string;
  phone?: string;
  role: string;
  permissions?: Record<string, boolean>;
  mfaEnabled: boolean;
  status: string;
  lastLoginAt?: string;
  createdAt: string;
}

export interface CreateUserRequest {
  firstName: string;
  lastName: string;
  email: string;
  password: string;
  phone?: string;
  role: string;
  permissions?: Record<string, boolean>;
}

export interface UpdateUserRequest {
  firstName?: string;
  lastName?: string;
  phone?: string;
  role?: string;
  permissions?: Record<string, boolean>;
}

export interface InviteUserRequest {
  email: string;
  role: string;
}

export interface PermissionsMatrix {
  permissions: string[];
  matrix: Record<string, string[]>;
}
