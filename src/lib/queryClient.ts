import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false, // 桌面端失去/得到焦点时不自动重新拉取，避免界面突兀闪烁
      retry: 1,                    // 失败重试次数
      staleTime: 1000 * 5,         // 5秒内的数据视为新鲜数据
    },
  },
});
