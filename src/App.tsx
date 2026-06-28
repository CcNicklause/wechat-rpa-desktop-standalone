import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound, MessageSquareText, Moon, ShieldCheck, Sun } from "lucide-react";

import { useAuthStore } from "./stores/useAuthStore";
import { AppShell } from "./components/layout/AppShell";
import { StatusBar } from "./components/layout/StatusBar";
import { Card } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { FieldError } from "./components/common/FieldError";
import { ToastContainer } from "./components/ui/toast";
import { useToast } from "./hooks/useToast";
import { useTheme } from "./hooks/useTheme";

const phonePattern = /^1[3-9]\d{9}$/;

const loginSchema = z.object({
  phone: z.string().regex(phonePattern, "请输入正确的手机号"),
  password: z.string().optional(),
  code: z.string().optional(),
});

type LoginFormValues = z.infer<typeof loginSchema>;
type LoginMode = "password" | "sms";

export default function App() {
  const status = useAuthStore((state) => state.status);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const initialize = useAuthStore((state) => state.initialize);
  const loginPassword = useAuthStore((state) => state.loginPassword);
  const loginSms = useAuthStore((state) => state.loginSms);
  const sendLoginCode = useAuthStore((state) => state.sendLoginCode);
  const { toast } = useToast();
  const { theme, toggleTheme } = useTheme();
  const [mode, setMode] = useState<LoginMode>("password");
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = window.setTimeout(() => setCountdown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  const {
    register,
    handleSubmit,
    getValues,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      phone: "",
      password: "",
      code: "",
    },
  });

  const onSubmit = async (data: LoginFormValues) => {
    try {
      if (mode === "password") {
        if (!data.password || data.password.length < 6) {
          setError("password", { message: "密码最少包含 6 位字符" });
          return;
        }
        await loginPassword(data.phone, data.password);
      } else {
        if (!data.code || data.code.length < 4) {
          setError("code", { message: "验证码最少包含 4 位字符" });
          return;
        }
        await loginSms(data.phone, data.code);
      }
      toast({
        title: "登录成功",
        description: "已连接 Portal 账号体系",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "登录失败",
        description: error instanceof Error ? error.message : "请检查账号信息后重试",
        variant: "destructive",
      });
    }
  };

  const handleSendCode = async () => {
    const phone = getValues("phone");
    clearErrors("phone");
    if (!phonePattern.test(phone)) {
      setError("phone", { message: "请输入正确的手机号" });
      return;
    }
    try {
      await sendLoginCode(phone);
      setCountdown(60);
      toast({
        title: "验证码已发送",
        description: "请查看手机短信",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "发送失败",
        description: error instanceof Error ? error.message : "请稍后重试",
        variant: "destructive",
      });
    }
  };

  if (status === "checking") {
    return (
      <div className="h-screen w-screen bg-background text-foreground flex items-center justify-center">
        <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-primary" />
          正在校验登录状态...
        </div>
        <ToastContainer />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="relative h-screen w-screen bg-background text-foreground flex items-center justify-center overflow-hidden transition-colors duration-300">
        <div className="absolute top-4 right-4 z-20">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="rounded-full h-9 w-9"
            title="切换主题"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-amber-400" />
            ) : (
              <Moon className="h-4 w-4 text-slate-600" />
            )}
          </Button>
        </div>

        <Card className="w-full max-w-sm p-6 border border-border bg-card text-card-foreground rounded-lg shadow-lg space-y-5">
          <div className="text-center space-y-2">
            <div className="inline-flex p-3 bg-secondary text-secondary-foreground rounded-lg">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <h2 className="text-lg font-bold text-foreground">
              WeChat RPA Desktop
            </h2>
            <p className="text-xs text-muted-foreground">
              使用 Portal 账号登录工作台
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-1">
            <Button
              type="button"
              variant={mode === "password" ? "primary" : "ghost"}
              size="sm"
              onClick={() => setMode("password")}
              className="h-8"
            >
              <KeyRound className="h-3.5 w-3.5" />
              密码
            </Button>
            <Button
              type="button"
              variant={mode === "sms" ? "primary" : "ghost"}
              size="sm"
              onClick={() => setMode("sms")}
              className="h-8"
            >
              <MessageSquareText className="h-3.5 w-3.5" />
              短信
            </Button>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label className="font-bold">手机号</Label>
              <Input
                type="tel"
                inputMode="numeric"
                maxLength={11}
                {...register("phone")}
                className="h-9 text-sm"
                placeholder="请输入手机号"
              />
              <FieldError className="text-[11px]">{errors.phone?.message}</FieldError>
            </div>

            {mode === "password" ? (
              <div className="space-y-1.5">
                <Label className="font-bold">密码</Label>
                <Input
                  type="password"
                  {...register("password")}
                  className="h-9 text-sm"
                  placeholder="请输入密码"
                />
                <FieldError className="text-[11px]">{errors.password?.message}</FieldError>
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label className="font-bold">短信验证码</Label>
                <div className="grid grid-cols-[1fr_auto] gap-2">
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    {...register("code")}
                    className="h-9 text-sm"
                    placeholder="请输入验证码"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 px-3"
                    onClick={handleSendCode}
                    disabled={countdown > 0}
                  >
                    {countdown > 0 ? `${countdown}s` : "获取验证码"}
                  </Button>
                </div>
                <FieldError className="text-[11px]">{errors.code?.message}</FieldError>
              </div>
            )}

            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={isSubmitting}
            >
              登录
            </Button>
          </form>

          <p className="text-center text-[11px] leading-5 text-muted-foreground">
            还没有账号？请前往 Web Portal 完成注册。
          </p>
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
