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
  documents_received: string[]
  documents_pending: string[]
  mortgage_data: Record<string, unknown> | null
  income_docs: Record<string, unknown>[]
}

export type TurboRefiRecommendationPacket = Record<string, unknown>
