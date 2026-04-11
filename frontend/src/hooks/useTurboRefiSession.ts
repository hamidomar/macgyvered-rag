'use client'

import { useCallback } from 'react'
import { toast } from 'sonner'
import { useQueryState } from 'nuqs'

import {
  deleteTurboRefiSessionAPI,
  getTurboRefiSessionAPI,
  getTurboRefiResultAPI,
  getTurboRefiStatusAPI,
  ingestTurboRefiDocumentAPI,
  listTurboRefiSessionsAPI,
  sendTurboRefiMessageAPI
} from '@/api/turborefi'
import { constructEndpointUrl } from '@/lib/constructEndpointUrl'
import { useStore } from '@/store'
import { type SessionEntry, type ToolCall } from '@/types/os'

const getDocumentLabel = (documentType: string) =>
  documentType === 'mortgage_statement'
    ? 'mortgage statement'
    : documentType === 'schedule_c'
      ? 'Schedule C'
      : documentType === 'paystub'
        ? 'paystub'
        : 'W-2'

const TURBO_REFI_DEFAULT_ENDPOINT = 'http://localhost:7777'

const toToolCalls = (
  toolTrace: Array<{
    tool: string
    arguments: Record<string, unknown>
    result: unknown
  }>
): ToolCall[] =>
  toolTrace.map((entry, index) => ({
    role: 'tool',
    content:
      typeof entry.result === 'string'
        ? entry.result
        : JSON.stringify(entry.result, null, 2),
    tool_call_id: `${entry.tool}-${Date.now()}-${index}`,
    tool_name: entry.tool,
    tool_args: Object.fromEntries(
      Object.entries(entry.arguments).map(([key, value]) => [
        key,
        typeof value === 'string' ? value : JSON.stringify(value)
      ])
    ),
    tool_call_error:
      typeof entry.result === 'object' &&
      entry.result !== null &&
      'status' in entry.result &&
      (entry.result as { status?: string }).status === 'error',
    metrics: {
      time: 0
    },
    created_at: Math.floor(Date.now() / 1000) + index
  }))

