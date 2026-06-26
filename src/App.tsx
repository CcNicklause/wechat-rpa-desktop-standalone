import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Sun, Moon } from "lucide-react";

import { useAuthStore } from "./stores/useAuthStore";
import { AppShell } from "./components/layout/AppShell";
import { StatusBar } from "./components/layout/StatusBar";
import { Card } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { ToastContainer } from "./components/ui/toast";
import { useToast } from "./hooks/useToast";
import { useTheme } from "./hooks/useTheme";

const loginSchema = z.object({
  username: z.string().min(1, "用户名不能为空"),
  password: z.string().min(6, "密码最少包含 6 位字符"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export default function App() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const login = useAuthStore((state) => state.login);
  const { toast } = useToast();
  const { theme, toggleTheme } = useTheme();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      username: "",
      password: "",
    },
  });

  const onSubmit = async (data: LoginFormValues) => {
    const success = await login(data.username, data.password);
    if (!success) {
      toast({
        title: "登录失败",
        description: "账号或密码验证失败，请重新检查",
        variant: "destructive",
      });
    } else {
      toast({
        title: "登录成功",
        description: `欢迎回来，${data.username}`,
        variant: "success",
      });
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="relative h-screen w-screen bg-background text-foreground flex items-center justify-center overflow-hidden transition-colors duration-300">
        {/* Theme Toggle Button */}
        <div className="absolute top-4 right-4 z-20">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="rounded-full h-9 w-9"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-amber-400" />
            ) : (
              <Moon className="h-4 w-4 text-slate-600" />
            )}
          </Button>
        </div>

        <Card className="w-full max-w-sm p-6 border border-border bg-card text-card-foreground rounded-xl shadow-lg space-y-6">
          <div className="text-center space-y-2">
            <div className="inline-flex p-3.5 bg-secondary text-secondary-foreground rounded-full">
              <span className="text-2xl">🤖</span>
            </div>
            <h2 className="text-lg font-bold text-foreground">
              WeChat RPA Desktop
            </h2>
            <p className="text-xs text-muted-foreground">
              登入您的自动加微工作台
            </p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-muted-foreground">
                管理账号
              </label>
              <input
                type="text"
                {...register("username")}
                className="w-full px-3 py-2 bg-transparent border border-input text-foreground rounded-lg text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                placeholder="请输入用户名"
              />
              {errors.username && (
                <p className="text-[11px] text-rose-500 font-semibold">
                  {errors.username.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-bold text-muted-foreground">
                访问密码
              </label>
              <input
                type="password"
                {...register("password")}
                className="w-full px-3 py-2 bg-transparent border border-input text-foreground rounded-lg text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                placeholder="••••••"
              />
              {errors.password && (
                <p className="text-[11px] text-rose-500 font-semibold">
                  {errors.password.message}
                </p>
              )}
            </div>

            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={isSubmitting}
            >
              登录
            </Button>
          </form>
        </Card>
        <ToastContainer />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-background text-foreground transition-colors duration-300">
      <AppShell />
      <StatusBar />
      <ToastContainer />
    </div>
  );
}
