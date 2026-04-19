'use client'

import { useMemo } from 'react'

import { useStore } from '@/store'
import type { ToolCall } from '@/types/os'

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null

const isJsonRecord = (value: JsonRecord | null): value is JsonRecord =>
  value !== null

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const asText = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null

const formatMoney = (value: unknown) => {
  const numberValue = asNumber(value)
  if (numberValue === null) return null
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(numberValue)
}

const formatPercent = (value: unknown) => {
  const numberValue = asNumber(value)
  if (numberValue === null) return null
  return `${numberValue.toFixed(1)}%`
}

const formatRatioPercent = (value: unknown) => {
  const numberValue = asNumber(value)
  return numberValue === null ? null : formatPercent(numberValue * 100)
}

const labelFor = (value: string) =>
  value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())

const decisionLabel = (value: string | null) =>
  value
    ? value
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (letter) => letter.toUpperCase())
    : null

type CitationGroup = {
  gse: string
  entries: JsonRecord[]
}

type CitationFocusGroup = {
  focusLabel: string
  entries: JsonRecord[]
}

type GseAnalysisGroup = {
  gse: string
  supported: boolean | null
  overallReason: string | null
  rows: Array<{
    focusLabel: string
    sectionIds: string
    decisionDescription: string
  }>
}

const importantToolNames = new Set([
  'resolve_uc1_uc2_intake',
  'resolve_full_application_intent',
  'calculate_uc1_uc2_outputs',
  'evaluate_lars',
  'analyze_gse_eligibility',
  'review_guideline_support',
  'build_json_first_recommendation_packet'
])

const parseToolStatus = (toolCall: ToolCall) => {
  if (toolCall.tool_call_error) return 'error'
  if (!toolCall.content) return 'running'
  try {
    const parsed = JSON.parse(toolCall.content) as JsonRecord
    const status = asText(parsed.status)
    if (status) return status
  } catch {
    return 'done'
  }
  return 'done'
}

const compactToolResult = (toolCall: ToolCall) => {
  if (!toolCall.content) return 'Waiting for result'
  try {
    const parsed = JSON.parse(toolCall.content) as JsonRecord
    if (toolCall.tool_name === 'analyze_gse_eligibility') {
      const analysis = asRecord(parsed.gse_analysis)
      const supported = Object.entries(analysis ?? {})
        .filter(([, value]) => asRecord(value)?.supported === true)
        .map(([gse]) => gse.toUpperCase())
      return supported.length > 0
        ? `Supported: ${supported.join(', ')}`
        : 'GSE analysis complete'
    }
    if (toolCall.tool_name === 'review_guideline_support') {
      const retrievedGses = Array.isArray(parsed.retrieved_gses)
        ? parsed.retrieved_gses.join(', ').toUpperCase()
        : 'guides'
      return `Reviewed ${retrievedGses}`
    }
    if (toolCall.tool_name === 'build_json_first_recommendation_packet') {
      const recommendedGse = asText(parsed.recommended_gse)?.toUpperCase()
      const ltv = asNumber(parsed.ltv_percent)
      return `${recommendedGse || 'Packet'} ready${ltv !== null ? ` - LTV ${ltv.toFixed(1)}%` : ''}`
    }
    if (parsed.final_score !== undefined && parsed.decision !== undefined) {
      return `Score ${String(parsed.final_score)} - ${decisionLabel(String(parsed.decision))}`
    }
    if (parsed.status !== undefined && parsed.field_name !== undefined) {
      return `${String(parsed.field_name)}: ${String(parsed.status)}`
    }
    if (parsed.ltv_percent !== undefined) {
      return `LTV ${String(parsed.ltv_percent)}%`
    }
  } catch {
    return toolCall.content.slice(0, 96)
  }
  return toolCall.content.slice(0, 96)
}

