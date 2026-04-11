import type { ToolCall } from '@/types/os'

export type TurboRefiDocumentType =
  | 'mortgage_statement'
  | 'paystub'
  | 'w2'
  | 'schedule_c'

export interface TurboRefiSessionCreateResponse {
  session_id: string
  response: string
  current_phase: string
}

export interface TurboRefiSessionUploadResponse {
  response: string
  current_phase: string
}

export interface TurboRefiMessageResponse {
  response: string
  tool_trace: Array<{
    tool: string
    arguments: Record<string, unknown>
    result: unknown
  }>
}

export interface TurboRefiConversationMessage {
  role: 'user' | 'agent'
  content: string
  created_at: number
  tool_calls?: ToolCall[]
}

export interface TurboRefiIngestResponse {
  session_id: string
  response: string
  current_phase: string
  document_type: TurboRefiDocumentType
  tool_trace: Array<{
    tool: string
    arguments: Record<string, unknown>
    result: unknown
  }>
}

export interface TurboRefiSessionStatus {
  current_phase: string | null
  intake_pending: string[]
  documents_received: string[]
  documents_pending: string[]
  verification_status: string | null
  borrower_facts: Record<string, unknown>
  mortgage_data: Record<string, unknown> | null
  income_docs: Record<string, unknown>[]
}

export interface TurboRefiSessionListEntry {
  session_id: string
  session_name: string
  created_at: number
  updated_at: number
  current_phase: string
}

export interface TurboRefiSessionDetail extends TurboRefiSessionStatus {
  session_id: string
  session_name: string
  created_at: number
  updated_at: number
  messages: TurboRefiConversationMessage[]
  recommendation_packet: Record<string, unknown> | null
  verification_report: Record<string, unknown> | null
}

export type TurboRefiRecommendationPacket = Record<string, unknown>
