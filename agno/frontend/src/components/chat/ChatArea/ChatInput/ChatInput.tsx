'use client'

import { type ChangeEvent, useEffect, useRef, useState } from 'react'
import { useQueryState } from 'nuqs'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import Icon from '@/components/ui/icon'
import { TextArea } from '@/components/ui/textarea'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { useTurboRefiSession } from '@/hooks/useTurboRefiSession'
import { useStore } from '@/store'

const documentLabel = (value: string) =>
  value === 'mortgage_statement'
    ? 'Mortgage Statement'
    : value === 'schedule_c'
      ? 'Schedule C'
      : value === 'paystub'
        ? 'Paystub'
        : 'W-2'

const phaseLabel = (value: string | null) =>
  value ? value.replace(/_/g, ' ') : 'awaiting mortgage statement'

const ChatInput = () => {
  const { chatInputRef } = useStore()
  const { handleStreamResponse } = useAIChatStreamHandler()
  const { ingestDocument, refreshStatus, isTurboRefiLoading } =
    useTurboRefiSession()
  const [selectedAgent] = useQueryState('agent')
  const [sessionId, setSessionId] = useQueryState('session')
  const [inputMessage, setInputMessage] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const isStreaming = useStore((state) => state.isStreaming)
  const mode = useStore((state) => state.mode)
  const turboRefiSession = useStore((state) => state.turboRefiSession)
  const resetTurboRefiSession = useStore((state) => state.resetTurboRefiSession)

  useEffect(() => {
    if (sessionId) {
      void (async () => {
        const status = await refreshStatus(sessionId)
        if (!status) {
          setSessionId(null)
        }
      })()
    } else {
      resetTurboRefiSession()
    }
  }, [refreshStatus, resetTurboRefiSession, sessionId, setSessionId])

  const canUpload = mode === 'agent' && !isTurboRefiLoading && !isStreaming
  const canChat = Boolean(mode === 'agent' && selectedAgent && sessionId)
  const placeholder =
    mode !== 'agent'
      ? 'Switch to agent mode to use TurboRefi'
      : !sessionId
        ? 'Attach a mortgage statement to begin'
        : !selectedAgent
          ? 'Select the TurboRefi agent to continue'
          : 'Ask your loan officer anything'

  const handleSubmit = async () => {
    if (!inputMessage.trim()) return

    const currentMessage = inputMessage
    setInputMessage('')

    try {
      await handleStreamResponse(currentMessage)
    } catch (error) {
      toast.error(
        `Error in handleSubmit: ${
          error instanceof Error ? error.message : String(error)
        }`
      )
    }
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''

    if (!file) return

    try {
      await ingestDocument(file, sessionId ?? undefined)
      requestAnimationFrame(() => chatInputRef?.current?.focus())
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to upload document'
      )
    }
  }

  const receivedDocuments = turboRefiSession.documentsReceived

  return (
    <div className="mx-auto w-full max-w-2xl font-geist">
      <div className="mb-2 flex flex-wrap items-center gap-2 px-1 text-xs">
        <span className="rounded-full border border-border bg-background px-3 py-1 text-foreground">
          Phase: {phaseLabel(turboRefiSession.currentPhase)}
        </span>
        {sessionId ? (
          <>
            {receivedDocuments.map((doc) => (
              <span
                key={doc}
                className="rounded-full border border-border bg-background px-3 py-1 text-muted-foreground"
              >
                {documentLabel(doc)}
              </span>
            ))}
            {turboRefiSession.documentsPending.length > 0 && (
              <span className="text-muted-foreground">
                Pending: {turboRefiSession.documentsPending.join(', ')}
              </span>
            )}
          </>
        ) : (
          <span className="text-muted-foreground">
            Upload the mortgage statement first. After that, attach paystubs,
            W-2s, or Schedule C files in the same chat.
          </span>
        )}
      </div>

      <div className="relative mb-1 flex w-full items-end gap-x-2 rounded-2xl border border-border bg-background p-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,image/*"
          onChange={handleFileChange}
          className="hidden"
          disabled={!canUpload}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleUploadClick}
          disabled={!canUpload}
          className="h-10 shrink-0 rounded-xl border-border bg-background px-3 text-foreground hover:bg-accent"
        >
          <Icon type="plus-icon" size="xs" className="text-foreground" />
          <span>{isTurboRefiLoading ? 'Uploading' : sessionId ? 'Attach' : 'Upload'}</span>
        </Button>
        <TextArea
          placeholder={placeholder}
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === 'Enter' &&
              !e.nativeEvent.isComposing &&
              !e.shiftKey &&
              !isStreaming
            ) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          className="min-h-[40px] border-0 bg-transparent px-2 text-sm text-foreground shadow-none focus-visible:border-transparent focus-visible:ring-0"
          disabled={!canChat}
          ref={chatInputRef}
        />
        <Button
          onClick={handleSubmit}
          disabled={!canChat || !inputMessage.trim() || isStreaming}
          size="icon"
          className="rounded-xl bg-primary text-primary-foreground"
        >
          <Icon type="send" className="text-primary-foreground" />
        </Button>
      </div>
    </div>
  )
}

export default ChatInput
