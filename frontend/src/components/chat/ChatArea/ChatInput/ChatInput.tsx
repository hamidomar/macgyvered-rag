'use client'

import { type ChangeEvent, useEffect, useRef, useState } from 'react'
import { useQueryState } from 'nuqs'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import Icon from '@/components/ui/icon'
import { TextArea } from '@/components/ui/textarea'
import { useTurboRefiSession } from '@/hooks/useTurboRefiSession'
import { isTurboRefiLoanOfficer } from '@/lib/turborefi'
import { useStore } from '@/store'

const documentLabel = (value: string) =>
  value === 'schedule_c'
    ? 'Schedule C'
    : value === 'tax_bill'
      ? 'Tax Bill'
      : value === 'insurance'
        ? 'Insurance'
        : value === 'identity'
          ? 'Identity'
          : value === 'pmi_statement'
            ? 'PMI Statement'
            : value === 'closing_disclosure'
              ? 'Closing Disclosure'
    : value === 'paystub'
      ? 'Paystub'
      : 'W-2'

const phaseLabel = (value: string | null) =>
  value ? value.replace(/_/g, ' ') : 'awaiting received json'

const summarizeDocumentCounts = (documentTypes: string[]) => {
  const counts = new Map<string, number>()
  for (const documentType of documentTypes) {
    counts.set(documentType, (counts.get(documentType) ?? 0) + 1)
  }
  return Array.from(counts.entries())
}

