import { create } from 'zustand';

export interface ToastMessage {
  id: string;
  title?: string;
  description: string;
  variant?: 'default' | 'destructive' | 'success';
}

interface ToastStore {
  toasts: ToastMessage[];
  toast: (options: Omit<ToastMessage, 'id'>) => void;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  toast: (options) => {
    const id = Math.random().toString(36).substring(2, 9);
    const newToast = { ...options, id };
    set((state) => ({ toasts: [...state.toasts, newToast] }));
    setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, 4000); // 4秒自动消失
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export function useToast() {
  const addToast = useToastStore((state) => state.toast);
  return {
    toast: addToast,
  };
}
