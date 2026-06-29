import { useEffect, useState, useCallback } from 'react';

// 轻量 hash 路由 hook：用 `#/path` 表达当前页面，刷新/重启自动保留，
// Tauri webview 的 file:// 协议下也工作。比起 react-router-dom 不引依赖。
//
//   const { route, query, navigate, setQuery } = useHashRoute('/dashboard');
//   navigate('/test');                     // 切到 #/test
//   setQuery({ lead: '123', tab: 'steps' }) // 设置 #/path?lead=123&tab=steps
//
// `defaultRoute` 仅当 location.hash 为空或不合法时使用。

interface HashParts {
  path: string;
  query: Record<string, string>;
}

function parseHash(): HashParts {
  if (typeof window === 'undefined') return { path: '', query: {} };
  const raw = window.location.hash.replace(/^#/, '');
  const [pathPart, queryPart] = raw.split('?');
  const path = pathPart.startsWith('/') ? pathPart : pathPart ? `/${pathPart}` : '';
  const query: Record<string, string> = {};
  if (queryPart) {
    queryPart.split('&').forEach((pair) => {
      const [key, value] = pair.split('=');
      if (key) {
        query[decodeURIComponent(key)] = decodeURIComponent(value || '');
      }
    });
  }
  return { path, query };
}

function buildHash(path: string, query: Record<string, string | null>): string {
  let result = path.startsWith('/') ? path : `/${path}`;
  const queryParts: string[] = [];
  Object.entries(query).forEach(([key, value]) => {
    if (value !== null && value !== undefined) {
      queryParts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
  });
  if (queryParts.length > 0) {
    result += `?${queryParts.join('&')}`;
  }
  return result;
}

export function useHashRoute(defaultRoute: string = '/'): {
  route: string;
  query: Record<string, string>;
  navigate: (next: string, query?: Record<string, string | null>) => void;
  setQuery: (params: Record<string, string | null>) => void;
} {
  const [route, setRoute] = useState<string>(() => parseHash().path || defaultRoute);
  const [query, setQueryState] = useState<Record<string, string>>(() => parseHash().query);

  useEffect(() => {
    const onChange = () => {
      const { path, query } = parseHash();
      setRoute(path || defaultRoute);
      setQueryState(query);
    };
    window.addEventListener('hashchange', onChange);
    // 首次挂载时若 hash 缺失，写一次默认值，保证 URL 一致
    const { path } = parseHash();
    if (!path) {
      window.location.hash = defaultRoute;
    }
    return () => window.removeEventListener('hashchange', onChange);
  }, [defaultRoute]);

  const navigate = useCallback((next: string, newQuery?: Record<string, string | null>) => {
    const target = buildHash(next, newQuery || query);
    window.location.hash = target;
  }, [query]);

  const setQuery = useCallback((params: Record<string, string | null>) => {
    const { path } = parseHash();
    const newQuery = { ...query };
    Object.entries(params).forEach(([key, value]) => {
      if (value === null) {
        delete newQuery[key];
      } else {
        newQuery[key] = value;
      }
    });
    window.location.hash = buildHash(path || defaultRoute, newQuery);
  }, [query, defaultRoute]);

  return { route, query, navigate, setQuery };
}