const ChatInput = () => {
  const { chatInputRef } = useStore()
  const {
    createSessionFromReceivedJson,
    ingestDocument,
    loadSession,
    sendMessage,
    isTurboRefiLoading
  } = useTurboRefiSession()
  const [selectedAgent] = useQueryState('agent')
  const [turboRefiSessionId, setTurboRefiSessionId] =
    useQueryState('refi_session')
  const [inputMessage, setInputMessage] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const isStreaming = useStore((state) => state.isStreaming)
  const mode = useStore((state) => state.mode)
  const agents = useStore((state) => state.agents)
  const turboRefiSession = useStore((state) => state.turboRefiSession)
  const turboRefiScreeningRate = useStore(
    (state) => state.turboRefiScreeningRate
  )
  const setTurboRefiScreeningRate = useStore(
    (state) => state.setTurboRefiScreeningRate
  )
  const resetTurboRefiSession = useStore((state) => state.resetTurboRefiSession)
  const selectedAgentDetails = agents.find(
    (agent) => agent.id === selectedAgent
  )
  const isLoanOfficerSelected = selectedAgent
    ? selectedAgentDetails
      ? isTurboRefiLoanOfficer(selectedAgentDetails.name)
      : true
    : false
  const hasActiveTurboRefiSession = Boolean(
    turboRefiSessionId &&
      (turboRefiSession.currentPhase ||
        turboRefiSession.documentsReceived.length > 0 ||
        turboRefiSession.documentsPending.length > 0 ||
        turboRefiSession.intakePending.length > 0)
  )

  useEffect(() => {
    if (turboRefiSessionId) {
      void (async () => {
        try {
          await loadSession(turboRefiSessionId)
        } catch {
          setTurboRefiSessionId(null)
        }
      })()
    } else {
      resetTurboRefiSession()
    }
  }, [
    loadSession,
    resetTurboRefiSession,
    setTurboRefiSessionId,
    turboRefiSessionId
  ])

  const canUpload =
    mode === 'agent' &&
    hasActiveTurboRefiSession &&
    !isTurboRefiLoading &&
    !isStreaming
  const canType = Boolean(mode === 'agent' && isLoanOfficerSelected)
  const placeholder =
    mode !== 'agent'
      ? 'Switch to agent mode to use TurboRefi'
      : !hasActiveTurboRefiSession
        ? 'Paste received mortgage JSON and send to begin'
        : !selectedAgent || !isLoanOfficerSelected
          ? 'Select the TurboRefi LOA agent to continue'
          : turboRefiSession.intakePending.length > 0
            ? 'Answer the intake questions so I can request the right documents'
            : 'Reply here or attach the next requested document'

  const handleSubmit = async () => {
    if (!inputMessage.trim()) return

    const currentMessage = inputMessage
    setInputMessage('')

    try {
      if (!hasActiveTurboRefiSession || !turboRefiSessionId) {
        let payload: Record<string, unknown>
        try {
          payload = JSON.parse(currentMessage)
        } catch {
          throw new Error(
            'Paste a valid received mortgage JSON payload to start the session'
          )
        }
        await createSessionFromReceivedJson(payload, {
          newRate: turboRefiScreeningRate ?? undefined,
          sessionName: 'Received JSON'
        })
        return
      }
      await sendMessage(turboRefiSessionId, currentMessage)
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
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''

    if (files.length === 0) return

    let nextSessionId = turboRefiSessionId ?? undefined
    let successCount = 0

    for (const file of files) {
      try {
        const result = await ingestDocument(file, nextSessionId)
        nextSessionId = result.session_id
        successCount += 1
      } catch (error) {
        toast.error(
          `${file.name}: ${
            error instanceof Error ? error.message : 'Failed to upload document'
          }`
        )
      }
    }

    if (files.length > 1 && successCount > 0) {
      toast.success(
        `Uploaded ${successCount} of ${files.length} selected documents`
      )
    }

    requestAnimationFrame(() => chatInputRef?.current?.focus())
  }

  const receivedDocuments = summarizeDocumentCounts(
    turboRefiSession.documentsReceived
  )
  const activeScreeningRate =
    typeof turboRefiSession.screeningAssumptions?.new_rate === 'number'
      ? turboRefiSession.screeningAssumptions.new_rate
      : null

  return (
    <div className="mx-auto w-full max-w-2xl font-geist">
      <div className="mb-2 flex flex-wrap items-center gap-2 px-1 text-xs">
        <span className="text-foreground rounded-full border border-border bg-background px-3 py-1">
          Phase: {phaseLabel(turboRefiSession.currentPhase)}
        </span>
        {hasActiveTurboRefiSession ? (
          <span className="text-muted-foreground rounded-full border border-border bg-background px-3 py-1">
            Screening rate:{' '}
            {activeScreeningRate === null
              ? 'not set'
              : `${activeScreeningRate.toFixed(3)}%`}
          </span>
        ) : (
          <label className="text-muted-foreground flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1">
            <span>Screening rate</span>
            <input
              type="number"
              min="0"
              step="0.125"
              value={turboRefiScreeningRate ?? ''}
              onChange={(event) => {
                const value = event.target.value
                setTurboRefiScreeningRate(value ? Number(value) : null)
              }}
              className="text-foreground w-16 border-0 bg-transparent text-right outline-none"
              disabled={isTurboRefiLoading || isStreaming}
            />
            <span>%</span>
          </label>
        )}
        {hasActiveTurboRefiSession ? (
          <>
            {turboRefiSession.intakePending.length > 0 && (
              <span className="text-muted-foreground">
                Need: {turboRefiSession.intakePending.join(', ')}
              </span>
            )}
            {receivedDocuments.map(([doc, count]) => (
              <span
                key={doc}
                className="text-muted-foreground rounded-full border border-border bg-background px-3 py-1"
              >
                {documentLabel(doc)}
                {count > 1 ? ` x${count}` : ''}
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
            Paste the received mortgage JSON in the message box to start. After
            that, attach the requested supporting documents here.
          </span>
        )}
      </div>

      <div className="relative mb-1 flex w-full items-end gap-x-2 rounded-2xl border border-border bg-background p-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,image/*"
          multiple
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
          className="text-foreground h-10 shrink-0 rounded-xl border-border bg-background px-3 hover:bg-accent"
        >
          <Icon type="plus-icon" size="xs" className="text-foreground" />
          <span>
            {isTurboRefiLoading
              ? 'Uploading'
              : hasActiveTurboRefiSession
                ? 'Attach'
                : 'Attach'}
          </span>
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
          className="text-foreground min-h-[40px] border-0 bg-transparent px-2 text-sm shadow-none focus-visible:border-transparent focus-visible:ring-0"
          disabled={!canType}
          ref={chatInputRef}
        />
        <Button
          onClick={handleSubmit}
          disabled={!canType || !inputMessage.trim() || isStreaming}
          size="icon"
          className="text-primary-foreground rounded-xl bg-primary"
        >
          <Icon type="send" className="text-primary-foreground" />
        </Button>
      </div>
    </div>
  )
}

export default ChatInput
