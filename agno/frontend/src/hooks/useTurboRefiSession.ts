'use client'

import { useCallback } from 'react'
import { toast } from 'sonner'
import { useQueryState } from 'nuqs'

import {
  getTurboRefiResultAPI,
  getTurboRefiStatusAPI,
  ingestTurboRefiDocumentAPI
} from '@/api/turborefi'
import { constructEndpointUrl } from '@/lib/constructEndpointUrl'
import { useStore } from '@/store'
import { type ToolCall } from '@/types/os'

const getDocumentLabel = (documentType: string) =>
  documentType === 'mortgage_statement'
    ? 'mortgage statement'
    : documentType === 'schedule_c'
      ? 'Schedule C'
      : documentType === 'paystub'
        ? 'paystub'
        : 'W-2'

export const useTurboRefiSession = () => {
  const selectedEndpoint = useStore((state) => state.selectedEndpoint)
  const authToken = useStore((state) => state.authToken)
  const setMessages = useStore((state) => state.setMessages)
  const setSessionsData = useStore((state) => state.setSessionsData)
  const setTurboRefiSession = useStore((state) => state.setTurboRefiSession)
  const resetTurboRefiSession = useStore((state) => state.resetTurboRefiSession)
  const isTurboRefiLoading = useStore((state) => state.isTurboRefiLoading)
  const setIsTurboRefiLoading = useStore((state) => state.setIsTurboRefiLoading)
  const [, setSessionId] = useQueryState('session')

  const refreshStatus = useCallback(
    async (sessionId: string) => {
      try {
        setTurboRefiSession({ recommendationPacket: null })
        const status = await getTurboRefiStatusAPI(
          constructEndpointUrl(selectedEndpoint),
          sessionId,
          authToken
        )
        setTurboRefiSession({
          currentPhase: status.current_phase,
          documentsReceived: status.documents_received,
          documentsPending: status.documents_pending,
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
      resetTurboRefiSession,
      selectedEndpoint,
      setTurboRefiSession
    ]
  )

  const ingestDocument = useCallback(
    async (file: File, sessionId?: string) => {
      setIsTurboRefiLoading(true)
      try {
        const endpoint = constructEndpointUrl(selectedEndpoint)
        const result = await ingestTurboRefiDocumentAPI(endpoint, file, {
          sessionId,
          authToken
        })

        const userMessage = {
          role: 'user' as const,
          content: `Uploaded ${getDocumentLabel(result.document_type)}: ${file.name}`,
          created_at: Math.floor(Date.now() / 1000)
        }
        const toolCalls: ToolCall[] = result.tool_trace.map((entry, index) => ({
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
          tool_call_error: false,
          metrics: {
            time: 0
          },
          created_at: Math.floor(Date.now() / 1000) + index
        }))
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

        setSessionId(result.session_id)
        setSessionsData((prev) => {
          const next = prev ?? []
          if (next.some((entry) => entry.session_id === result.session_id)) {
            return next
          }
          return [
            {
              session_id: result.session_id,
              session_name: `Mortgage Statement - ${file.name}`,
              created_at: Math.floor(Date.now() / 1000)
            },
            ...next
          ]
        })

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
      refreshStatus,
      selectedEndpoint,
      setIsTurboRefiLoading,
      setMessages,
      setSessionId,
      setSessionsData,
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
        const endpoint = constructEndpointUrl(selectedEndpoint)
        const packet = await getTurboRefiResultAPI(endpoint, sessionId, authToken)
        setTurboRefiSession({ recommendationPacket: packet })
        toast.success('Loaded recommendation packet')
        return packet
      } finally {
        setIsTurboRefiLoading(false)
      }
    },
    [authToken, selectedEndpoint, setIsTurboRefiLoading, setTurboRefiSession]
  )

  return {
    ingestDocument,
    createSessionFromMortgage,
    uploadSecondaryDocument,
    refreshStatus,
    loadRecommendationPacket,
    isTurboRefiLoading
  }
}
