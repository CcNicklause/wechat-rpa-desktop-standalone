import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { requestLocalApi } from '../lib/api';

const MOCK_REASONS = [
  '你好，看您朋友圈有项目合作，加一下',
  '合作咨询，请问是微信代发负责人吗？',
  '社群交流加个好友哈',
  '你好，朋友推荐加你的'
];

export function useCloudTasks(enabled: boolean) {
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }

    const triggerPull = async () => {
      try {
        const mockPhone = `138${Math.floor(10000000 + Math.random() * 90000000)}`;
        const mockLead = {
          name: `云端线索_${Math.floor(Math.random() * 1000)}`,
          phone: mockPhone,
          add_reason: MOCK_REASONS[Math.floor(Math.random() * MOCK_REASONS.length)],
          source: '云端分配'
        };

        // Post lead into local SQLite database
        const createdLead = await requestLocalApi('/api/v1/leads', {
          method: 'POST',
          body: JSON.stringify(mockLead)
        });

        // Trigger local precheck with mock execution dry run mode
        await requestLocalApi('/api/v1/rpa/precheck', {
          method: 'POST',
          body: JSON.stringify({ lead_id: createdLead.id })
        });

        // Force invalidate React Query cache to show lead instantly
        queryClient.invalidateQueries({ queryKey: ['leads'] });
      } catch (err) {
        console.error('Failed to sync cloud tasks locally', err);
      }
    };

    triggerPull(); // 启动时立即拉取一次
    timerRef.current = setInterval(triggerPull, 30000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, queryClient]);
}