const toolCallKey = (toolCall: ToolCall, index: number) => {
  const identityParts = [
    toolCall.tool_call_id,
    toolCall.tool_name,
    String(toolCall.created_at),
    toolCall.content ?? '',
    JSON.stringify(toolCall.tool_args ?? {})
  ].filter(Boolean)

  return `${identityParts.join('::')}::${index}`
}

const outputRows = (outputs: JsonRecord | null) => {
  if (!outputs) return []
  const rows = [
    ['LTV', formatPercent(outputs.ltv_percent)],
    ['Gross Monthly Income', formatMoney(outputs.gmi)],
    ['PI', formatMoney(outputs.old_pi)],
    ['PMI Savings', formatMoney(outputs.pmi_savings)],
    ['PITIA', formatMoney(outputs.pitia_total)],
    ['Front DTI', formatRatioPercent(outputs.front_dti)],
    ['Back DTI', formatRatioPercent(outputs.back_dti)],
    ['Original LTV', formatRatioPercent(outputs.original_ltv)],
    ['Combined LTV', formatRatioPercent(outputs.combined_ltv)]
  ]
  return rows.filter((row): row is [string, string] => Boolean(row[1]))
}

const TurboRefiInsightPanel = () => {
  const turboRefiSession = useStore((state) => state.turboRefiSession)
  const messages = useStore((state) => state.messages)
  const recommendationPacket = asRecord(turboRefiSession.recommendationPacket)
  const larsResult = asRecord(turboRefiSession.larsResult)
  const calculatedOutputs = asRecord(turboRefiSession.calculatedOutputs)
  const events = Array.isArray(larsResult?.events)
    ? larsResult.events.map(asRecord).filter(Boolean)
    : []
  const score = asNumber(larsResult?.final_score)
  const startingScore = asNumber(larsResult?.starting_score)
  const decision = asText(larsResult?.decision)
  const decisionText = decisionLabel(decision)
  const rows = outputRows(calculatedOutputs)
  const recommendedGse = asText(recommendationPacket?.recommended_gse)
  const packetIncome = formatMoney(
    recommendationPacket?.qualifying_monthly_income
  )
  const packetLtv = formatPercent(recommendationPacket?.ltv_percent)
  const packetRecommendedReason = asText(
    recommendationPacket?.recommended_gse_reason
  )
  const packetCitations = Array.isArray(
    recommendationPacket?.guideline_citations
  )
    ? recommendationPacket.guideline_citations
        .map(asRecord)
        .filter(isJsonRecord)
    : []
  const groupedCitations = useMemo<CitationGroup[]>(() => {
    if (!packetCitations.length) return []
    const groups = new Map<string, JsonRecord[]>()
    packetCitations.forEach((citation) => {
      const gse = asText(citation.gse)?.toUpperCase() ?? 'OTHER'
      const existing = groups.get(gse) ?? []
      existing.push(citation)
      groups.set(gse, existing)
    })
    return Array.from(groups.entries()).map(([gse, entries]) => ({
      gse,
      entries
    }))
  }, [packetCitations])
  const focusedCitationGroups = useMemo<
    Array<CitationGroup & { focusGroups: CitationFocusGroup[] }>
  >(
    () =>
      groupedCitations.map((group) => {
        const focusMap = new Map<string, JsonRecord[]>()
        group.entries.forEach((entry) => {
          const focusLabel =
            asText(entry.focus_label) ??
            asText(entry.focus_key) ??
            'Guide support'
          const existing = focusMap.get(focusLabel) ?? []
          existing.push(entry)
          focusMap.set(focusLabel, existing)
        })
        return {
          ...group,
          focusGroups: Array.from(focusMap.entries()).map(
            ([focusLabel, entries]) => ({
              focusLabel,
              entries
            })
          )
        }
      }),
    [groupedCitations]
  )
  const gseAnalysisGroups = useMemo<GseAnalysisGroup[]>(() => {
    const analysis = asRecord(recommendationPacket?.gse_analysis)
    if (!analysis) return []
    return Object.entries(analysis).map(([gse, value]) => {
      const record = asRecord(value)
      const focusResults = Array.isArray(record?.focus_results)
        ? record.focus_results.map(asRecord).filter(isJsonRecord)
        : []
      return {
        gse: gse.toUpperCase(),
        supported:
          typeof record?.supported === 'boolean'
            ? (record.supported as boolean)
            : null,
        overallReason: asText(record?.overall_reason),
        rows: focusResults.map((entry) => {
          const sectionIds = Array.isArray(entry.section_ids)
            ? entry.section_ids
                .map((id) => asText(id))
                .filter(Boolean)
                .join(', ')
            : ''
          return {
            focusLabel:
              asText(entry.focus_label) ??
              asText(entry.focus_key) ??
              'Guide support',
            sectionIds: sectionIds || '--',
            decisionDescription:
              asText(entry.decision_description) ??
              asText(entry.rule_summary) ??
              '--'
          }
        })
      }
    })
  }, [recommendationPacket])
  const packetReasoning = Array.isArray(recommendationPacket?.reasoning_chain)
    ? recommendationPacket.reasoning_chain
        .map((entry) => asText(entry))
        .filter(Boolean)
    : []
  const toolCalls = useMemo(
    () => messages.flatMap((message) => message.tool_calls ?? []),
    [messages]
  )
  const importantToolCalls = useMemo(
    () =>
      toolCalls.filter((toolCall) =>
        importantToolNames.has(toolCall.tool_name)
      ),
    [toolCalls]
  )
  const packetFnmaEligible =
    typeof recommendationPacket?.fnma_eligible === 'boolean'
      ? recommendationPacket.fnma_eligible
      : null
  const packetFhlmcEligible =
    typeof recommendationPacket?.fhlmc_eligible === 'boolean'
      ? recommendationPacket.fhlmc_eligible
      : null
  const packetDocs = asRecord(recommendationPacket?.documentation_status)
  const pendingDocs = Array.isArray(packetDocs?.pending)
    ? packetDocs.pending.map((entry) => asText(entry)).filter(Boolean)
    : []
  const receivedDocs = Array.isArray(packetDocs?.received)
    ? packetDocs.received.map((entry) => asText(entry)).filter(Boolean)
    : []
  const hasData = Boolean(
    turboRefiSession.currentPhase ||
      recommendationPacket ||
      larsResult ||
      calculatedOutputs ||
      turboRefiSession.handoffPackage ||
      toolCalls.length
  )

  if (!hasData) {
    return null
  }

  return (
    <aside className="hidden min-h-0 w-[21rem] shrink-0 border-l border-border bg-background px-4 py-4 font-geist lg:flex lg:flex-col">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div>
          <p className="text-sm font-medium text-primary">Decision Trace</p>
          <p className="text-xs text-secondary">
            {turboRefiSession.useCase
              ? labelFor(turboRefiSession.useCase)
              : 'No active case'}
          </p>
        </div>
        {decision ? (
          <span className="rounded-md border border-border px-2 py-1 text-xs text-primary">
            {decisionText}
          </span>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-4">
        <section className="space-y-3">
          <div className="flex items-end justify-between">
            <div>
              <p className="text-xs uppercase text-secondary">LARS Score</p>
              <p className="text-3xl font-semibold text-primary">
                {score ?? '--'}
              </p>
            </div>
            {startingScore !== null && score !== null ? (
              <p className="text-xs text-secondary">
                {startingScore - score} points reduced
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            {events.length > 0 ? (
              events.map((event, index) => (
                <div
                  key={`${String(event?.factor_code)}-${index}`}
                  className="border-l border-border pl-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-primary">
                      {String(event?.factor_code ?? 'Factor')}
                    </p>
                    <p className="text-xs text-destructive">
                      -{String(event?.deduction ?? 0)}
                    </p>
                  </div>
                  <p className="text-xs text-secondary">
                    {String(event?.factor_name ?? 'Score factor')}
                  </p>
                  <p className="mt-1 text-xs text-secondary">
                    Score after: {String(event?.score_after ?? '--')}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm text-secondary">No LARS deductions.</p>
            )}
          </div>
        </section>

        {recommendationPacket ? (
          <section className="space-y-2">
            <p className="text-xs uppercase text-secondary">Recommendation</p>
            <div className="space-y-2 rounded-lg border border-border p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs text-secondary">Recommended GSE</span>
                <span className="text-sm font-medium text-primary">
                  {recommendedGse ? recommendedGse.toUpperCase() : '--'}
                </span>
              </div>
              {packetRecommendedReason ? (
                <div className="space-y-1">
                  <span className="text-xs text-secondary">Why selected</span>
                  <p className="text-sm text-primary">
                    {packetRecommendedReason}
                  </p>
                </div>
              ) : null}
              {packetIncome ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-secondary">
                    Qualifying Income
                  </span>
                  <span className="text-sm text-primary">{packetIncome}</span>
                </div>
              ) : null}
              {packetLtv ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-secondary">Packet LTV</span>
                  <span className="text-sm text-primary">{packetLtv}</span>
                </div>
              ) : null}
              {packetFnmaEligible !== null ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-secondary">FNMA</span>
                  <span className="text-sm text-primary">
                    {packetFnmaEligible ? 'Supported' : 'Not Supported'}
                  </span>
                </div>
              ) : null}
              {packetFhlmcEligible !== null ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-secondary">FHLMC</span>
                  <span className="text-sm text-primary">
                    {packetFhlmcEligible ? 'Supported' : 'Not Supported'}
                  </span>
                </div>
              ) : null}
              {receivedDocs.length > 0 ? (
                <div className="border-t border-border pt-2">
                  <p className="text-xs text-secondary">
                    Packet received {receivedDocs.length} required item
                    {receivedDocs.length === 1 ? '' : 's'}.
                  </p>
                  <p className="mt-1 text-xs text-secondary">
                    {receivedDocs.join(', ')}
                  </p>
                </div>
              ) : null}
              {pendingDocs.length > 0 ? (
                <div className="border-t border-border pt-2">
                  <p className="text-xs text-secondary">Still pending</p>
                  <p className="mt-1 text-xs text-secondary">
                    {pendingDocs.join(', ')}
                  </p>
                </div>
              ) : null}
              {packetReasoning.length > 0 ? (
                <div className="space-y-1 border-t border-border pt-2">
                  {packetReasoning.map((reason, index) => (
                    <p
                      key={`${reason}-${index}`}
                      className="text-xs text-secondary"
                    >
                      {reason}
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}

        {gseAnalysisGroups.length > 0 ? (
          <section className="space-y-2">
            <p className="text-xs uppercase text-secondary">Guide Evidence</p>
            <div className="space-y-2">
              {gseAnalysisGroups.map((group) => (
                <div
                  key={group.gse}
                  className="rounded-lg border border-border p-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-primary">
                        {group.gse} Basis
                      </p>
                      {group.overallReason ? (
                        <p className="mt-1 text-[11px] text-secondary">
                          {group.overallReason}
                        </p>
                      ) : null}
                    </div>
                    <span className="rounded-md bg-background-secondary px-2 py-1 text-[11px] text-secondary">
                      {group.supported === null
                        ? group.gse
                        : group.supported
                          ? `${group.gse} Supported`
                          : `${group.gse} Not Supported`}
                    </span>
                  </div>

                  <div className="mt-3 overflow-hidden rounded-md border border-border">
                    <table className="w-full table-fixed text-left">
                      <thead className="bg-background-secondary">
                        <tr>
                          <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                            Purpose
                          </th>
                          <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                            Section
                          </th>
                          <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                            Decision Basis
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.rows.map((row, index) => (
                          <tr
                            key={`${group.gse}-${row.focusLabel}-${row.sectionIds}-${index}`}
                            className="border-t border-border align-top"
                          >
                            <td className="px-2 py-2 text-xs text-secondary">
                              {row.focusLabel}
                            </td>
                            <td className="px-2 py-2 text-xs font-medium text-primary">
                              {row.sectionIds}
                            </td>
                            <td className="px-2 py-2 text-xs text-secondary">
                              {row.decisionDescription}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : focusedCitationGroups.length > 0 ? (
          <section className="space-y-2">
            <p className="text-xs uppercase text-secondary">Guide Evidence</p>
            <div className="space-y-2">
              {focusedCitationGroups.map((group) => {
                const uniqueSections = Array.from(
                  new Set(
                    group.entries
                      .map((entry) => asText(entry.section))
                      .filter(Boolean)
                  )
                )
                return (
                  <div
                    key={group.gse}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-medium text-primary">
                          {group.gse === 'OTHER'
                            ? 'Guide Basis'
                            : `${group.gse} Basis`}
                        </p>
                        <p className="mt-1 text-[11px] text-secondary">
                          {uniqueSections.length} section
                          {uniqueSections.length === 1 ? '' : 's'}
                        </p>
                      </div>
                      {group.gse !== 'OTHER' ? (
                        <span className="rounded-md bg-background-secondary px-2 py-1 text-[11px] text-secondary">
                          {group.gse}
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-3 overflow-hidden rounded-md border border-border">
                      <table className="w-full table-fixed text-left">
                        <thead className="bg-background-secondary">
                          <tr>
                            <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                              Purpose
                            </th>
                            <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                              Section
                            </th>
                            <th className="px-2 py-2 text-[11px] font-medium text-secondary">
                              Decision Basis
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.focusGroups.flatMap((focusGroup, focusIndex) =>
                            focusGroup.entries.map((citation, index) => {
                              const section = asText(citation.section)
                              const finding =
                                asText(citation.finding) ??
                                asText(citation.why_selected) ??
                                asText(citation.title)
                              return (
                                <tr
                                  key={`${group.gse}-${focusGroup.focusLabel}-${section}-${index}`}
                                  className="border-t border-border align-top"
                                >
                                  <td className="px-2 py-2 text-xs text-secondary">
                                    {index === 0 ? focusGroup.focusLabel : ''}
                                    {index === 0 && focusIndex > 0 ? '' : ''}
                                  </td>
                                  <td className="px-2 py-2 text-xs font-medium text-primary">
                                    {section || 'Guide Section'}
                                  </td>
                                  <td className="px-2 py-2 text-xs text-secondary">
                                    {finding || '--'}
                                  </td>
                                </tr>
                              )
                            })
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        ) : null}

        {rows.length > 0 ? (
          <section className="space-y-2">
            <p className="text-xs uppercase text-secondary">
              Calculated Outputs
            </p>
            <div className="divide-y divide-border">
              {rows.map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="text-xs text-secondary">{label}</span>
                  <span className="text-sm text-primary">{value}</span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {importantToolCalls.length > 0 ? (
          <section className="space-y-2">
            <p className="text-xs uppercase text-secondary">Tool Calls</p>
            <div className="space-y-2">
              {importantToolCalls.map((toolCall, index) => (
                <div
                  key={toolCallKey(toolCall, index)}
                  className="rounded-lg border border-border p-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="truncate font-dmmono text-xs text-primary">
                      {toolCall.tool_name}
                    </p>
                    <span className="rounded-md bg-background-secondary px-2 py-1 text-[11px] text-secondary">
                      {parseToolStatus(toolCall)}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-secondary">
                    {compactToolResult(toolCall)}
                  </p>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </aside>
  )
}

export default TurboRefiInsightPanel
