import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import {
  AgentDetails,
  SessionEntry,
  TeamDetails,
  type ChatMessage
} from '@/types/os'

interface Store {
  hydrated: boolean
  setHydrated: () => void
  streamingErrorMessage: string
  setStreamingErrorMessage: (streamingErrorMessage: string) => void
  endpoints: {
    endpoint: string
    id__endpoint: string
  }[]
  setEndpoints: (
    endpoints: {
      endpoint: string
      id__endpoint: string
    }[]
  ) => void
  isStreaming: boolean
  setIsStreaming: (isStreaming: boolean) => void
  isEndpointActive: boolean
  setIsEndpointActive: (isActive: boolean) => void
  isEndpointLoading: boolean
  setIsEndpointLoading: (isLoading: boolean) => void
  messages: ChatMessage[]
  setMessages: (
    messages: ChatMessage[] | ((prevMessages: ChatMessage[]) => ChatMessage[])
  ) => void
  chatInputRef: React.RefObject<HTMLTextAreaElement | null>
  selectedEndpoint: string
  setSelectedEndpoint: (selectedEndpoint: string) => void
  authToken: string
  setAuthToken: (authToken: string) => void
  agents: AgentDetails[]
  setAgents: (agents: AgentDetails[]) => void
  teams: TeamDetails[]
  setTeams: (teams: TeamDetails[]) => void
  selectedModel: string
  setSelectedModel: (model: string) => void
  mode: 'agent' | 'team'
  setMode: (mode: 'agent' | 'team') => void
  sessionsData: SessionEntry[] | null
  setSessionsData: (
    sessionsData:
      | SessionEntry[]
      | ((prevSessions: SessionEntry[] | null) => SessionEntry[] | null)
  ) => void
  isSessionsLoading: boolean
  setIsSessionsLoading: (isSessionsLoading: boolean) => void
  turboRefiSession: {
    currentPhase: string | null
    useCase: string | null
    stateMachineState: string | null
    referralDecision: string | null
    fullApplicationIntent: 'proceed' | 'decline' | null
    intakePending: string[]
    documentsReceived: string[]
    documentsPending: string[]
    borrowerFacts: Record<string, unknown> | null
    receivedMortgage: Record<string, unknown> | null
    incomeDocs: Record<string, unknown>[]
    screeningAssumptions: Record<string, unknown> | null
    calculatedOutputs: Record<string, unknown> | null
    larsResult: Record<string, unknown> | null
    handoffPackage: Record<string, unknown> | null
    sourceDataWarnings: string[]
    recommendationPacket: Record<string, unknown> | null
  }
  setTurboRefiSession: (
    updates:
      | Partial<Store['turboRefiSession']>
      | ((
          prev: Store['turboRefiSession']
        ) => Partial<Store['turboRefiSession']>)
  ) => void
  resetTurboRefiSession: () => void
  turboRefiScreeningRate: number | null
  setTurboRefiScreeningRate: (turboRefiScreeningRate: number | null) => void
  isTurboRefiLoading: boolean
  setIsTurboRefiLoading: (isTurboRefiLoading: boolean) => void
}

const initialTurboRefiSession = {
  currentPhase: null,
  useCase: null,
  stateMachineState: null,
  referralDecision: null,
  fullApplicationIntent: null,
  intakePending: [],
  documentsReceived: [],
  documentsPending: [],
  borrowerFacts: null,
  receivedMortgage: null,
  incomeDocs: [],
  screeningAssumptions: null,
  calculatedOutputs: null,
  larsResult: null,
  handoffPackage: null,
  sourceDataWarnings: [],
  recommendationPacket: null
}

export const useStore = create<Store>()(
  persist(
    (set) => ({
      hydrated: false,
      setHydrated: () => set({ hydrated: true }),
      streamingErrorMessage: '',
      setStreamingErrorMessage: (streamingErrorMessage) =>
        set(() => ({ streamingErrorMessage })),
      endpoints: [],
      setEndpoints: (endpoints) => set(() => ({ endpoints })),
      isStreaming: false,
      setIsStreaming: (isStreaming) => set(() => ({ isStreaming })),
      isEndpointActive: false,
      setIsEndpointActive: (isActive) =>
        set(() => ({ isEndpointActive: isActive })),
      isEndpointLoading: true,
      setIsEndpointLoading: (isLoading) =>
        set(() => ({ isEndpointLoading: isLoading })),
      messages: [],
      setMessages: (messages) =>
        set((state) => ({
          messages:
            typeof messages === 'function' ? messages(state.messages) : messages
        })),
      chatInputRef: { current: null },
      selectedEndpoint: 'http://localhost:7777',
      setSelectedEndpoint: (selectedEndpoint) =>
        set(() => ({ selectedEndpoint })),
      authToken: '',
      setAuthToken: (authToken) => set(() => ({ authToken })),
      agents: [],
      setAgents: (agents) => set({ agents }),
      teams: [],
      setTeams: (teams) => set({ teams }),
      selectedModel: '',
      setSelectedModel: (selectedModel) => set(() => ({ selectedModel })),
      mode: 'agent',
      setMode: (mode) => set(() => ({ mode })),
      sessionsData: null,
      setSessionsData: (sessionsData) =>
        set((state) => ({
          sessionsData:
            typeof sessionsData === 'function'
              ? sessionsData(state.sessionsData)
              : sessionsData
        })),
      isSessionsLoading: false,
      setIsSessionsLoading: (isSessionsLoading) =>
        set(() => ({ isSessionsLoading })),
      turboRefiSession: initialTurboRefiSession,
      setTurboRefiSession: (updates) =>
        set((state) => ({
          turboRefiSession: {
            ...state.turboRefiSession,
            ...(typeof updates === 'function'
              ? updates(state.turboRefiSession)
              : updates)
          }
        })),
      resetTurboRefiSession: () =>
        set(() => ({ turboRefiSession: initialTurboRefiSession })),
      turboRefiScreeningRate: 6,
      setTurboRefiScreeningRate: (turboRefiScreeningRate) =>
        set(() => ({ turboRefiScreeningRate })),
      isTurboRefiLoading: false,
      setIsTurboRefiLoading: (isTurboRefiLoading) =>
        set(() => ({ isTurboRefiLoading }))
    }),
    {
      name: 'endpoint-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        selectedEndpoint: state.selectedEndpoint,
        turboRefiScreeningRate: state.turboRefiScreeningRate
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHydrated?.()
      }
    }
  )
)
