import * as React from "react"
import { useToastStore, type ToastMessage } from "../../hooks/useToast"
import { cn } from "../../lib/utils"

export function ToastContainer() {
  const toasts = useToastStore((state) => state.toasts)
  const dismiss = useToastStore((state) => state.dismiss)

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80 max-w-[90vw]">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
      ))}
    </div>
  )
}

interface ToastItemProps {
  toast: ToastMessage
  onDismiss: () => void
}

function ToastItem({ toast, onDismiss }: ToastItemProps) {
  return (
    <div
      onClick={onDismiss}
      className={cn(
        "flex flex-col gap-1 p-4 rounded-xl border backdrop-blur-xl shadow-lg cursor-pointer transition-all duration-300 transform translate-y-0 scale-100 hover:scale-[1.02] active:scale-[0.98] animate-in fade-in slide-in-from-bottom-5",
        toast.variant === "destructive"
          ? "border-rose-500/30 bg-rose-950/80 text-rose-200"
          : toast.variant === "success"
          ? "border-emerald-500/30 bg-emerald-950/80 text-emerald-200"
          : "border-white/10 bg-slate-900/80 text-slate-200"
      )}
    >
      {toast.title && <span className="text-xs font-bold tracking-wide uppercase">{toast.title}</span>}
      <p className="text-xs">{toast.description}</p>
    </div>
  )
}