export const useTurboRefiSession = () => {
  const selectedEndpoint = useStore((state) => state.selectedEndpoint)
  const authToken = useStore((state) => state.authToken)
  const setMessages = useStore((state) => state.setMessages)
  const setSessionsData = useStore((state) => state.setSessionsData)
  const setTurboRefiSession = useStore((state) => state.setTurboRefiSession)
  const resetTurboRefiSession = useStore((state) => state.resetTurboRefiSession)
  const isTurboRefiLoading = useStore((state) => state.isTurboRefiLoading)
  const setIsTurboRefiLoading = useStore((state) => state.setIsTurboRefiLoading)
  const [, setTurboRefiSessionId] = useQueryState('refi_session')

  const getTurboRefiEndpoint = useCallback(() => {
    const endpoint = constructEndpointUrl(
      selectedEndpoint || TURBO_REFI_DEFAULT_ENDPOINT
    )

    if (typeof window !== 'undefined') {
      const frontendOrigin = window.location.origin.replace(/\/$/, '')
      if (!endpoint || endpoint === frontendOrigin) {
        return TURBO_REFI_DEFAULT_ENDPOINT
      }
    }

    return endpoint || TURBO_REFI_DEFAULT_ENDPOINT
  }, [selectedEndpoint])

  const refreshStatus = useCallback(
    async (sessionId: string) => {
      try {
        setTurboRefiSession({ recommendationPacket: null })
        const status = await getTurboRefiStatusAPI(
          getTurboRefiEndpoint(),
          sessionId,
          authToken
        )
        setTurboRefiSession({
          currentPhase: status.current_phase,
          intakePending: status.intake_pending,
          documentsReceived: status.documents_received,
          documentsPending: status.documents_pending,
          borrowerFacts: status.borrower_facts,
          mortgageData: status.mortgage_data,
          incomeDocs: status.income_docs
        })
        return status
      } catch {
        resetTurboRefiSession()
        return null
      }
    },
    [
      authToken,
      getTurboRefiEndpoint,
      resetTurboRefiSession,
      setTurboRefiSession
    ]
  )

  const listSessions = useCallback(async (): Promise<SessionEntry[]> => {
    const endpoint = getTurboRefiEndpoint()
    const sessions = await listTurboRefiSessionsAPI(endpoint, authToken)
    const entries = sessions.map((session) => ({
      session_id: session.session_id,
      session_name: session.session_name,
      created_at: session.created_at,
      updated_at: session.updated_at
    }))
    setSessionsData(entries)
    return entries
  }, [authToken, getTurboRefiEndpoint, setSessionsData])

  const loadSession = useCallback(
    async (sessionId: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const session = await getTurboRefiSessionAPI(endpoint, sessionId, authToken)
        setMessages(
          session.messages.map((message) => ({
            role: message.role,
            content: message.content,
            created_at: message.created_at,
            tool_calls: message.tool_calls
          }))
        )
        setTurboRefiSessionId(session.session_id)
        setTurboRefiSession({
          currentPhase: session.current_phase,
          intakePending: session.intake_pending,
          documentsReceived: session.documents_received,
          documentsPending: session.documents_pending,
          borrowerFacts: session.borrower_facts,
          mortgageData: session.mortgage_data,
          incomeDocs: session.income_docs,
          recommendationPacket: session.recommendation_packet
        })
        return session
      } catch (error) {
        resetTurboRefiSession()
        setMessages([])
        throw error
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [
      authToken,
      getTurboRefiEndpoint,
      resetTurboRefiSession,
      setIsTurboRefiLoading,
      setMessages,
      setTurboRefiSession,
      setTurboRefiSessionId
    ]
  )

  const deleteSession = useCallback(
    async (sessionId: string) => {
      const endpoint = getTurboRefiEndpoint()
      await deleteTurboRefiSessionAPI(endpoint, sessionId, authToken)
      setSessionsData((prev) =>
        prev ? prev.filter((session) => session.session_id !== sessionId) : prev
      )
    },
    [authToken, getTurboRefiEndpoint, setSessionsData]
  )

  const appendIngestMessages = useCallback(
    (file: File, result: Awaited<ReturnType<typeof ingestTurboRefiDocumentAPI>>, sessionId?: string) => {
      const userMessage = {
        role: 'user' as const,
        content: `Uploaded ${getDocumentLabel(result.document_type)}: ${file.name}`,
        created_at: Math.floor(Date.now() / 1000)
      }
      const toolCalls = toToolCalls(result.tool_trace)
      const agentMessage = {
        role: 'agent' as const,
        content: result.response,
        tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
        created_at: Math.floor(Date.now() / 1000) + 1
      }

      if (sessionId) {
        setMessages((prev) => [...prev, userMessage, agentMessage])
      } else {
        setMessages([userMessage, agentMessage])
      }
    },
    [setMessages]
  )

  const ingestDocument = useCallback(
    async (file: File, sessionId?: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        let effectiveSessionId = sessionId
        let result
        try {
          result = await ingestTurboRefiDocumentAPI(endpoint, file, {
            sessionId: effectiveSessionId,
            authToken
          })
        } catch (error) {
          const isStaleSession =
            effectiveSessionId &&
            error instanceof Error &&
            error.message.toLowerCase().includes('session not found')

          if (!isStaleSession) {
            throw error
          }

          setTurboRefiSessionId(null)
          resetTurboRefiSession()
          effectiveSessionId = undefined
          result = await ingestTurboRefiDocumentAPI(endpoint, file, {
            authToken
          })
        }

        appendIngestMessages(file, result, effectiveSessionId)

        setTurboRefiSessionId(result.session_id)

        setTurboRefiSession({ recommendationPacket: null })
        await refreshStatus(result.session_id)
        toast.success(`${getDocumentLabel(result.document_type)} uploaded`)
        return result
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [
      authToken,
      appendIngestMessages,
      getTurboRefiEndpoint,
      refreshStatus,
      resetTurboRefiSession,
      setIsTurboRefiLoading,
      setTurboRefiSessionId,
      setTurboRefiSession
    ]
  )

  const createSessionFromMortgage = useCallback(
    async (file: File) => ingestDocument(file),
    [ingestDocument]
  )

  const uploadSecondaryDocument = useCallback(
    async (sessionId: string, _docType: 'paystub' | 'w2' | 'schedule_c', file: File) =>
      ingestDocument(file, sessionId),
    [ingestDocument]
  )

  const loadRecommendationPacket = useCallback(
    async (sessionId: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const packet = await getTurboRefiResultAPI(endpoint, sessionId, authToken)
        setTurboRefiSession({ recommendationPacket: packet })
        toast.success('Loaded recommendation packet')
        return packet
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [authToken, getTurboRefiEndpoint, setIsTurboRefiLoading, setTurboRefiSession]
  )

  const sendMessage = useCallback(
    async (sessionId: string, message: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const result = await sendTurboRefiMessageAPI(
          endpoint,
          sessionId,
          message,
          authToken
        )

        setMessages((prev) => [
          ...prev,
          {
            role: 'user' as const,
            content: message,
            created_at: Math.floor(Date.now() / 1000)
          },
          {
            role: 'agent' as const,
            content: result.response,
            tool_calls:
              result.tool_trace.length > 0
                ? toToolCalls(result.tool_trace)
                : undefined,
            created_at: Math.floor(Date.now() / 1000) + 1
          }
        ])

        await refreshStatus(sessionId)
        return result
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [
      authToken,
      getTurboRefiEndpoint,
      refreshStatus,
      setIsTurboRefiLoading,
      setMessages
    ]
  )

  return {
    ingestDocument,
    createSessionFromMortgage,
    uploadSecondaryDocument,
    listSessions,
    loadSession,
    deleteSession,
    refreshStatus,
    sendMessage,
    loadRecommendationPacket,
    isTurboRefiLoading
  }
}
