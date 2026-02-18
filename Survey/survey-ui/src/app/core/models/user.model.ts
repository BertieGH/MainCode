export enum UserRole {
  Admin = 'Admin',
  Manager = 'Manager',
  User = 'User'
}

export interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  isActive: boolean;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CreateUser {
  username: string;
  email: string;
  password: string;
  role: string;
}

export interface UpdateUser {
  username: string;
  email: string;
  role?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

export interface AuthResponse {
  token: string;
  username: string;
  email: string;
  role: string;
  expiresAt: string;
}
