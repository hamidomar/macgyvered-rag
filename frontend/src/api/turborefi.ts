import {
  TurboRefiDocumentType,
  TurboRefiIngestResponse,
  TurboRefiMessageResponse,
  TurboRefiRecommendationPacket,
  TurboRefiSessionDetail,
  TurboRefiSessionCreateResponse,
  TurboRefiSessionListEntry,
  TurboRefiSessionStatus,
  TurboRefiSessionUploadResponse
} from '@/types/turborefi'

const createHeaders = (authToken?: string): HeadersInit => {
  const headers: HeadersInit = {}

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  return headers
}

const readErrorMessage = async (response: Response) => {
  try {
    const data = await response.json()
    if (typeof data?.detail === 'string') {
      return data.detail
    }
    return JSON.stringify(data)
  } catch {
    return response.statusText
  }
}

export const createTurboRefiSessionAPI = async (
  endpoint: string,
  file: File,
  authToken?: string
): Promise<TurboRefiSessionCreateResponse> => {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${endpoint}/session`, {
    method: 'POST',
    headers: createHeaders(authToken),
    body: formData
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const uploadTurboRefiDocumentAPI = async (
  endpoint: string,
  sessionId: string,
  docType: 'paystub' | 'w2' | 'schedule_c',
  file: File,
  authToken?: string
): Promise<TurboRefiSessionUploadResponse> => {
  const formData = new FormData()
  formData.append('doc_type', docType)
  formData.append('file', file)

  const response = await fetch(`${endpoint}/session/${sessionId}/upload`, {
    method: 'POST',
    headers: createHeaders(authToken),
    body: formData
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const ingestTurboRefiDocumentAPI = async (
  endpoint: string,
  file: File,
  options?: {
    sessionId?: string
    docType?: TurboRefiDocumentType
    authToken?: string
  }
): Promise<TurboRefiIngestResponse> => {
  const formData = new FormData()
  formData.append('file', file)

  if (options?.sessionId) {
    formData.append('session_id', options.sessionId)
  }
  if (options?.docType) {
    formData.append('doc_type', options.docType)
  }

  const response = await fetch(`${endpoint}/ingest`, {
    method: 'POST',
    headers: createHeaders(options?.authToken),
    body: formData
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const getTurboRefiStatusAPI = async (
  endpoint: string,
  sessionId: string,
  authToken?: string
): Promise<TurboRefiSessionStatus> => {
  const response = await fetch(`${endpoint}/session/${sessionId}/status`, {
    method: 'GET',
    headers: createHeaders(authToken)
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const listTurboRefiSessionsAPI = async (
  endpoint: string,
  authToken?: string
): Promise<TurboRefiSessionListEntry[]> => {
  const response = await fetch(`${endpoint}/refi/sessions`, {
    method: 'GET',
    headers: createHeaders(authToken)
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  const data = await response.json()
  return Array.isArray(data?.data) ? data.data : []
}

export const getTurboRefiSessionAPI = async (
  endpoint: string,
  sessionId: string,
  authToken?: string
): Promise<TurboRefiSessionDetail> => {
  const response = await fetch(`${endpoint}/refi/sessions/${sessionId}`, {
    method: 'GET',
    headers: createHeaders(authToken)
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const deleteTurboRefiSessionAPI = async (
  endpoint: string,
  sessionId: string,
  authToken?: string
) => {
  const response = await fetch(`${endpoint}/refi/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: createHeaders(authToken)
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const sendTurboRefiMessageAPI = async (
  endpoint: string,
  sessionId: string,
  message: string,
  authToken?: string
): Promise<TurboRefiMessageResponse> => {
  const response = await fetch(`${endpoint}/session/${sessionId}/message`, {
    method: 'POST',
    headers: {
      ...createHeaders(authToken),
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ message })
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}

export const getTurboRefiResultAPI = async (
  endpoint: string,
  sessionId: string,
  authToken?: string
): Promise<TurboRefiRecommendationPacket> => {
  const response = await fetch(`${endpoint}/session/${sessionId}/result`, {
    method: 'GET',
    headers: createHeaders(authToken)
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }

  return response.json()
}
