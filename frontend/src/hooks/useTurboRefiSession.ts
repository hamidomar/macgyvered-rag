'use client'

import { useCallback } from 'react'
import { toast } from 'sonner'
import { useQueryState } from 'nuqs'

import {
  createTurboRefiSessionFromJsonAPI,
  deleteTurboRefiSessionAPI,
  getTurboRefiMessageStreamUrl,
  getTurboRefiSessionAPI,
  getTurboRefiResultAPI,
  getTurboRefiStatusAPI,
  ingestTurboRefiDocumentAPI,
  listTurboRefiSessionsAPI,
  uploadTurboRefiDocumentJsonAPI
} from '@/api/turborefi'
import { constructEndpointUrl } from '@/lib/constructEndpointUrl'
import { useStore } from '@/store'
import {
  RunEvent,
  type RunResponse,
  type SessionEntry,
  type ToolCall
} from '@/types/os'
import useAIResponseStream from './useAIResponseStream'

const getDocumentLabel = (documentType: string) =>
  documentType === 'schedule_c'
    ? 'Schedule C'
    : documentType === 'tax_bill'
      ? 'property tax bill'
      : documentType === 'insurance'
        ? 'homeowners insurance declaration'
        : documentType === 'identity'
          ? 'government ID'
          : documentType === 'pmi_statement'
            ? 'PMI statement'
            : documentType === 'closing_disclosure'
              ? 'closing disclosure'
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

const mergeToolCall = (
  toolCall: ToolCall,
  existingToolCalls: ToolCall[] = []
) => {
  const toolCallId =
    toolCall.tool_call_id || `${toolCall.tool_name}-${toolCall.created_at}`
  const existingIndex = existingToolCalls.findIndex(
    (existing) =>
      existing.tool_call_id === toolCall.tool_call_id ||
      `${existing.tool_name}-${existing.created_at}` === toolCallId
  )

  if (existingIndex < 0) {
    return [...existingToolCalls, toolCall]
  }

  const nextToolCalls = [...existingToolCalls]
  nextToolCalls[existingIndex] = {
    ...nextToolCalls[existingIndex],
    ...toolCall
  }
  return nextToolCalls
}

const mergeChunkToolCalls = (
  chunk: RunResponse,
  existingToolCalls: ToolCall[] = []
) => {
  let nextToolCalls = [...existingToolCalls]
  if (chunk.tool) {
    nextToolCalls = mergeToolCall(chunk.tool, nextToolCalls)
  }
  if (chunk.tools) {
    for (const toolCall of chunk.tools) {
      nextToolCalls = mergeToolCall(toolCall, nextToolCalls)
    }
  }
  return nextToolCalls
}

