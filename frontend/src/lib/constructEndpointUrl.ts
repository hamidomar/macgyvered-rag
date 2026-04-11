export const constructEndpointUrl = (
  value: string | null | undefined
): string => {
  if (!value) return ''

  const normalizedValue = decodeURIComponent(value).trim()

  const browserFallback = (() => {
    if (typeof window === 'undefined') return null
    return `${window.location.protocol}//${window.location.hostname}:7777`
  })()

  const normalizeParsedUrl = (url: URL) => {
    const isFrontendDevOrigin =
      typeof window !== 'undefined' &&
      url.origin === window.location.origin &&
      window.location.port === '3000'

    if (isFrontendDevOrigin && browserFallback) {
      return browserFallback
    }

    return url.origin
  }

  if (
    normalizedValue.startsWith('http://') ||
    normalizedValue.startsWith('https://')
  ) {
    try {
      const parsed = new URL(normalizedValue)
      return normalizeParsedUrl(parsed)
    } catch {
      return normalizedValue
        .replace(/\/(v1|verifier|runner)\/?$/i, '')
        .replace(/\/$/, '')
    }
  }

  // Check if the endpoint is localhost or an IP address
  if (
    normalizedValue.startsWith('localhost') ||
    /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/.test(normalizedValue)
  ) {
    try {
      const parsed = new URL(`http://${normalizedValue}`)
      return normalizeParsedUrl(parsed)
    } catch {
      return `http://${normalizedValue}`
    }
  }

  // For all other cases, default to HTTPS
  try {
    const parsed = new URL(`https://${normalizedValue}`)
    return normalizeParsedUrl(parsed)
  } catch {
    return `https://${normalizedValue}`
  }
}
