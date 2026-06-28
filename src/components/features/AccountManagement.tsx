import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { invoke } from '@tauri-apps/api/core';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FieldError } from '@/components/common/FieldError';
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

  const onSubmit = async (_data: PasswordFormValues) => {
    toast({
      title: '请前往 Web Portal',
      description: '桌面端当前只负责登录，不直接修改 Portal 账号密码',
      variant: 'default',
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
              <span className="font-semibold">{user?.name || user?.phone || 'Guest'}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-muted-foreground">Portal 手机号</span>
              <span className="font-semibold">{user?.phone || '-'}</span>
            </div>
            <div className="flex justify-between border-b pb-2">
              <span className="text-muted-foreground">租户 ID</span>
              <span className="font-semibold">{user?.tenant_id ?? '-'}</span>
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
                <Label>旧密码</Label>
                <Input
                  type="password"
                  {...register('oldPassword')}
                />
                <FieldError>{errors.oldPassword?.message}</FieldError>
              </div>
              <div className="space-y-1.5">
                <Label>新密码</Label>
                <Input
                  type="password"
                  {...register('newPassword')}
                />
                <FieldError>{errors.newPassword?.message}</FieldError>
              </div>
              <div className="space-y-1.5">
                <Label>确认新密码</Label>
                <Input
                  type="password"
                  {...register('confirmPassword')}
                />
                <FieldError>{errors.confirmPassword?.message}</FieldError>
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
