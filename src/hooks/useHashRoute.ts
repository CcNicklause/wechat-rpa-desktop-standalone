import { useEffect, useState, useCallback } from 'react';

// 轻量 hash 路由 hook：用 `#/path` 表达当前页面，刷新/重启自动保留，
// Tauri webview 的 file:// 协议下也工作。比起 react-router-dom 不引依赖。
//
//   const { route, navigate } = useHashRoute('/dashboard');
//   navigate('/test');                     // 切到 #/test
//   <a href="#/risk">…</a>                 // 浏览器原生支持
//
// `defaultRoute` 仅当 location.hash 为空或不合法时使用。

function readHash(): string {
  if (typeof window === 'undefined') return '';
  const raw = window.location.hash.replace(/^#/, '');
  return raw.startsWith('/') ? raw : raw ? `/${raw}` : '';
}

export function useHashRoute(defaultRoute: string = '/'): {
  route: string;
  navigate: (next: string) => void;
} {
  const [route, setRoute] = useState<string>(() => readHash() || defaultRoute);

  useEffect(() => {
    const onChange = () => setRoute(readHash() || defaultRoute);
    window.addEventListener('hashchange', onChange);
    // 首次挂载时若 hash 缺失，写一次默认值，保证 URL 一致
    if (!readHash()) {
      window.location.hash = defaultRoute;
    }
    return () => window.removeEventListener('hashchange', onChange);
  }, [defaultRoute]);

  const navigate = useCallback((next: string) => {
    const target = next.startsWith('/') ? next : `/${next}`;
    if (target !== readHash()) {
      window.location.hash = target;
    }
  }, []);

  return { route, navigate };
}
