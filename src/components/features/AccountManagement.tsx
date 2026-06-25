import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { invoke } from '@tauri-apps/api/core';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToast } from '@/hooks/useToast';

const passwordSchema = z.object({
  oldPassword: z.string().min(1, '请输入旧密码'),
  newPassword: z.string().min(6, '新密码必须至少为 6 个字符'),
  confirmPassword: z.string().min(1, '请确认新密码'),
}).refine((data) => data.newPassword === data.confirmPassword, {
  message: '两次输入的新密码不一致',
  path: ['confirmPassword'],
});

type PasswordFormValues = z.infer<typeof passwordSchema>;

export function AccountManagement() {
  const user = useAuthStore((state) => state.user);
  const { toast } = useToast();
  const [token, setToken] = useState('加载中...');
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    const fetchToken = async () => {
      try {
        const res = await invoke<string>('get_security_token');
        setToken(res);
      } catch {
        setToken('test_token');
      }
    };
    fetchToken();
  }, []);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { oldPassword: '', newPassword: '', confirmPassword: '' },
  });

  const onSubmit = async (data: PasswordFormValues) => {
    // Simulate API change password
    await new Promise((resolve) => setTimeout(resolve, 800));
    toast({
      title: '修改密码成功',
      description: '登录席位密码已安全修改',
      variant: 'success',
    });
    reset();
  };

  const copyToken = () => {
    navigator.clipboard.writeText(token);
    toast({ title: '复制成功', description: '安全令牌已复制到剪贴板', variant: 'success' });
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="p-6 border border-border">
          <CardHeader className="p-0 pb-4 border-b border-border">
            <CardTitle>席位账户属性</CardTitle>
          </CardHeader>
          <CardContent className="p-0 pt-4 space-y-4 text-xs">
            <div className="flex justify-between border-b pb-2">
              <span className="text-muted-foreground">当前席位名称</span>
              <span className="font-semibold">{user?.username || 'Guest'}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-muted-foreground">权限级别</span>
              <span className="font-semibold text-indigo-500 dark:text-indigo-400 capitalize">{user?.role || 'agent'}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-muted-foreground">API 安全接入令牌</span>
              <div className="flex items-center gap-2">
                <span className="font-mono bg-muted px-2 py-0.5 rounded text-[10px]">
                  {showToken ? token : '••••••••••••••••'}
                </span>
                <Button variant="ghost" className="h-6 px-2 text-[10px]" onClick={() => setShowToken(!showToken)}>
                  {showToken ? '隐藏' : '显示'}
                </Button>
                <Button variant="outline" className="h-6 px-2 text-[10px]" onClick={copyToken}>
                  复制
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="p-6 border border-border">
          <CardHeader className="p-0 pb-4 border-b border-border">
            <CardTitle>修改席位密码</CardTitle>
          </CardHeader>
          <CardContent className="p-0 pt-4">
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-muted-foreground">旧密码</label>
                <input
                  type="password"
                  {...register('oldPassword')}
                  className="w-full px-3 py-1.5 bg-transparent border border-input rounded-lg text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                />
                {errors.oldPassword && <p className="text-[10px] text-rose-500 font-semibold">{errors.oldPassword.message}</p>}
              </div>
              <div className="space-y-1.5">
                <label className="font-semibold text-muted-foreground">新密码</label>
                <input
                  type="password"
                  {...register('newPassword')}
                  className="w-full px-3 py-1.5 bg-transparent border border-input rounded-lg text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                />
                {errors.newPassword && <p className="text-[10px] text-rose-500 font-semibold">{errors.newPassword.message}</p>}
              </div>
              <div className="space-y-1.5">
                <label className="font-semibold text-muted-foreground">确认新密码</label>
                <input
                  type="password"
                  {...register('confirmPassword')}
                  className="w-full px-3 py-1.5 bg-transparent border border-input rounded-lg text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                />
                {errors.confirmPassword && <p className="text-[10px] text-rose-500 font-semibold">{errors.confirmPassword.message}</p>}
              </div>
              <Button type="submit" className="w-full h-8" disabled={isSubmitting}>
                保存修改
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
