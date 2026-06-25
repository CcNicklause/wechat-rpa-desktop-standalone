import { create } from 'zustand';

type Theme = 'light' | 'dark';

interface ThemeStore {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const getInitialTheme = (): Theme => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('wechat-rpa-theme') as Theme;
    if (saved === 'light' || saved === 'dark') {
      return saved;
    }
    // 默认使用系统或者是标准的 dark 模式
    return 'dark';
  }
  return 'dark';
};

const applyTheme = (theme: Theme) => {
  if (typeof window === 'undefined') return;
  const root = window.document.documentElement;
  if (theme === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
  localStorage.setItem('wechat-rpa-theme', theme);
};

export const useThemeStore = create<ThemeStore>((set) => {
  // 首次运行应用全局样式
  const initialTheme = getInitialTheme();
  applyTheme(initialTheme);

  return {
    theme: initialTheme,
    toggleTheme: () => set((state) => {
      const nextTheme = state.theme === 'light' ? 'dark' : 'light';
      applyTheme(nextTheme);
      return { theme: nextTheme };
    }),
    setTheme: (theme) => set(() => {
      applyTheme(theme);
      return { theme };
    }),
  };
});

export function useTheme() {
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);
  return { theme, toggleTheme };
}
