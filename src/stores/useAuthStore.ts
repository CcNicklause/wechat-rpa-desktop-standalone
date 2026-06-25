import { create } from 'zustand';

interface User {
  username: string;
  role: 'agent' | 'admin';
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('mock_token'),
  login: async (username, password) => {
    if (username.trim() && password.length >= 6) {
      localStorage.setItem('mock_token', 'mock-jwt-token-xyz123');
      set({ user: { username, role: 'agent' }, isAuthenticated: true });
      return true;
    }
    return false;
  },
  logout: () => {
    localStorage.removeItem('mock_token');
    set({ user: null, isAuthenticated: false });
  },
}));