export const useTurboRefiSession = () => {
  const selectedEndpoint = useStore((state) => state.selectedEndpoint)
  const authToken = useStore((state) => state.authToken)
  const setMessages = useStore((state) => state.setMessages)
  const setSessionsData = useStore((state) => state.setSessionsData)
  const setTurboRefiSession = useStore((state) => state.setTurboRefiSession)
  const resetTurboRefiSession = useStore((state) => state.resetTurboRefiSession)
  const isTurboRefiLoading = useStore((state) => state.isTurboRefiLoading)
  const setIsTurboRefiLoading = useStore((state) => state.setIsTurboRefiLoading)
  const setIsStreaming = useStore((state) => state.setIsStreaming)
  const setStreamingErrorMessage = useStore(
    (state) => state.setStreamingErrorMessage
  )
  const [, setTurboRefiSessionId] = useQueryState('refi_session')
  const { streamResponse } = useAIResponseStream()

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
          useCase: status.use_case ?? null,
          stateMachineState: status.state_machine_state ?? null,
          referralDecision: status.referral_decision ?? null,
          fullApplicationIntent: status.full_application_intent ?? null,
          intakePending: status.intake_pending,
          documentsReceived: status.documents_received,
          documentsPending: status.documents_pending,
          borrowerFacts: status.borrower_facts,
          receivedMortgage: status.received_mortgage ?? null,
          incomeDocs: status.income_docs,
          calculatedOutputs: status.calculated_outputs ?? null,
          larsResult: status.lars_result ?? null,
          handoffPackage: status.handoff_package ?? null,
          sourceDataWarnings: status.source_data_warnings ?? []
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
        const session = await getTurboRefiSessionAPI(
          endpoint,
          sessionId,
          authToken
        )
        setMessages(
          session.messages.map((message) => ({
            role: message.role,
            content: message.content,
            created_at: message.created_at,
            tool_calls: message.tool_calls
          }))
        )
        setTurboRefiSession({
          currentPhase: session.current_phase,
          useCase: session.use_case ?? null,
          stateMachineState: session.state_machine_state ?? null,
          referralDecision: session.referral_decision ?? null,
          fullApplicationIntent: session.full_application_intent ?? null,
          intakePending: session.intake_pending,
          documentsReceived: session.documents_received,
          documentsPending: session.documents_pending,
          borrowerFacts: session.borrower_facts,
          receivedMortgage: session.received_mortgage ?? null,
          incomeDocs: session.income_docs,
          calculatedOutputs: session.calculated_outputs ?? null,
          larsResult: session.lars_result ?? null,
          handoffPackage: session.handoff_package ?? null,
          sourceDataWarnings: session.source_data_warnings ?? [],
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
      setTurboRefiSession
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
    (
      file: File,
      result: Awaited<ReturnType<typeof ingestTurboRefiDocumentAPI>>,
      sessionId?: string
    ) => {
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
        if (!sessionId) {
          throw new Error(
            'Create a session from received JSON before uploading supporting documents'
          )
        }
        let result
        try {
          result = await ingestTurboRefiDocumentAPI(endpoint, file, {
            sessionId,
            authToken
          })
        } catch (error) {
          const isStaleSession =
            error instanceof Error &&
            error.message.toLowerCase().includes('session not found')

          if (!isStaleSession) {
            throw error
          }

          setTurboRefiSessionId(null)
          resetTurboRefiSession()
          throw new Error(
            'The active session no longer exists. Load the received JSON again to continue.'
          )
        }

        appendIngestMessages(file, result, sessionId)

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

  const createSessionFromReceivedJson = useCallback(
    async (
      payload: Record<string, unknown>,
      options?: { sessionName?: string }
    ) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const result = await createTurboRefiSessionFromJsonAPI(
          endpoint,
          payload,
          {
            ...options,
            authToken
          }
        )
        setTurboRefiSessionId(result.session_id)
        setMessages([
          {
            role: 'user' as const,
            content: 'Received JSON input',
            created_at: Math.floor(Date.now() / 1000)
          },
          {
            role: 'agent' as const,
            content: result.response,
            tool_calls:
              result.tool_trace && result.tool_trace.length > 0
                ? toToolCalls(result.tool_trace)
                : undefined,
            created_at: Math.floor(Date.now() / 1000) + 1
          }
        ])
        await refreshStatus(result.session_id)
        toast.success('Received JSON loaded')
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
      setMessages,
      setTurboRefiSessionId
    ]
  )

  const uploadDocumentJson = useCallback(
    async (
      sessionId: string,
      docType:
        | 'paystub'
        | 'w2'
        | 'tax_bill'
        | 'insurance'
        | 'identity'
        | 'pmi_statement'
        | 'closing_disclosure',
      data: Record<string, unknown>
    ) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const result = await uploadTurboRefiDocumentJsonAPI(
          endpoint,
          sessionId,
          docType,
          data,
          authToken
        )
        setMessages((prev) => [
          ...prev,
          {
            role: 'user' as const,
            content: `Uploaded ${getDocumentLabel(docType)}`,
            created_at: Math.floor(Date.now() / 1000)
          },
          {
            role: 'agent' as const,
            content: result.response,
            tool_calls:
              result.tool_trace && result.tool_trace.length > 0
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

  const loadRecommendationPacket = useCallback(
    async (sessionId: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = getTurboRefiEndpoint()
        const packet = await getTurboRefiResultAPI(
          endpoint,
          sessionId,
          authToken
        )
        setTurboRefiSession({ recommendationPacket: packet })
        toast.success('Loaded recommendation packet')
        return packet
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [
      authToken,
      getTurboRefiEndpoint,
      setIsTurboRefiLoading,
      setTurboRefiSession
    ]
  )

  const sendMessage = useCallback(
    async (sessionId: string, message: string) => {
      setIsTurboRefiLoading(true)
      setIsStreaming(true)
      setStreamingErrorMessage('')
      let streamFailed = false
      try {
        const endpoint = getTurboRefiEndpoint()
        setMessages((prev) => [
          ...prev,
          {
            role: 'user' as const,
            content: message,
            created_at: Math.floor(Date.now() / 1000)
          },
          {
            role: 'agent' as const,
            content: '',
            tool_calls: [],
            created_at: Math.floor(Date.now() / 1000) + 1
          }
        ])

        await streamResponse({
          apiUrl: getTurboRefiMessageStreamUrl(endpoint, sessionId),
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
          requestBody: { message },
          onChunk: (chunk: RunResponse) => {
            if (
              chunk.event === RunEvent.ToolCallStarted ||
              chunk.event === RunEvent.ToolCallCompleted
            ) {
              setMessages((prev) => {
                const nextMessages = [...prev]
                const lastMessage = nextMessages[nextMessages.length - 1]
                if (lastMessage?.role === 'agent') {
                  lastMessage.tool_calls = mergeChunkToolCalls(
                    chunk,
                    lastMessage.tool_calls
                  )
                }
                return nextMessages
              })
              return
            }

            if (
              chunk.event === RunEvent.RunContent ||
              chunk.event === RunEvent.RunCompleted
            ) {
              setMessages((prev) => {
                const nextMessages = [...prev]
                const lastMessage = nextMessages[nextMessages.length - 1]
                if (lastMessage?.role === 'agent') {
                  lastMessage.content =
                    typeof chunk.content === 'string'
                      ? chunk.content
                      : JSON.stringify(chunk.content ?? '')
                  lastMessage.tool_calls = mergeChunkToolCalls(
                    chunk,
                    lastMessage.tool_calls
                  )
                }
                return nextMessages
              })
            }

            if (chunk.event === RunEvent.RunError) {
              streamFailed = true
              setStreamingErrorMessage(String(chunk.content || 'Stream failed'))
              setMessages((prev) => {
                const nextMessages = [...prev]
                const lastMessage = nextMessages[nextMessages.length - 1]
                if (lastMessage?.role === 'agent') {
                  lastMessage.streamingError = true
                }
                return nextMessages
              })
            }
          },
          onError: (error) => {
            streamFailed = true
            setStreamingErrorMessage(error.message)
            setMessages((prev) => {
              const nextMessages = [...prev]
              const lastMessage = nextMessages[nextMessages.length - 1]
              if (lastMessage?.role === 'agent') {
                lastMessage.streamingError = true
              }
              return nextMessages
            })
          },
          onComplete: () => {}
        })

        if (!streamFailed) {
          const status = await refreshStatus(sessionId)
          if (
            status?.full_application_intent === 'proceed' &&
            status.referral_decision === 'AUTOMATED'
          ) {
            const packet = await getTurboRefiResultAPI(
              endpoint,
              sessionId,
              authToken
            )
            setTurboRefiSession({ recommendationPacket: packet })
          }
        }
      } finally {
        setIsTurboRefiLoading(false)
        setIsStreaming(false)
      }
    },
    [
      authToken,
      getTurboRefiEndpoint,
      refreshStatus,
      setIsTurboRefiLoading,
      setIsStreaming,
      setMessages,
      setTurboRefiSession,
      setStreamingErrorMessage,
      streamResponse
    ]
  )

  return {
    ingestDocument,
    createSessionFromReceivedJson,
    uploadDocumentJson,
    listSessions,
    loadSession,
    deleteSession,
    refreshStatus,
    sendMessage,
    loadRecommendationPacket,
    isTurboRefiLoading
  }
}
