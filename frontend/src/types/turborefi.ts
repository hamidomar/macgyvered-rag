import type { ToolCall } from '@/types/os'

export type TurboRefiDocumentType =
  | 'paystub'
  | 'w2'
  | 'schedule_c'
  | 'tax_bill'
  | 'insurance'
  | 'identity'
  | 'pmi_statement'
  | 'closing_disclosure'

export type TurboRefiToolTrace = Array<{
  tool: string
  arguments: Record<string, unknown>
  result: unknown
}>

export interface TurboRefiSessionCreateResponse {
  session_id: string
  response: string
  current_phase: string
  use_case?: string
  state_machine_state?: string
  lars_result?: Record<string, unknown> | null
  handoff_package?: Record<string, unknown> | null
  tool_trace?: TurboRefiToolTrace
}

export interface TurboRefiSessionUploadResponse {
  response: string
  current_phase: string
  state_machine_state?: string
  lars_result?: Record<string, unknown> | null
  handoff_package?: Record<string, unknown> | null
  tool_trace?: TurboRefiToolTrace
}

export interface TurboRefiMessageResponse {
  response: string
  tool_trace: TurboRefiToolTrace
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
  tool_trace: TurboRefiToolTrace
}

export interface TurboRefiSessionStatus {
  current_phase: string | null
  use_case?: string
  state_machine_state?: string
  referral_decision?: string | null
  full_application_intent?: 'proceed' | 'decline' | null
  intake_pending: string[]
  documents_received: string[]
  documents_pending: string[]
  borrower_facts: Record<string, unknown>
  received_mortgage?: Record<string, unknown> | null
  income_docs: Record<string, unknown>[]
  calculated_outputs?: Record<string, unknown>
  lars_result?: Record<string, unknown> | null
  handoff_package?: Record<string, unknown> | null
  source_data_warnings?: string[]
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
  borrower_id_token?: string | null
  messages: TurboRefiConversationMessage[]
  recommendation_packet: Record<string, unknown> | null
}

export type TurboRefiRecommendationPacket = Record<string, unknown>
