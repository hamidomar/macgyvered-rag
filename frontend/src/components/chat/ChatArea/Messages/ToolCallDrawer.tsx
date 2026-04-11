'use client'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import Icon from '@/components/ui/icon'
import type { ToolCall } from '@/types/os'

const parseMaybeJson = (value: string) => {
  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

const formatInlineValue = (value: unknown) => {
  if (typeof value === 'string') {
    return JSON.stringify(value)
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const formatBlockValue = (value: unknown) => {
  if (typeof value === 'string') {
    const parsed = parseMaybeJson(value)
    if (typeof parsed === 'string') {
      return parsed
    }
    return JSON.stringify(parsed, null, 2)
  }

  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const buildSignature = (toolCall: ToolCall) => {
  const args = Object.entries(toolCall.tool_args ?? {})
  if (args.length === 0) {
    return `${toolCall.tool_name}()`
  }

  const signature = args
    .map(([key, rawValue]) => `${key}=${formatInlineValue(parseMaybeJson(rawValue))}`)
    .join(', ')

  return `${toolCall.tool_name}(${signature})`
}

interface ToolCallDrawerProps {
  toolCall: ToolCall | null
  onOpenChange: (open: boolean) => void
}

const ToolCallDrawer = ({ toolCall, onOpenChange }: ToolCallDrawerProps) => {
  const isOpen = toolCall !== null

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="left-0 top-0 h-dvh max-h-dvh w-full max-w-none translate-x-0 translate-y-0 gap-0 rounded-none border-0 border-border bg-background p-0 sm:left-auto sm:right-0 sm:w-[min(42rem,48vw)] sm:max-w-[42rem] sm:border-l">
        {toolCall ? (
          <div className="flex h-full flex-col">
            <DialogHeader className="border-b border-border px-6 py-5 text-left">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-accent p-2 text-primary/80">
                  <Icon type="hammer" size="sm" color="secondary" />
                </div>
                <div className="space-y-1">
                  <DialogTitle className="font-geist text-lg">
                    {toolCall.tool_name}
                  </DialogTitle>
                  <DialogDescription className="text-sm text-secondary">
                    Inspect the exact tool input and response payload.
                  </DialogDescription>
                </div>
                <div
                  className={`ml-auto rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.08em] ${
                    toolCall.tool_call_error
                      ? 'bg-destructive/10 text-destructive'
                      : 'bg-emerald-500/10 text-emerald-400'
                  }`}
                >
                  {toolCall.tool_call_error ? 'Error' : 'Success'}
                </div>
              </div>
            </DialogHeader>

            <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
              <section className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-[0.08em] text-secondary">
                  Call Signature
                </p>
                <pre className="overflow-x-auto rounded-xl border border-border bg-background-secondary p-4 font-dmmono text-xs leading-6 text-primary">
                  {buildSignature(toolCall)}
                </pre>
              </section>

              <section className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-[0.08em] text-secondary">
                  Arguments
                </p>
                <pre className="overflow-x-auto rounded-xl border border-border bg-background-secondary p-4 font-dmmono text-xs leading-6 text-primary">
                  {formatBlockValue(toolCall.tool_args)}
                </pre>
              </section>

              <section className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-[0.08em] text-secondary">
                  Response
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-xl border border-border bg-background-secondary p-4 font-dmmono text-xs leading-6 text-primary">
                  {formatBlockValue(toolCall.content)}
                </pre>
              </section>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export default ToolCallDrawer
