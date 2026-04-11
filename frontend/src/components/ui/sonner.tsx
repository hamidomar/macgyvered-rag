'use client'

import { Toaster as Sonner } from 'sonner'

type ToasterProps = React.ComponentProps<typeof Sonner>

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      richColors
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            'group toast group-[.toaster]:border group-[.toaster]:border-zinc-700 group-[.toaster]:bg-zinc-950 group-[.toaster]:text-zinc-50 group-[.toaster]:shadow-lg',
          title: 'group-[.toast]:text-zinc-50',
          description: 'group-[.toast]:text-zinc-300',
          actionButton:
            'group-[.toast]:bg-zinc-100 group-[.toast]:text-zinc-950',
          cancelButton:
            'group-[.toast]:bg-zinc-800 group-[.toast]:text-zinc-100',
          error:
            'group-[.toaster]:border-red-900 group-[.toaster]:bg-red-950 group-[.toaster]:text-red-50',
          success:
            'group-[.toaster]:border-emerald-900 group-[.toaster]:bg-emerald-950 group-[.toaster]:text-emerald-50',
          warning:
            'group-[.toaster]:border-amber-900 group-[.toaster]:bg-amber-950 group-[.toaster]:text-amber-50',
          info:
            'group-[.toaster]:border-sky-900 group-[.toaster]:bg-sky-950 group-[.toaster]:text-sky-50'
        }
      }}
      {...props}
    />
  )
}

export { Toaster }
